from pathlib import Path
from typing import Any

from validation.dataset.common import JsonObject
from validation.dataset.converters.base_converter import Converter
from validation.dataset.converters.c_cpp_benchmark import CCppBenchmarkConverter


def create_converter(
    name: str,
    source_dir: Path,
    source_version: str,
    configuration: JsonObject,
) -> Converter:
    if name == "c_cpp_benchmark":
        return CCppBenchmarkConverter(
            source_dir,
            source_version,
            _required_text_list(configuration, "functional_categories"),
        )

    raise ValueError(f"Unknown dataset converter: {name}")


def _required_text_list(configuration: JsonObject, field: str) -> list[str]:
    value: Any = configuration.get(field)

    if not isinstance(value, list) or not value:
        raise ValueError(f"Expected non-empty list field {field}")

    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"Expected non-empty string values in {field}")

    return [item.strip() for item in value]
