# Validation dataset

## Canonical schema

### Directory schema

```
sbor-dataset/
├─ 0/
│  ├─ metadata.json
│  ├─ 1.json
│  ├─ 0.json
├─ 1/
│  ├─ metadata.json
│  ├─ 0.json
│  ├─ 1.json
```

- Directories (`0/`, `1/`) represent repositories
- Metadata contains info about repository (see TODO: link to the metadata schema header)
- Each JSON files represent a single MR of the repository. Numeric file names (`0.json` through `n.json`) are stable local identifiers only

### Metadata schema

Contains repository URL so we can clone it into agent's container.

```json
{
    "schema_version": "1.0",
    "repo_url": "repository url"
}
```

### Item schema

```json
{
    "schema_version": "1.0",
    "source_url": "source repository URL",
    "source": {
        "dataset": "source dataset",
        "dataset_version": "pinned source dataset git commit"
    },
    "mr": {
        "url": "MR URL",
        "title": "MR title",
        "description": "MR description",
        "base_sha": "commit before the MR changes (MR target branch)",
        "head_sha": "commit containing the defects (MR source branch)",
        "diff_sha256": "sha256 of the canonical git diff"
    },
    "defects": [{
        "file_path": "path to the file with found defect",
        "start_line": 67,
        "end_line": 69,
        "category": "defect category",
        "description": "text description of the defect"
    }]
}
```

- Source metadata is stored per item because one repository may contain MRs from multiple source datasets
- `diff_sha256` is SHA-256 of the output of `git diff --binary --no-ext-diff base_sha..head_sha`.
- The MVP includes only defects whose location is in `head_sha` (the right side of an MR diff). AACR-Bench records on the left side of a diff are excluded by the converter.

## Current state of the defect categories

- Only two types of defect categories are used for simplicity:
    1. *Functional*
    2. *Evolvability*

> Right now, generator emits only *functional* defects