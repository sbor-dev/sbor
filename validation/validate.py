import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

import click

from validation.run_artifacts import load_experiment_metadata

RUNTIME_ENVIRONMENT_VARIABLES = (
    "SBOR_REVIEWER_MODEL",
    "SBOR_REVIEWER_BASE_URL",
    "SBOR_REVIEWER_API",
    "SBOR_REVIEWER_TOKEN",
    "SBOR_JUDGE_MODEL",
    "SBOR_JUDGE_BASE_URL",
    "SBOR_JUDGE_API",
    "SBOR_JUDGE_TOKEN",
)


def run_command(command: list[str], input_text: str | None = None) -> None:
    result = subprocess.run(command, input=input_text, text=True, check=False)

    if result.returncode:
        raise click.ClickException(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}"
        )


def image_exists(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
    )

    return result.returncode == 0


def docker_command(
    reviewer_input_dir: Path,
    judge_labels_dir: Path,
    output_dir: Path,
    validation_config: Path,
    metadata: Path,
    code_revision: str,
    code_dirty: bool,
    image: str,
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    source = os.environ if environment is None else environment
    command = [
        "docker",
        "run",
        "--rm",
        "--add-host=host.docker.internal:host-gateway",
    ]

    for variable in RUNTIME_ENVIRONMENT_VARIABLES:
        if variable in source:
            command.extend(["--env", variable])

    command.extend(
        [
            "--mount",
            f"type=bind,source={reviewer_input_dir.resolve()},target=/input,readonly",
            "--mount",
            f"type=bind,source={judge_labels_dir.resolve()},target=/labels,readonly",
            "--mount",
            "type=bind,source="
            f"{validation_config.resolve()},target=/run/sbor/validation.yaml,readonly",
            "--mount",
            f"type=bind,source={metadata.resolve()},target=/run/sbor/metadata.yaml,readonly",
            "--mount",
            f"type=bind,source={output_dir.resolve()},target=/output",
            image,
            "/app/.venv/bin/python",
            "-m",
            "validation.runner",
            "--validation-config",
            "/run/sbor/validation.yaml",
            "--metadata",
            "/run/sbor/metadata.yaml",
            "--code-revision",
            code_revision,
            "--code-dirty",
            str(code_dirty).lower(),
            "--dataset-dir",
            "/input",
            "--labels-path",
            "/labels/labels.jsonl",
            "--output-dir",
            "/output",
        ]
    )

    return command


@click.command()
@click.option(
    "--dataset-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--config",
    "validation_config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("config/validation.yaml"),
    show_default=True,
)
@click.option(
    "--metadata",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--image", default="sbor", show_default=True)
@click.option("--rebuild", is_flag=True)
def main(
    dataset_dir: Path,
    output_dir: Path,
    validation_config: Path,
    metadata: Path,
    image: str,
    rebuild: bool,
) -> None:
    load_experiment_metadata(metadata)

    if rebuild or not image_exists(image):
        run_command(["docker", "build", "--tag", image, "."])

    output_dir.mkdir(parents=True, exist_ok=True)
    code_revision, code_dirty = git_state(Path(__file__).resolve().parent.parent)

    with (
        tempfile.TemporaryDirectory(
            prefix="sbor-reviewer-input-"
        ) as reviewer_temporary,
        tempfile.TemporaryDirectory(prefix="sbor-judge-labels-") as judge_temporary,
    ):
        reviewer_input_dir = Path(reviewer_temporary)
        shutil.copy2(
            dataset_dir / "metadata.json",
            reviewer_input_dir / "metadata.json",
        )
        shutil.copy2(dataset_dir / "input.jsonl", reviewer_input_dir / "input.jsonl")
        judge_labels_dir = Path(judge_temporary)
        labels_path = judge_labels_dir / "labels.jsonl"
        shutil.copy2(dataset_dir / "labels.jsonl", labels_path)
        judge_labels_dir.chmod(0o700)
        labels_path.chmod(0o600)
        command = docker_command(
            reviewer_input_dir,
            judge_labels_dir,
            output_dir,
            validation_config,
            metadata,
            code_revision,
            code_dirty,
            image,
        )
        run_command(command)


def git_state(directory: Path) -> tuple[str, bool]:
    revision = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )

    if revision.returncode:
        raise click.ClickException("Could not determine the code revision")

    status = subprocess.run(
        ["git", "-C", str(directory), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )

    if status.returncode:
        raise click.ClickException("Could not determine whether the code is dirty")

    return revision.stdout.strip(), bool(status.stdout.strip())


if __name__ == "__main__":
    main()
