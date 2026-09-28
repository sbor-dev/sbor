import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import click

from validation.common import (
    JsonObject,
    load_yaml_mapping,
    required_mapping,
    required_text,
)
from validation.downloader import prepare_review
from validation.judge import configure_judge_pi, run_judge
from validation.judgments import load_judgment
from validation.reports import load_reports
from validation.reviewer import (
    agent_user_ids,
    configure_pi,
    load_llm_configuration,
    run_reviewer,
)
from validation.run_artifacts import (
    create_run_artifacts,
    load_experiment_metadata,
    validate_dataset_version,
    validate_runtime_models,
)


def load_input_items(path: Path) -> list[JsonObject]:
    items: list[JsonObject] = []

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                message = f"Invalid JSON at {path}:{line_number}: {error}"

                raise ValueError(message) from error

            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}")

            items.append(payload)

    return sorted(items, key=lambda item: required_text(item, "key"))


def item_limit(configuration: JsonObject) -> int | None:
    value = configuration.get("item_limit")

    if value is None:
        return None

    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("item_limit must be a positive integer or null")

    return value


def select_items(items: list[JsonObject], limit: int | None) -> list[JsonObject]:
    if limit is None:
        return items

    return items[:limit]


def load_labels(path: Path) -> dict[str, JsonObject]:
    labels: dict[str, JsonObject] = {}

    for label in load_input_items(path):
        key = required_text(label, "key")

        if key in labels:
            raise ValueError(f"Duplicate label key {key}")

        defects = label.get("defects")

        if not isinstance(defects, list):
            raise ValueError(f"Expected defects array for label {key}")

        labels[key] = label

    return labels


def run_item(
    item: JsonObject,
    label: JsonObject | None,
    output_dir: Path,
    model: str,
    verbose: bool,
) -> JsonObject:
    key = required_text(item, "key")
    mr = required_mapping(item, "mr")
    title = required_text(mr, "title")
    base_revision = required_text(mr, "base_sha")
    target_revision = required_text(mr, "head_sha")
    description = mr.get("description")

    if not isinstance(description, str):
        raise ValueError("Expected string field mr.description")

    result_dir = output_dir / "items" / key
    result_dir.mkdir(parents=True, exist_ok=True)
    started_at = _timestamp()
    stage = "fetch"
    stages: JsonObject = {
        name: {"started_at": None, "finished_at": None}
        for name in ("fetch", "reviewer", "judge")
    }
    diff: JsonObject = {
        "base_revision": base_revision,
        "target_revision": target_revision,
        "sha256": None,
    }

    try:
        if label is None:
            raise ValueError(f"Missing label for {key}")

        with tempfile.TemporaryDirectory(prefix=f"sbor-{key[:12]}-") as temporary:
            work_dir = Path(temporary)
            user_id, group_id = agent_user_ids()
            os.chown(work_dir, user_id, group_id)
            work_dir.chmod(0o755)
            stages["fetch"]["started_at"] = _timestamp()

            if verbose:
                click.echo(f"{key}: preparing repository", err=True)

            prepared = prepare_review(item, work_dir)
            stages["fetch"]["finished_at"] = _timestamp()
            diff["sha256"] = prepared.diff_sha256
            report_dir = work_dir / "report"
            stage = "reviewer"
            stages["reviewer"]["started_at"] = _timestamp()

            if verbose:
                click.echo(f"{key}: running reviewer", err=True)

            run_reviewer(
                prepared,
                report_dir,
                model,
                title,
                description,
                verbose,
            )
            stages["reviewer"]["finished_at"] = _timestamp()
            stage = "report_validation"

            if verbose:
                click.echo(f"{key}: validating report", err=True)

            findings = load_reports(report_dir, prepared.repository_dir)
            shutil.copy2(report_dir / "report.json", result_dir / "report.json")
            shutil.copy2(report_dir / "report.md", result_dir / "report.md")
            judgment_dir = work_dir / "judgment"
            judgment_path = judgment_dir / "judgment.json"
            stage = "judge"
            stages["judge"]["started_at"] = _timestamp()

            if verbose:
                label_defects = label["defects"]
                click.echo(
                    f"{key}: running judge for {len(label_defects)} labels and "
                    f"{len(findings)} findings",
                    err=True,
                )

            run_judge(
                prepared,
                report_dir / "report.json",
                judgment_path,
                model,
                key,
                label,
                verbose,
            )
            stages["judge"]["finished_at"] = _timestamp()
            stage = "judgment_validation"

            if verbose:
                click.echo(f"{key}: validating judgment", err=True)

            judgment_output_path = result_dir / "judgment.json"
            shutil.copy2(judgment_path, judgment_output_path)
            judgment = load_judgment(judgment_path, label, findings)

            if verbose:
                click.echo(
                    f"{key}: judgment validated with "
                    f"{len(judgment['label_assessments'])} label assessments and "
                    f"{len(judgment['reviewer_assessments'])} reviewer assessments",
                    err=True,
                )

            shutil.copy2(judgment_path, judgment_output_path)

        result = _item_result(
            key,
            "succeeded",
            "completed",
            started_at,
            stages,
            diff,
            None,
        )
    except Exception as error:
        result = _item_result(
            key,
            "failed",
            stage,
            started_at,
            stages,
            diff,
            str(error),
        )
        _write_json(result_dir / "result.json", result)
        raise

    _write_json(result_dir / "result.json", result)
    return result


