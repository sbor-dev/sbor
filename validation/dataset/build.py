import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import click
import yaml

from validation.dataset.common import ConvertedItem, DatasetMetadata, JsonObject
from validation.dataset.converters.c_cpp_benchmark import CCppBenchmarkConverter


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
    configuration = load_config(config_path)
    dataset_configuration = _required_mapping(configuration, "dataset")
    sources_configuration = _required_mapping(configuration, "sources")
    c_cpp_configuration = _required_mapping(sources_configuration, "c_cpp_benchmark")
    source_dir = resolve_source_dir(config_path, c_cpp_configuration)
    source_version = git_revision(source_dir)
    resolved_generator_revision = generator_revision or git_revision(Path.cwd())
    converter = CCppBenchmarkConverter(
        source_dir,
        source_version,
        _required_text_list(c_cpp_configuration, "functional_categories"),
    )
    metadata = DatasetMetadata(
        dataset_name=_required_text(dataset_configuration, "name"),
        dataset_version=_required_text(dataset_configuration, "version"),
        generator_revision=resolved_generator_revision,
    )

    DatasetBuilder(converter.convert(), metadata).write(output_dir)


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
        ["git", "-C", str(directory), "rev-parse", "HEAD"],
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
    value: Any = configuration.get(field)

    if not isinstance(value, list) or not value:
        raise ValueError(f"Expected non-empty list field {field}")

    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"Expected non-empty string values in {field}")

    return [item.strip() for item in value]


if __name__ == "__main__":
    raise SystemExit(main())
