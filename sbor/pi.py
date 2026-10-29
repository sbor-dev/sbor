import json
import os
from collections.abc import Mapping
from pathlib import Path

from sbor.common import JsonObject, required_text

RUNTIME_CONFIGURATION_FIELDS = {
    "model": "MODEL",
    "base_url": "BASE_URL",
    "api": "API",
    "token": "TOKEN",
}


def load_runtime_configuration(
    role: str,
    environment: Mapping[str, str] | None = None,
) -> JsonObject:
    source = os.environ if environment is None else environment
    prefix = f"SBOR_{role.upper()}_"
    configuration: JsonObject = {}

    for field, suffix in RUNTIME_CONFIGURATION_FIELDS.items():
        variable = f"{prefix}{suffix}"
        value = source.get(variable)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing environment variable {variable}")

        configuration[field] = value

    return configuration


def configure_pi(
    llm_configuration: JsonObject,
    agent_dir: Path,
    provider: str,
) -> str:
    agent_dir = Path(agent_dir)
    agent_dir.mkdir(parents=True, exist_ok=True)
    model = required_text(llm_configuration, "model")
    payload = {
        "providers": {
            provider: {
                "baseUrl": required_text(llm_configuration, "base_url"),
                "api": required_text(llm_configuration, "api"),
                "apiKey": required_text(llm_configuration, "token"),
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                },
                "models": [{"id": model, "reasoning": False}],
            }
        }
    }
    models_path = agent_dir / "models.json"
    models_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    models_path.chmod(0o600)

    return model
