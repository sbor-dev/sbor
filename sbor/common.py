from typing import Any

JsonObject = dict[str, Any]


def required_text(payload: JsonObject, field: str) -> str:
    value = payload.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string field {field}")

    return value.strip()
