from dataclasses import dataclass
from hashlib import sha256
from typing import Any

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ConvertedItem:
    key: str
    input_item: JsonObject
    label_item: JsonObject


@dataclass(frozen=True)
class DatasetMetadata:
    dataset_name: str
    dataset_version: str
    generator_revision: str


def build_key(
    dataset: str,
    dataset_version: str,
    mr_url: str,
    base_sha: str,
    head_sha: str,
) -> str:
    value = "\0".join((dataset, dataset_version, mr_url, base_sha, head_sha))

    return sha256(value.encode("utf-8")).hexdigest()
