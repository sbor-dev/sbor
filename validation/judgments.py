import json
from pathlib import Path

from validation.common import JsonObject, required_text

LABEL_VERDICTS = frozenset({"matched", "missed"})
REVIEWER_VERDICTS = frozenset({"supported", "unsupported"})


def _required_list(payload: JsonObject, field: str) -> list[object]:
    value = payload.get(field)

    if not isinstance(value, list):
        raise ValueError(f"Judgment field {field} must be an array")

    return value


def _required_index(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"Judgment field {field} must be a non-negative integer")

    return value


def _required_references(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(
            f"Judgment field {field} must be an array of non-empty strings"
        )

    if len(value) != len(set(value)):
        raise ValueError(f"Judgment field {field} contains duplicate values")

    return value


def validate_judgment(
    payload: object,
    label: JsonObject,
    reviewer_findings: list[JsonObject],
) -> JsonObject:
    if not isinstance(payload, dict):
        raise ValueError("judgment.json must contain a JSON object")

    key = required_text(payload, "key")

    if key != required_text(label, "key"):
        raise ValueError("Judgment key does not match label key")

    required_text(payload, "summary")
    defects = _required_list(label, "defects")
    label_assessments = _required_list(payload, "label_assessments")
    reviewer_assessments = _required_list(payload, "reviewer_assessments")
    reviewer_ids = {required_text(finding, "id") for finding in reviewer_findings}
    assessed_label_indexes: set[int] = set()
    assessed_reviewer_ids: set[str] = set()
    label_references: dict[int, set[str]] = {}
    reviewer_references: dict[str, set[int]] = {}

    for assessment in label_assessments:
        if not isinstance(assessment, dict):
            raise ValueError("Each label assessment must be a JSON object")

        label_index = _required_index(assessment.get("label_index"), "label_index")

        if label_index >= len(defects) or label_index in assessed_label_indexes:
            raise ValueError("Judgment label assessments must cover each label once")

        assessed_label_indexes.add(label_index)
        verdict = required_text(assessment, "verdict")

        if verdict not in LABEL_VERDICTS:
            raise ValueError(f"Invalid label verdict {verdict}")

        finding_ids = _required_references(
            assessment.get("reviewer_finding_ids"),
            "reviewer_finding_ids",
        )

        if not set(finding_ids).issubset(reviewer_ids):
            raise ValueError("Label assessment references an unknown reviewer finding")

        if verdict == "matched" and not finding_ids:
            raise ValueError("Matched label must reference a reviewer finding")

        if verdict == "missed" and finding_ids:
            raise ValueError("Missed label must not reference reviewer findings")

        required_text(assessment, "reason")
        label_references[label_index] = set(finding_ids)

    if assessed_label_indexes != set(range(len(defects))):
        raise ValueError("Judgment label assessments must cover every label")

    for assessment in reviewer_assessments:
        if not isinstance(assessment, dict):
            raise ValueError("Each reviewer assessment must be a JSON object")

        finding_id = required_text(assessment, "id")

        if finding_id not in reviewer_ids or finding_id in assessed_reviewer_ids:
            raise ValueError(
                "Judgment reviewer assessments must cover each finding once"
            )

        assessed_reviewer_ids.add(finding_id)
        verdict = required_text(assessment, "verdict")

        if verdict not in REVIEWER_VERDICTS:
            raise ValueError(f"Invalid reviewer verdict {verdict}")

        label_indexes = assessment.get("label_indexes")

        if not isinstance(label_indexes, list):
            raise ValueError("Judgment field label_indexes must be an array")

        if len(label_indexes) != len(set(label_indexes)) or any(
            _required_index(index, "label_indexes") >= len(defects)
            for index in label_indexes
        ):
            raise ValueError("Judgment reviewer assessment has invalid label indexes")

        if verdict == "unsupported" and label_indexes:
            raise ValueError("Unsupported reviewer finding must not reference labels")

        required_text(assessment, "reason")
        reviewer_references[finding_id] = set(label_indexes)

    if assessed_reviewer_ids != reviewer_ids:
        raise ValueError("Judgment reviewer assessments must cover every finding")

    for label_index, finding_ids in label_references.items():
        symmetric_ids = {
            finding_id
            for finding_id, label_indexes in reviewer_references.items()
            if label_index in label_indexes
        }

        if finding_ids != symmetric_ids:
            raise ValueError("Judgment label and reviewer references must be symmetric")

    return payload


def load_judgment(
    path: Path,
    label: JsonObject,
    reviewer_findings: list[JsonObject],
) -> JsonObject:
    if not path.is_file():
        raise ValueError("Judge did not write judgment.json")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid judgment.json: {error}") from error

    if isinstance(payload, dict) and "key" not in payload:
        payload["key"] = required_text(label, "key")
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return validate_judgment(payload, label, reviewer_findings)
