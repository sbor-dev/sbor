import json
from collections.abc import Collection, Iterable
from pathlib import Path

from validation.dataset.common import ConvertedItem, JsonObject, build_key
from validation.dataset.converters.base_converter import Converter


class CCppBenchmarkConverter(Converter):
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
        return "c_cpp_benchmark"

    def convert(self) -> Iterable[ConvertedItem]:
        for record in self._load_records():
            yield self._convert_record(record)

    def _load_records(self) -> list[JsonObject]:
        source_file = self.source_dir / "benchmark_final16.json"

        with source_file.open(encoding="utf-8") as handle:
            records = json.load(handle)

        if not isinstance(records, list):
            raise ValueError(f"Expected a JSON array in {source_file}")

        if not all(isinstance(record, dict) for record in records):
            raise ValueError(f"Expected JSON objects in {source_file}")

        return records

    def _convert_record(self, record: JsonObject) -> ConvertedItem:
        repo = _required_text(record, "repo")
        mr_url = _required_text(record, "pr_url")
        base_sha = _required_text(record, "base_sha")
        head_sha = _required_text(record, "head_sha")

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
            "repo_url": f"https://github.com/{repo}.git",
            "source": {
                "dataset": self.source_name,
                "dataset_version": self.dataset_version,
            },
            "mr": {
                "url": mr_url,
                "title": _required_text(record, "pr_title"),
                "description": "",
                "base_sha": base_sha,
                "head_sha": head_sha,
            },
        }

        goldens = record.get("goldens")

        if not isinstance(goldens, list):
            raise ValueError(f"Expected goldens for {mr_url}")

        defects: list[JsonObject] = []

        for golden in goldens:
            if not isinstance(golden, dict):
                raise ValueError(f"Expected golden object for {mr_url}")

            if _required_text(golden, "category") not in self.functional_categories:
                continue

            line = _required_line(golden, "line")

            defects.append(
                {
                    "file_path": _required_text(golden, "path"),
                    "start_line": line,
                    "end_line": line,
                    "category": "Functional",
                    "description": _required_text(golden, "comment"),
                }
            )

        label_item: JsonObject = {
            "schema_version": "1.0",
            "key": key,
            "defects": defects,
        }

        return ConvertedItem(key, input_item, label_item)


def _required_text(record: JsonObject, field: str) -> str:
    value = record.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string field {field}")

    return value.strip()


def _required_line(record: JsonObject, field: str) -> int:
    value = record.get(field)

    if not isinstance(value, int) or value < 1:
        raise ValueError(f"Expected positive integer field {field}")

    return value
