import json
import re
from collections.abc import Collection, Iterable
from pathlib import Path

from validation.dataset.common import ConvertedItem, JsonObject, build_key
from validation.dataset.converters.base_converter import Converter

GITHUB_PR_URL = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)/?$",
    re.IGNORECASE,
)


class AacrBenchConverter(Converter):
    def __init__(
        self,
        source_dir: Path,
        dataset_version: str,
        functional_categories: Collection[str],
    ) -> None:
        self.source_dir = Path(source_dir)
        self.dataset_version = dataset_version
        self.functional_categories = frozenset(functional_categories)

    @property
    def source_name(self) -> str:
        return "aacr_bench"

    def convert(self) -> Iterable[ConvertedItem]:
        for record in self._load_records():
            yield self._convert_record(record)

    def _load_records(self) -> list[JsonObject]:
        source_file = self.source_dir / "dataset/positive_samples.json"

        with source_file.open(encoding="utf-8") as handle:
            records = json.load(handle)

        if not isinstance(records, list):
            raise ValueError(f"Expected a JSON array in {source_file}")

        if not all(isinstance(record, dict) for record in records):
            raise ValueError(f"Expected JSON objects in {source_file}")

        return records

    def _convert_record(self, record: JsonObject) -> ConvertedItem:
        mr_url = _required_text(record, "githubPrUrl")
        match = GITHUB_PR_URL.fullmatch(mr_url)

        if match is None:
            raise ValueError(f"Expected GitHub pull request URL: {mr_url}")

        repository = f"{match.group('owner')}/{match.group('repo')}"
        base_sha = _required_text(record, "source_commit")
        head_sha = _required_text(record, "target_commit")
        key = build_key(
            self.source_name,
            self.dataset_version,
            mr_url,
            base_sha,
            head_sha,
        )
        input_item: JsonObject = {
            "schema_version": "1.0",
            "key": key,
            "repo_url": f"https://github.com/{repository}.git",
            "source": {
                "dataset": self.source_name,
                "dataset_version": self.dataset_version,
            },
            "mr": {
                "url": mr_url,
                "title": f"Pull request #{match.group('number')}",
                "description": "",
                "base_sha": base_sha,
                "head_sha": head_sha,
            },
        }
        label_item: JsonObject = {
            "schema_version": "1.0",
            "key": key,
            "defects": self._convert_defects(record, mr_url),
        }

        return ConvertedItem(key, input_item, label_item)

    def _convert_defects(
        self,
        record: JsonObject,
        mr_url: str,
    ) -> list[JsonObject]:
        comments = record.get("comments")

        if not isinstance(comments, list):
            raise ValueError(f"Expected comments for {mr_url}")

        defects: list[JsonObject] = []

        for comment in comments:
            if not isinstance(comment, dict):
                raise ValueError(f"Expected comment object for {mr_url}")

            if comment.get("side") != "right":
                continue

            category = comment.get("category")

            if (
                not isinstance(category, str)
                or category not in self.functional_categories
            ):
                continue

            start_line = comment.get("from_line")
            end_line = comment.get("to_line")

            if not _valid_line_range(start_line, end_line):
                continue

            defects.append(
                {
                    "file_path": _required_text(comment, "path"),
                    "start_line": start_line,
                    "end_line": end_line,
                    "category": "Functional",
                    "description": _required_text(comment, "note"),
                }
            )

        return defects


def _required_text(record: JsonObject, field: str) -> str:
    value = record.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string field {field}")

    return value.strip()


def _valid_line_range(start_line: object, end_line: object) -> bool:
    return (
        isinstance(start_line, int)
        and not isinstance(start_line, bool)
        and isinstance(end_line, int)
        and not isinstance(end_line, bool)
        and 1 <= start_line <= end_line
    )