def _item_result(
    key: str,
    status: str,
    stage: str,
    started_at: str,
    stages: JsonObject,
    diff: JsonObject,
    error: str | None,
) -> JsonObject:
    return {
        "schema_version": "1.0",
        "item_key": key,
        "status": status,
        "stage": stage,
        "started_at": started_at,
        "finished_at": _timestamp(),
        "stages": stages,
        "diff": diff,
        "error": error,
    }


def _write_json(path: Path, payload: JsonObject) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@click.command()
@click.option(
    "--validation-config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--metadata",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--code-revision", required=True)
@click.option("--code-dirty", type=click.BOOL, required=True)
@click.option(
    "--llm-config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--llm-config-stdin", is_flag=True)
@click.option(
    "--dataset-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--labels-path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
)
def main(
    validation_config: Path,
    metadata: Path,
    code_revision: str,
    code_dirty: bool,
    llm_config: Path | None,
    llm_config_stdin: bool,
    dataset_dir: Path,
    labels_path: Path,
    output_dir: Path,
) -> None:
    configuration = load_yaml_mapping(validation_config)
    experiment_metadata = load_experiment_metadata(metadata)
    limit = item_limit(configuration)

    if (llm_config is not None) == llm_config_stdin:
        raise click.ClickException(
            "Provide exactly one of --llm-config or --llm-config-stdin"
        )

    llm_configuration = load_llm_configuration(llm_config, llm_config_stdin)
    model = configure_pi(llm_configuration)
    judge_model = configure_judge_pi(llm_configuration)

    if judge_model != model:
        raise click.ClickException("Reviewer and judge models do not match")

    validate_runtime_models(experiment_metadata, model)
    validate_dataset_version(experiment_metadata, dataset_dir / "metadata.json")

    items = select_items(load_input_items(dataset_dir / "input.jsonl"), limit)
    labels = load_labels(labels_path)
    verbose = os.environ.get("SBOR_VALIDATION_VERBOSE") == "true"
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = create_run_artifacts(
        output_dir,
        metadata,
        validation_config,
        experiment_metadata,
        code_revision,
        code_dirty,
        len(items),
    )
    results: list[JsonObject] = []
    status = "failed"

    try:
        for item in items:
            key = required_text(item, "key")

            try:
                results.append(
                    run_item(item, labels.get(key), artifacts.run_dir, model, verbose)
                )
            except (
                OSError,
                RuntimeError,
                ValueError,
                subprocess.SubprocessError,
            ) as error:
                click.echo(f"{key}: {error}", err=True)
                results.append({"key": key, "status": "failed", "error": str(error)})

        failed = [result for result in results if result["status"] == "failed"]
        status = "failed" if failed else "completed"
    finally:
        artifacts.finish(status)

    if failed:
        raise click.ClickException(f"Validation failed for {len(failed)} item(s)")


if __name__ == "__main__":
    main()
