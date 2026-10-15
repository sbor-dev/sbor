# Validation dataset

## Canonical schema

### Directory schema

```
sbor-dataset/
├─ metadata.json
├─ input.jsonl
└─ labels.jsonl
```

- `input.jsonl` contains one MR review input per line. It is the only dataset file available to the code review agent
- `labels.jsonl` contains the ground truth defects. It is available only to the judge
- Corresponding records in `input.jsonl` and `labels.jsonl` have the same deterministic key

### Metadata schema

Contains metadata for the whole dataset release.

```json
{
    "schema_version": "1.0",
    "dataset_name": "sbor-validation",
    "dataset_version": "0.1.0",
    "generator_revision": "git commit of dataset generator"
}
```

### Input item schema

```json
{
    "schema_version": "1.0",
    "key": "sha256 of source and MR revisions",
    "repo_url": "source repository URL",
    "source": {
        "dataset": "source dataset",
        "dataset_version": "pinned source dataset git commit"
    },
    "mr": {
        "url": "MR URL",
        "title": "MR title",
        "description": "MR description",
        "base_sha": "commit before the MR changes (MR target branch)",
        "head_sha": "commit containing the defects (MR source branch)"
    }
}
```

### Label item schema

```json
{
    "schema_version": "1.0",
    "key": "key of the corresponding input item",
    "defects": [{
        "file_path": "path to the file with found defect",
        "start_line": 67,
        "end_line": 69,
        "category": "defect category",
        "description": "text description of the defect"
    }]
}
```

- `key` is the lowercase hexadecimal sha256 of the string `dataset + "\\0" + dataset_version + "\\0" + mr.url + "\\0" + base_sha + "\\0" + head_sha`. It identifies the exact source record and MR revision used in a dataset release
- Source metadata is stored per item because one repository may contain MRs from multiple source datasets
- `diff_sha256` is SHA-256 of the output of `git diff --binary --no-ext-diff base_sha..head_sha`.
- The MVP includes only defects whose location is in `head_sha` (the right side of an MR diff). AACR-Bench records on the left side of a diff are excluded by the converter.
- Every `input.jsonl` key must have exactly one `labels.jsonl` record, including clean MRs with `defects: []`

## Current state of the defect categories

- Only two types of defect categories are used for simplicity:
    1. *Functional*
    2. *Evolvability*

> Right now, generator emits only *functional* defects
