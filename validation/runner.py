import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import click

from validation.common import (
    JsonObject,
    load_yaml_mapping,
    required_mapping,
    required_text,
)
from validation.downloader import PreparedReview, prepare_review
from validation.judge import configure_judge_pi, run_judge
from validation.judgments import load_judgment
from validation.reports import load_reports
from validation.reviewer import configure_pi, load_llm_configuration, run_reviewer


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


def _diff_status(item: JsonObject, prepared: PreparedReview) -> JsonObject:
    result: JsonObject = {"diff_sha256": prepared.diff_sha256}
    expected = item.get("diff_sha256")

    if isinstance(expected, str) and expected:
        result["expected_diff_sha256"] = expected
        result["diff_sha256_match"] = expected == prepared.diff_sha256

    return result


def run_item(
    item: JsonObject,
    label: JsonObject,
    output_dir: Path,
    model: str,
    verbose: bool,
) -> JsonObject:
    key = required_text(item, "key")
    mr = required_mapping(item, "mr")
    title = required_text(mr, "title")
    description = mr.get("description")

    if not isinstance(description, str):
        raise ValueError("Expected string field mr.description")

    result_dir = output_dir / "reports" / key
    result_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"sbor-{key[:12]}-") as temporary:
        work_dir = Path(temporary)
        user_stat = Path("/home/sbor").stat()
        os.chown(work_dir, user_stat.st_uid, user_stat.st_gid)
        work_dir.chmod(0o755)
        if verbose:
            click.echo(f"{key}: preparing repository", err=True)
        prepared = prepare_review(item, work_dir)
        report_dir = work_dir / "report"
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
        if verbose:
            click.echo(f"{key}: validating report", err=True)
        findings = load_reports(report_dir, prepared.repository_dir)
        shutil.copy2(report_dir / "report.json", result_dir / "report.json")
        shutil.copy2(report_dir / "report.md", result_dir / "report.md")
        judgment_dir = work_dir / "judgment"
        judgment_path = judgment_dir / "judgment.json"
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
        if verbose:
            click.echo(f"{key}: validating judgment", err=True)
        judgment = load_judgment(judgment_path, label, findings)
        if verbose:
            click.echo(
                f"{key}: judgment validated with "
                f"{len(judgment['label_assessments'])} label assessments and "
                f"{len(judgment['reviewer_assessments'])} reviewer assessments",
                err=True,
            )
        judgment_output_path = output_dir / "judgments" / key / "judgment.json"
        judgment_output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(judgment_path, judgment_output_path)
        result = {
            "key": key,
            "status": "ok",
            "findings": len(findings),
            "judgment": "ok",
            **_diff_status(item, prepared),
        }

    return result


def write_results(path: Path, results: list[JsonObject]) -> None:
    path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@click.command()
@click.option(
    "--validation-config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
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
    llm_config: Path | None,
    llm_config_stdin: bool,
    dataset_dir: Path,
    labels_path: Path,
    output_dir: Path,
) -> None:
    configuration = load_yaml_mapping(validation_config)
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

    items = select_items(load_input_items(dataset_dir / "input.jsonl"), limit)
    labels = load_labels(labels_path)
    verbose = os.environ.get("SBOR_VALIDATION_VERBOSE") == "true"
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[JsonObject] = []

    for item in items:
        key = required_text(item, "key")

        try:
            results.append(run_item(item, labels[key], output_dir, model, verbose))
        except KeyError:
            message = f"Missing label for {key}"
            click.echo(f"{key}: {message}", err=True)
            results.append({"key": key, "status": "error", "error": message})
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            click.echo(f"{key}: {error}", err=True)
            results.append({"key": key, "status": "error", "error": str(error)})

    write_results(output_dir / "reviewer-results.json", results)
    failed = [result for result in results if result["status"] == "error"]

    if failed:
        raise click.ClickException(f"Validation failed for {len(failed)} item(s)")


if __name__ == "__main__":
    main()
