import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from validation.common import (
    JsonObject,
    load_yaml_mapping,
    required_mapping,
    required_text,
)


@dataclass
class RunArtifacts:
    run_id: str
    run_dir: Path
    started_at: str
    code_revision: str
    code_dirty: bool
    dataset: JsonObject

    def write_manifest(self, status: str, finished_at: str | None = None) -> None:
        payload = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "status": status,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "code": {
                "revision": self.code_revision,
                "dirty": self.code_dirty,
            },
            "dataset": self.dataset,
        }
        (self.run_dir / "run.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def finish(self, status: str) -> None:
        self.write_manifest(status, _timestamp())


def load_experiment_metadata(path: Path) -> JsonObject:
    metadata = load_yaml_mapping(path)

    if metadata.get("schema_version") != "1.0":
        raise ValueError("Expected metadata schema_version 1.0")

    experiment = required_mapping(metadata, "experiment")
    required_text(experiment, "name")
    required_text(experiment, "run_name")
    tags = experiment.get("tags")

    if not isinstance(tags, dict):
        raise ValueError("Expected mapping field experiment.tags")

    if not all(isinstance(key, str) and key.strip() for key in tags):
        raise ValueError("Expected non-empty string keys in experiment.tags")

    if not all(_is_scalar(value) for value in tags.values()):
        raise ValueError("Expected scalar values in experiment.tags")

    dataset = required_mapping(metadata, "dataset")

    for field in ("repository", "revision", "version"):
        required_text(dataset, field)

    _optional_text(dataset, "sha256")
    _validate_model_metadata(required_mapping(metadata, "reviewer"), "reviewer")
    _validate_model_metadata(required_mapping(metadata, "judge"), "judge")

    return metadata


def create_run_artifacts(
    output_dir: Path,
    metadata_path: Path,
    validation_config: Path,
    metadata: JsonObject,
    code_revision: str,
    code_dirty: bool,
    item_count: int,
) -> RunArtifacts:
    experiment = required_mapping(metadata, "experiment")
    run_name = required_text(experiment, "run_name")
    started_at = _timestamp()
    run_id = f"{_run_timestamp(started_at)}-{_slug(run_name)}"
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True)
    shutil.copy2(metadata_path, run_dir / "metadata.yaml")
    shutil.copy2(validation_config, run_dir / "validation.yaml")
    dataset = dict(required_mapping(metadata, "dataset"))
    dataset["items"] = item_count
    artifacts = RunArtifacts(
        run_id=run_id,
        run_dir=run_dir,
        started_at=started_at,
        code_revision=code_revision,
        code_dirty=code_dirty,
        dataset=dataset,
    )
    artifacts.write_manifest("running")
    return artifacts


def validate_runtime_models(metadata: JsonObject, model: str) -> None:
    reviewer = required_mapping(metadata, "reviewer")
    judge = required_mapping(metadata, "judge")

    for role, configuration in (("reviewer", reviewer), ("judge", judge)):
        declared_model = required_text(configuration, "model")

        if declared_model != model:
            raise ValueError(
                f"Declared {role} model {declared_model!r} does not match "
                f"runtime model {model!r}"
            )


def validate_dataset_version(metadata: JsonObject, dataset_metadata_path: Path) -> None:
    try:
        dataset_metadata = json.loads(dataset_metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {dataset_metadata_path}: {error}") from error

    if not isinstance(dataset_metadata, dict):
        raise ValueError(f"Expected JSON object in {dataset_metadata_path}")

    declared = required_text(required_mapping(metadata, "dataset"), "version")
    actual = required_text(dataset_metadata, "dataset_version")

    if declared != actual:
        raise ValueError(
            f"Declared dataset version {declared!r} does not match "
            f"dataset metadata version {actual!r}"
        )


def _validate_model_metadata(configuration: JsonObject, role: str) -> None:
    required_text(configuration, "provider")
    required_text(configuration, "model")

    for field in (
        "revision",
        "weight_quantization",
        "kv_cache_quantization",
        "inference_command",
    ):
        _optional_text(configuration, field, prefix=role)

    for field in ("context_tokens", "max_output_tokens"):
        _optional_positive_integer(configuration, field, prefix=role)

    temperature = _required_optional_value(configuration, "temperature", role)

    if temperature is not None and (
        isinstance(temperature, bool) or not isinstance(temperature, int | float)
    ):
        raise ValueError(f"Expected number or null field {role}.temperature")

    seed = _required_optional_value(configuration, "seed", role)

    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError(f"Expected integer or null field {role}.seed")


def _required_optional_value(
    configuration: JsonObject,
    field: str,
    prefix: str,
) -> Any:
    if field not in configuration:
        raise ValueError(f"Missing field {prefix}.{field}; use null if unknown")

    return configuration[field]


def _optional_text(
    configuration: JsonObject,
    field: str,
    prefix: str | None = None,
) -> None:
    value = _required_optional_value(configuration, field, prefix or "dataset")

    if value is not None and (not isinstance(value, str) or not value.strip()):
        qualified_field = f"{prefix}.{field}" if prefix else f"dataset.{field}"
        raise ValueError(f"Expected non-empty string or null field {qualified_field}")


def _optional_positive_integer(
    configuration: JsonObject,
    field: str,
    prefix: str,
) -> None:
    value = _required_optional_value(configuration, field, prefix)

    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value < 1
    ):
        raise ValueError(f"Expected positive integer or null field {prefix}.{field}")


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _slug(value: str) -> str:
    slug = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-.")

    if not slug:
        raise ValueError("experiment.run_name must contain a path-safe character")

    return slug


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_timestamp(timestamp: str) -> str:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return parsed.strftime("%Y%m%dT%H%M%SZ")
