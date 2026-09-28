import json
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import click
import yaml

from validation.dataset.common import ConvertedItem, DatasetMetadata, JsonObject
from validation.dataset.converters.factory import create_converter
from validation.dataset.repository_validation import (
    RepositoryValidationError,
    validate_repository,
)


class DatasetBuilder:
    def __init__(
        self,
        items: Iterable[ConvertedItem],
        metadata: DatasetMetadata,
    ) -> None:
        self.items = tuple(sorted(items, key=lambda item: item.key))
        self.metadata = metadata
        keys = [item.key for item in self.items]

        if len(keys) != len(set(keys)):
            raise ValueError("Dataset contains duplicate keys")

    def write(self, output_dir: Path) -> None:
        output_dir = Path(output_dir)

        if output_dir.exists():
            raise FileExistsError(f"Output directory already exists: {output_dir}")

        output_dir.mkdir(parents=True)
        self._write_metadata(output_dir)
        self._write_input(output_dir)
        self._write_labels(output_dir)

    def _write_metadata(self, output_dir: Path) -> None:
        payload = {
            "schema_version": "1.0",
            "dataset_name": self.metadata.dataset_name,
            "dataset_version": self.metadata.dataset_version,
            "generator_revision": self.metadata.generator_revision,
        }
        (output_dir / "metadata.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_input(self, output_dir: Path) -> None:
        self._write_jsonl(
            output_dir / "input.jsonl", (item.input_item for item in self.items)
        )

    def _write_labels(self, output_dir: Path) -> None:
        self._write_jsonl(
            output_dir / "labels.jsonl", (item.label_item for item in self.items)
        )

    def _write_jsonl(self, path: Path, records: Iterable[dict[str, object]]) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                handle.write("\n")


def build_dataset(
    config_path: Path,
    output_dir: Path,
    generator_revision: str | None,
) -> None:
    started_at = _timestamp()
    configuration = load_config(config_path)
    dataset_configuration = _required_mapping(configuration, "dataset")
    sources_configuration = _required_mapping(configuration, "sources")
    converter_names = _required_text_list(configuration, "converters")
    resolved_generator_revision = generator_revision or git_revision(Path.cwd())
    converted_items: list[ConvertedItem] = []

    for converter_name in converter_names:
        source_configuration = _required_mapping(
            sources_configuration, converter_name
        )
        source_dir = resolve_source_dir(config_path, source_configuration)
        converter = create_converter(
            converter_name,
            source_dir,
            git_revision(source_dir),
            source_configuration,
        )
        converted_items.extend(converter.convert())

    items, skipped, source_counts = validate_items(
        converted_items,
        converter_names,
    )

    metadata = DatasetMetadata(
        dataset_name=_required_text(dataset_configuration, "name"),
        dataset_version=_required_text(dataset_configuration, "version"),
        generator_revision=resolved_generator_revision,
    )

    DatasetBuilder(items, metadata).write(output_dir)
    write_build_report(
        output_dir / "build-report.json",
        metadata.dataset_version,
        started_at,
        items,
        skipped,
        source_counts,
    )


def validate_items(
    items: Iterable[ConvertedItem],
    source_names: Iterable[str],
) -> tuple[list[ConvertedItem], list[JsonObject], dict[str, JsonObject]]:
    valid_items: list[ConvertedItem] = []
    skipped: list[JsonObject] = []
    source_counts: dict[str, JsonObject] = {
        source_name: {"written": 0, "skipped": 0}
        for source_name in source_names
    }

    with TemporaryDirectory(prefix="sbor-dataset-validation-") as temporary:
        validation_dir = Path(temporary)

        for item in items:
            source_name = _item_source(item)
            counts = source_counts.setdefault(
                source_name,
                {"written": 0, "skipped": 0},
            )

            try:
                validate_repository(item.input_item, validation_dir / item.key)
            except RepositoryValidationError as error:
                source_id = _item_source_id(item)
                click.echo(
                    f"Skipping {source_name}:{source_id}: "
                    f"{error.reason}: {error.detail}",
                    err=True,
                )
                counts["skipped"] += 1
                skipped.append(
                    {
                        "source": source_name,
                        "source_id": source_id,
                        "reason": error.reason,
                        "detail": error.detail,
                    }
                )
                continue

            counts["written"] += 1
            valid_items.append(item)

    return valid_items, skipped, source_counts


def write_build_report(
    path: Path,
    dataset_version: str,
    started_at: str,
    items: list[ConvertedItem],
    skipped: list[JsonObject],
    source_counts: dict[str, JsonObject],
) -> None:
    payload = {
        "schema_version": "1.0",
        "dataset_version": dataset_version,
        "started_at": started_at,
        "finished_at": _timestamp(),
        "items_written": len(items),
        "items_skipped": len(skipped),
        "sources": source_counts,
        "skipped": skipped,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _item_source(item: ConvertedItem) -> str:
    source = _required_mapping(item.input_item, "source")
    return _required_text(source, "dataset")


def _item_source_id(item: ConvertedItem) -> str:
    mr = _required_mapping(item.input_item, "mr")
    return _required_text(mr, "url")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("config/validation_dataset_builder.yaml"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
)
@click.option("--generator-revision")
def main(
    config_path: Path,
    output_dir: Path,
    generator_revision: str | None,
) -> None:
    build_dataset(config_path, output_dir, generator_revision)


def git_revision(directory: Path) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={directory.resolve()}",
            "-C",
            str(directory),
            "rev-parse",
            "HEAD",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def load_config(path: Path) -> JsonObject:
    with Path(path).open(encoding="utf-8") as handle:
        configuration = yaml.safe_load(handle)

    if not isinstance(configuration, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")

    return configuration


def resolve_source_dir(config_path: Path, source_configuration: JsonObject) -> Path:
    source_dir = Path(_required_text(source_configuration, "source_dir"))

    if source_dir.is_absolute():
        return source_dir

    return Path(config_path).resolve().parent.parent / source_dir


def _required_mapping(configuration: JsonObject, field: str) -> JsonObject:
    value = configuration.get(field)

    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping field {field}")

    return value


def _required_text(configuration: JsonObject, field: str) -> str:
    value = configuration.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string field {field}")

    return value.strip()


def _required_text_list(configuration: JsonObject, field: str) -> list[str]:
    value = configuration.get(field)

    if not isinstance(value, list) or not value:
        raise ValueError(f"Expected non-empty list field {field}")

    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"Expected non-empty string values in {field}")

    return [item.strip() for item in value]


if __name__ == "__main__":
    raise SystemExit(main())
