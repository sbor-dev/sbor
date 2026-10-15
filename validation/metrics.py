import json
import math
from datetime import datetime
from pathlib import Path
from statistics import fmean, median

from validation.common import JsonObject, required_text


def write_metrics(
    run_dir: Path,
    labels: dict[str, JsonObject],
    results: list[JsonObject],
) -> JsonObject:
    metrics = collect_metrics(run_dir, labels, results)
    path = run_dir / "metrics.json"
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
    return metrics


def collect_metrics(
    run_dir: Path,
    labels: dict[str, JsonObject],
    results: list[JsonObject],
) -> JsonObject:
    statuses = {"succeeded": 0, "failed": 0, "timed_out": 0}
    quality = {
        "findings_supported": 0,
        "findings_unsupported": 0,
        "labels_matched": 0,
        "labels_missed": 0,
        "clean_items": 0,
        "clean_items_with_unsupported_findings": 0,
    }
    timing_values: dict[str, list[float]] = {
        name: [] for name in ("item", "fetch", "reviewer", "judge")
    }
    total_output_tokens = 0
    total_inference_seconds = 0.0

    for returned_result in results:
        status = required_text(returned_result, "status")

        if status not in statuses:
            raise ValueError(f"Unknown item status {status}")

        statuses[status] += 1
        key_value = returned_result.get("item_key", returned_result.get("key"))

        if not isinstance(key_value, str) or not key_value:
            raise ValueError("Item result is missing its key")

        if status != "succeeded":
            continue

        result = _load_json_object(run_dir / "items" / key_value / "result.json")
        _append_duration(timing_values["item"], result)
        stages = result.get("stages")

        if not isinstance(stages, dict):
            raise ValueError(f"Expected stages object for item {key_value}")

        for stage in ("fetch", "reviewer", "judge"):
            interval = stages.get(stage)

            if not isinstance(interval, dict):
                raise ValueError(f"Expected {stage} stage for item {key_value}")

            _append_duration(timing_values[stage], interval)

        judgment = _load_json_object(run_dir / "items" / key_value / "judgment.json")
        reviewer_assessments = _required_object_list(
            judgment,
            "reviewer_assessments",
        )
        label_assessments = _required_object_list(judgment, "label_assessments")

        for assessment in reviewer_assessments:
            verdict = required_text(assessment, "verdict")
            field = {
                "supported": "findings_supported",
                "unsupported": "findings_unsupported",
            }.get(verdict)

            if field is None:
                raise ValueError(f"Unknown reviewer verdict {verdict}")

            quality[field] += 1

        for assessment in label_assessments:
            verdict = required_text(assessment, "verdict")
            field = {"matched": "labels_matched", "missed": "labels_missed"}.get(
                verdict
            )

            if field is None:
                raise ValueError(f"Unknown label verdict {verdict}")

            quality[field] += 1

        label = labels.get(key_value)

        if label is None:
            raise ValueError(f"Missing label for metrics item {key_value}")

        defects = label.get("defects")

        if not isinstance(defects, list):
            raise ValueError(f"Expected defects array for metrics item {key_value}")

        if not defects:
            quality["clean_items"] += 1

            if any(
                assessment.get("verdict") == "unsupported"
                for assessment in reviewer_assessments
            ):
                quality["clean_items_with_unsupported_findings"] += 1

        inference = returned_result.get("_reviewer_inference")

        if isinstance(inference, dict):
            output_tokens = inference.get("output_tokens")
            duration_seconds = inference.get("duration_seconds")

            if (
                isinstance(output_tokens, int)
                and not isinstance(output_tokens, bool)
                and output_tokens >= 0
                and isinstance(duration_seconds, int | float)
                and not isinstance(duration_seconds, bool)
                and math.isfinite(duration_seconds)
                and duration_seconds > 0
            ):
                total_output_tokens += output_tokens
                total_inference_seconds += float(duration_seconds)

    avg_tokens_per_second = (
        total_output_tokens / total_inference_seconds
        if total_output_tokens > 0 and total_inference_seconds > 0
        else None
    )

    return {
        "schema_version": "1.0",
        "execution": {
            "items_succeeded": statuses["succeeded"],
            "items_failed": statuses["failed"],
            "items_timed_out": statuses["timed_out"],
        },
        "quality": quality,
        "timing_seconds": {
            name: _distribution(values) for name, values in timing_values.items()
        },
        "inference": {
            "avg_tokens_per_second": _rounded(avg_tokens_per_second),
        },
    }


def _load_json_object(path: Path) -> JsonObject:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error

    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")

    return payload


def _required_object_list(payload: JsonObject, field: str) -> list[JsonObject]:
    value = payload.get(field)

    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Expected object array field {field}")

    return value


def _append_duration(values: list[float], interval: JsonObject) -> None:
    started_at = interval.get("started_at")
    finished_at = interval.get("finished_at")

    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return

    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    duration = (finished - started).total_seconds()

    if duration < 0:
        raise ValueError("Finished timestamp precedes started timestamp")

    values.append(duration)


def _distribution(values: list[float]) -> JsonObject:
    if not values:
        return {"avg": None, "median": None, "p95": None, "p99": None}

    ordered = sorted(values)
    return {
        "avg": _rounded(fmean(ordered)),
        "median": _rounded(median(ordered)),
        "p95": _rounded(_percentile(ordered, 0.95)),
        "p99": _rounded(_percentile(ordered, 0.99)),
    }


def _percentile(ordered: list[float], fraction: float) -> float:
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return ordered[lower]

    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None
