from pathlib import Path
from typing import Any

import yaml

JsonObject = dict[str, Any]


def load_yaml_mapping(path: Path) -> JsonObject:
    with path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping in {path}")

    return payload


def required_text(payload: JsonObject, field: str) -> str:
    value = payload.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string field {field}")

    return value.strip()


def required_mapping(payload: JsonObject, field: str) -> JsonObject:
    value = payload.get(field)

    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping field {field}")

    return value
