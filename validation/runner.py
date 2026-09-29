import json
import multiprocessing
import os
import shutil
import signal
import subprocess
import tempfile
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
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


def item_timeout_seconds(configuration: JsonObject) -> int:
    value = configuration.get("item_timeout_seconds")

    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("item_timeout_seconds must be a positive integer")

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
    result_path = result_dir / "result.json"
    _write_item_progress(
        result_path,
        key,
        stage,
        started_at,
        stages,
        diff,
    )

    try:
        if label is None:
            raise ValueError(f"Missing label for {key}")

        with tempfile.TemporaryDirectory(prefix=f"sbor-{key[:12]}-") as temporary:
            work_dir = Path(temporary)
            user_id, group_id = agent_user_ids()
            os.chown(work_dir, user_id, group_id)
            work_dir.chmod(0o755)
            stages["fetch"]["started_at"] = _timestamp()
            _write_item_progress(
                result_path,
                key,
                stage,
                started_at,
                stages,
                diff,
            )

            if verbose:
                click.echo(f"{key}: preparing repository", err=True)

            prepared = prepare_review(item, work_dir)
            stages["fetch"]["finished_at"] = _timestamp()
            diff["sha256"] = prepared.diff_sha256
            report_dir = work_dir / "report"
            stage = "reviewer"
            stages["reviewer"]["started_at"] = _timestamp()
            _write_item_progress(
                result_path,
                key,
                stage,
                started_at,
                stages,
                diff,
            )

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
            _write_item_progress(
                result_path,
                key,
                stage,
                started_at,
                stages,
                diff,
            )

            if verbose:
                click.echo(f"{key}: validating report", err=True)

            findings = load_reports(report_dir, prepared.repository_dir)
            shutil.copy2(report_dir / "report.json", result_dir / "report.json")
            shutil.copy2(report_dir / "report.md", result_dir / "report.md")
            judgment_dir = work_dir / "judgment"
            judgment_path = judgment_dir / "judgment.json"
            stage = "judge"
            stages["judge"]["started_at"] = _timestamp()
            _write_item_progress(
                result_path,
                key,
                stage,
                started_at,
                stages,
                diff,
            )

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
            _write_item_progress(
                result_path,
                key,
                stage,
                started_at,
                stages,
                diff,
            )

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
            _timestamp(),
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
            _timestamp(),
        )
        _write_json(result_path, result)
        raise

    _write_json(result_path, result)
    return result


def run_item_with_timeout(
    item: JsonObject,
    label: JsonObject | None,
    output_dir: Path,
    model: str,
    verbose: bool,
    timeout_seconds: int,
) -> JsonObject:
    context = multiprocessing.get_context("fork")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_run_item_process,
        args=(
            child_connection,
            item,
            label,
            output_dir,
            model,
            verbose,
        ),
    )
    process.start()
    child_connection.close()
    process.join(timeout_seconds)

    if process.is_alive():
        _terminate_process_group(process)
        parent_connection.close()
        key = required_text(item, "key")
        message = f"Item timed out after {timeout_seconds} seconds"
        click.echo(f"{key}: {message}", err=True)
        return _finalize_interrupted_item(item, output_dir, "timed_out", message)

    result: JsonObject

    if parent_connection.poll():
        result = parent_connection.recv()
    else:
        message = f"Item process exited with code {process.exitcode}"
        result = _finalize_interrupted_item(item, output_dir, "failed", message)

    parent_connection.close()
    process.close()

    if result.get("status") == "failed":
        click.echo(f"{required_text(item, 'key')}: {result.get('error')}", err=True)

    return result


def _run_item_process(
    connection: Connection,
    item: JsonObject,
    label: JsonObject | None,
    output_dir: Path,
    model: str,
    verbose: bool,
) -> None:
    try:
        os.setsid()
        result = run_item(item, label, output_dir, model, verbose)
    except Exception as error:
        result = {
            "key": item.get("key"),
            "status": "failed",
            "error": str(error),
        }

    try:
        connection.send(result)
    finally:
        connection.close()


def _terminate_process_group(process: BaseProcess) -> None:
    if process.pid is None:
        return

    try:
        process_group = os.getpgid(process.pid)
    except ProcessLookupError:
        process.join()
        process.close()
        return

    try:
        if process_group == process.pid:
            os.killpg(process_group, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        process.join()
        process.close()
        return

    process.join(2)

    if process.is_alive():
        if process_group == process.pid:
            os.killpg(process_group, signal.SIGKILL)
        else:
            process.kill()

        process.join()

    process.close()


def _finalize_interrupted_item(
    item: JsonObject,
    output_dir: Path,
    status: str,
    error: str,
) -> JsonObject:
    key = required_text(item, "key")
    result_path = output_dir / "items" / key / "result.json"

    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        mr = required_mapping(item, "mr")
        payload = _item_result(
            key,
            "running",
            "fetch",
            _timestamp(),
            {
                name: {"started_at": None, "finished_at": None}
                for name in ("fetch", "reviewer", "judge")
            },
            {
                "base_revision": required_text(mr, "base_sha"),
                "target_revision": required_text(mr, "head_sha"),
                "sha256": None,
            },
            None,
            None,
        )

    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {result_path}")

    payload["status"] = status
    payload["finished_at"] = _timestamp()
    payload["error"] = error
    result_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(result_path, payload)
    return payload


def _write_item_progress(
    path: Path,
    key: str,
    stage: str,
    started_at: str,
    stages: JsonObject,
    diff: JsonObject,
) -> None:
    _write_json(
        path,
        _item_result(
            key,
            "running",
            stage,
            started_at,
            stages,
            diff,
            None,
            None,
        ),
    )


def _item_result(
    key: str,
    status: str,
    stage: str,
    started_at: str,
    stages: JsonObject,
    diff: JsonObject,
    error: str | None,
    finished_at: str | None,
) -> JsonObject:
    return {
        "schema_version": "1.0",
        "item_key": key,
        "status": status,
        "stage": stage,
        "started_at": started_at,
        "finished_at": finished_at,
        "stages": stages,
        "diff": diff,
        "error": error,
    }


def _write_json(path: Path, payload: JsonObject) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


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
    timeout_seconds = item_timeout_seconds(configuration)

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
                    run_item_with_timeout(
                        item,
                        labels.get(key),
                        artifacts.run_dir,
                        model,
                        verbose,
                        timeout_seconds,
                    )
                )
            except (
                OSError,
                RuntimeError,
                ValueError,
                subprocess.SubprocessError,
            ) as error:
                click.echo(f"{key}: {error}", err=True)
                results.append({"key": key, "status": "failed", "error": str(error)})

        failed = [result for result in results if result["status"] != "succeeded"]
        status = "failed" if failed else "completed"
    finally:
        artifacts.finish(status)

    if failed:
        raise click.ClickException(f"Validation failed for {len(failed)} item(s)")


if __name__ == "__main__":
    main()
