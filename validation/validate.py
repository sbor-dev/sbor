import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click


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


def read_llm_config(path: Path | None) -> str:
    if path is None:
        return sys.stdin.read()

    return path.read_text(encoding="utf-8")


def docker_command(
    reviewer_input_dir: Path,
    judge_labels_dir: Path,
    output_dir: Path,
    validation_config: Path,
    image: str,
    verbose: bool,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--add-host=host.docker.internal:host-gateway",
    ]

    if verbose:
        command.extend(["--env", "SBOR_VALIDATION_VERBOSE=true"])

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
            f"type=bind,source={output_dir.resolve()},target=/output",
            image,
            "/app/.venv/bin/python",
            "-m",
            "validation.runner",
            "--validation-config",
            "/run/sbor/validation.yaml",
            "--dataset-dir",
            "/input",
            "--labels-path",
            "/labels/labels.jsonl",
            "--output-dir",
            "/output",
            "--llm-config-stdin",
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
    "--llm-config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--image", default="sbor", show_default=True)
@click.option("--rebuild", is_flag=True)
@click.option("--verbose", is_flag=True)
def main(
    dataset_dir: Path,
    output_dir: Path,
    validation_config: Path,
    llm_config: Path | None,
    image: str,
    rebuild: bool,
    verbose: bool,
) -> None:
    if rebuild or not image_exists(image):
        run_command(["docker", "build", "--tag", image, "."])

    output_dir.mkdir(parents=True, exist_ok=True)
    llm_config_text = read_llm_config(llm_config)

    if not llm_config_text.strip():
        raise click.ClickException("LLM configuration is empty")

    with (
        tempfile.TemporaryDirectory(
            prefix="sbor-reviewer-input-"
        ) as reviewer_temporary,
        tempfile.TemporaryDirectory(prefix="sbor-judge-labels-") as judge_temporary,
    ):
        reviewer_input_dir = Path(reviewer_temporary)
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
            image,
            verbose,
        )
        run_command(command, llm_config_text)


if __name__ == "__main__":
    main()
