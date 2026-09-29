import json
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

import click
import yaml

SUBSET_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def generate_subsets(
    dataset_dir: Path,
    config_path: Path,
    output_dir: Path,
    verbose: bool = False,
) -> None:
    dataset_dir = Path(dataset_dir)
    output_dir = Path(output_dir)

    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")

    metadata_path = dataset_dir / "metadata.json"

    if not metadata_path.is_file():
        raise FileNotFoundError(f"Dataset metadata does not exist: {metadata_path}")

    input_records = _load_jsonl(dataset_dir / "input.jsonl")
    label_records = _load_jsonl(dataset_dir / "labels.jsonl")

    if input_records.keys() != label_records.keys():
        raise ValueError("Dataset input and label keys do not match")

    if verbose:
        click.echo(
            f"Loaded {len(input_records)} items from {dataset_dir}",
            err=True,
        )

    subsets = load_subset_config(config_path)

    for subset_name, keys in subsets.items():
        missing = set(keys).difference(input_records)

        if missing:
            missing_keys = ", ".join(sorted(missing))
            raise ValueError(
                f"Subset {subset_name} contains unknown keys: {missing_keys}"
            )

    output_dir.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(
        prefix=f".{output_dir.name}-",
        dir=output_dir.parent,
    ) as temporary:
        staging_dir = Path(temporary) / output_dir.name
        staging_dir.mkdir()

        for subset_name, keys in subsets.items():
            if verbose:
                click.echo(
                    f"Writing subset {subset_name} with {len(keys)} items",
                    err=True,
                )

            subset_dir = staging_dir / subset_name
            subset_dir.mkdir()
            shutil.copy2(metadata_path, subset_dir / "metadata.json")
            selected_keys = set(keys)
            _write_jsonl(
                subset_dir / "input.jsonl",
                input_records,
                selected_keys,
            )
            _write_jsonl(
                subset_dir / "labels.jsonl",
                label_records,
                selected_keys,
            )

        staging_dir.replace(output_dir)

    if verbose:
        click.echo(
            f"Generated {len(subsets)} subsets in {output_dir}",
            err=True,
        )


def load_subset_config(path: Path) -> dict[str, tuple[str, ...]]:
    with Path(path).open(encoding="utf-8") as handle:
        configuration = yaml.safe_load(handle)

    if not isinstance(configuration, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")

    subsets = configuration.get("subsets")

    if not isinstance(subsets, dict) or not subsets:
        raise ValueError("Expected a non-empty subsets mapping")

    result: dict[str, tuple[str, ...]] = {}

    for name, value in subsets.items():
        if not isinstance(name, str) or not SUBSET_NAME.fullmatch(name):
            raise ValueError(f"Invalid subset name: {name}")

        if not isinstance(value, dict):
            raise ValueError(f"Expected mapping for subset {name}")

        keys = value.get("items")

        if (
            not isinstance(keys, list)
            or not keys
            or not all(isinstance(key, str) and key.strip() for key in keys)
        ):
            raise ValueError(f"Expected non-empty item key list for subset {name}")

        normalized_keys = tuple(key.strip() for key in keys)

        if len(normalized_keys) != len(set(normalized_keys)):
            raise ValueError(f"Subset {name} contains duplicate item keys")

        result[name] = normalized_keys

    return result


def _load_jsonl(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                message = f"Invalid JSON at {path}:{line_number}: {error}"

                raise ValueError(message) from error

            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}")

            key = payload.get("key")

            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"Expected non-empty key at {path}:{line_number}")

            if key in records:
                raise ValueError(f"Duplicate key {key} in {path}")

            records[key] = line.rstrip("\r\n")

    return records


def _write_jsonl(
    path: Path,
    records: dict[str, str],
    selected_keys: set[str],
) -> None:
    selected_records: Iterable[str] = (
        line for key, line in records.items() if key in selected_keys
    )

    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for line in selected_records:
            handle.write(line)
            handle.write("\n")


@click.command()
@click.option(
    "--dataset-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("config/validation_dataset_subsets.yaml"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
)
@click.option("--verbose", is_flag=True)
def main(
    dataset_dir: Path,
    config_path: Path,
    output_dir: Path,
    verbose: bool,
) -> None:
    generate_subsets(dataset_dir, config_path, output_dir, verbose)


if __name__ == "__main__":
    raise SystemExit(main())
