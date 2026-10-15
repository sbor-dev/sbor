import json
import re
from pathlib import Path, PurePosixPath

from validation.common import JsonObject, required_text

ALLOWED_CATEGORIES = frozenset({"Functional", "Evolvability"})
ALLOWED_SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"})
REQUIRED_FIELDS = frozenset(
    {
        "id",
        "severity",
        "category",
        "description",
        "file",
        "start_line",
        "end_line",
    }
)
ISSUE_HEADING = re.compile(r"^## Issue `([^`]+)`\s*$", re.MULTILINE)


def _validate_file_path(file_path: str, repository_dir: Path, finding_id: str) -> Path:
    raw_parts = file_path.split("/")
    path = PurePosixPath(file_path)

    if (
        path.is_absolute()
        or "\\" in file_path
        or any(part in {"", ".", ".."} for part in raw_parts)
        or path.as_posix() != file_path
    ):
        raise ValueError(f"Invalid report file path {file_path}")

    repository_root = repository_dir.resolve()
    candidate = (repository_root / Path(*path.parts)).resolve()

    try:
        candidate.relative_to(repository_root)
    except ValueError as error:
        raise ValueError(f"Invalid report file path {file_path}") from error

    if not candidate.is_file():
        raise ValueError(f"Report file does not exist for id {finding_id}: {file_path}")

    return candidate


def validate_report(payload: object, repository_dir: Path) -> list[JsonObject]:
    if not isinstance(payload, list):
        raise ValueError("report.json must contain a JSON array")

    findings: list[JsonObject] = []
    ids: set[str] = set()

    for finding in payload:
        if not isinstance(finding, dict):
            raise ValueError("Each report finding must be a JSON object")

        missing = REQUIRED_FIELDS.difference(finding)

        if missing:
            fields = ", ".join(sorted(missing))
            raise ValueError(f"Report finding is missing fields: {fields}")

        finding_id = required_text(finding, "id")

        if finding_id in ids:
            raise ValueError(f"Duplicate report id {finding_id}")

        ids.add(finding_id)
        severity = required_text(finding, "severity")
        category = required_text(finding, "category")
        required_text(finding, "description")
        file_path = required_text(finding, "file")

        if severity not in ALLOWED_SEVERITIES:
            raise ValueError(f"Invalid severity {severity}")

        if category not in ALLOWED_CATEGORIES:
            raise ValueError(f"Invalid category {category}")

        source_path = _validate_file_path(file_path, repository_dir, finding_id)
        start_line = finding.get("start_line")
        end_line = finding.get("end_line")

        if (
            not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or start_line < 1
        ):
            raise ValueError(f"Invalid start_line for report id {finding_id}")

        if (
            not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or end_line < start_line
        ):
            raise ValueError(f"Invalid end_line for report id {finding_id}")

        with source_path.open(encoding="utf-8", errors="replace") as handle:
            line_count = sum(1 for _ in handle)

        if end_line > line_count:
            raise ValueError(
                f"Line range for report id {finding_id} exceeds {file_path} "
                f"({line_count} lines)"
            )

        findings.append(finding)

    return findings


def validate_report_markdown(path: Path, findings: list[JsonObject]) -> None:
    content = path.read_text(encoding="utf-8")

    if "# Code review report" not in content or "Found issues:" not in content:
        raise ValueError("report.md is not a meaningful code review report")

    markdown_ids = ISSUE_HEADING.findall(content)

    if len(markdown_ids) != len(set(markdown_ids)):
        raise ValueError("report.md contains duplicate issue ids")

    json_ids = {required_text(finding, "id") for finding in findings}

    if set(markdown_ids) != json_ids:
        raise ValueError("report.json and report.md issue ids do not match")


def load_reports(report_dir: Path, repository_dir: Path) -> list[JsonObject]:
    report_json = report_dir / "report.json"
    report_markdown = report_dir / "report.md"

    if not report_json.is_file() or not report_markdown.is_file():
        raise ValueError("Reviewer did not write both report.json and report.md")

    try:
        payload = json.loads(report_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid report.json: {error}") from error

    findings = validate_report(payload, repository_dir)
    validate_report_markdown(report_markdown, findings)

    return findings
