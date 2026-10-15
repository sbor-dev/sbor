# Validation artifacts

Each validation run is stored in a separate directory:

```text
runs/<run-id>/
├── metadata.yaml
├── validation.yaml
├── run.json
├── metrics.json
└── items/<item-key>/
    ├── result.json
    ├── report.json
    ├── report.md
    ├── judgment.json
    ├── reviewer-reasoning.txt
    └── judge-reasoning.txt
```

The `*-reasoning.txt` files are created only when `capture_reasoning` is enabled

## Input metadata

Metadata is provided as a required YAML file. An unknown optional value is recorded as `null`

```yaml
schema_version: "1.0"
experiment:
  name: local-model-selection
  run_name: deepseek-flash-smoke
  tags: {"smoke"}
dataset:
  repository: org/repository
  revision: main
  version: "2026-09-28"
  sha256: null
reviewer:
  provider: openai-compatible
  model: deepseek-ai/DeepSeek-V4-Flash
  revision: null
  weight_quantization: null
  kv_cache_quantization: null
  context_tokens: null
  temperature: null
  seed: null
  max_output_tokens: null
  inference_command: null
judge:
  provider: openai-compatible
  model: fixed-judge-model
  revision: null
  weight_quantization: null
  kv_cache_quantization: null
  context_tokens: null
  temperature: null
  seed: null
  max_output_tokens: null
  inference_command: null
```

## `run.json`

```json
{
  "schema_version": "1.0",
  "run_id": "20260928T120000Z-deepseek-flash-smoke",
  "status": "completed",
  "started_at": "2026-09-28T12:00:00Z",
  "finished_at": "2026-09-28T13:15:00Z",
  "code": {
    "revision": "0123456789abcdef",
    "dirty": false
  },
  "dataset": {
    "repository": "org/repository",
    "revision": "main",
    "version": "2026-09-28",
    "sha256": null,
    "items": 200
  }
}
```

## `result.json`

```json
{
  "schema_version": "1.0",
  "item_key": "owner/repository@revision",
  "status": "succeeded",
  "stage": "completed",
  "started_at": "2026-09-28T12:00:01Z",
  "finished_at": "2026-09-28T12:04:25Z",
  "stages": {
    "fetch": {
      "started_at": "2026-09-28T12:00:01Z",
      "finished_at": "2026-09-28T12:00:31Z"
    },
    "reviewer": {
      "started_at": "2026-09-28T12:00:31Z",
      "finished_at": "2026-09-28T12:03:40Z"
    },
    "judge": {
      "started_at": "2026-09-28T12:03:40Z",
      "finished_at": "2026-09-28T12:04:25Z"
    }
  },
  "diff": {
    "base_revision": "0123456789abcdef",
    "target_revision": "fedcba9876543210",
    "sha256": "..."
  },
  "error": null
}
```

## `metrics.json`

```json
{
  "schema_version": "1.0",
  "execution": {
    "items_succeeded": 180,
    "items_failed": 15,
    "items_timed_out": 5
  },
  "quality": {
    "findings_supported": 120,
    "findings_unsupported": 20,
    "labels_matched": 100,
    "labels_missed": 30,
    "clean_items": 50,
    "clean_items_with_unsupported_findings": 4
  },
  "timing_seconds": {
    "item": {"avg": 240.1, "median": 220.0, "p95": 500.0, "p99": 700.0},
    "fetch": {"avg": 25.0, "median": 20.0, "p95": 60.0, "p99": 90.0},
    "reviewer": {"avg": 170.0, "median": 160.0, "p95": 350.0, "p99": 480.0},
    "judge": {"avg": 45.1, "median": 40.0, "p95": 100.0, "p99": 140.0}
  },
  "inference": {
    "avg_tokens_per_second": 32.4
  }
}
```

Timing distributions include succeeded items only. Empty distributions use
`null` for every statistic. `avg_tokens_per_second` applies only to the reviewer
and is calculated as total output tokens divided by total model-response time;
tool execution time is excluded. It is `null` when the provider does not expose
token usage.

## Dataset build report

The builder creates `build-report.json` next to the dataset:

```json
{
  "schema_version": "1.0",
  "dataset_version": "2026-09-28",
  "started_at": "2026-09-28T10:00:00Z",
  "finished_at": "2026-09-28T10:20:00Z",
  "items_written": 214,
  "items_skipped": 7,
  "sources": {
    "c_cpp": {"written": 120, "skipped": 2},
    "swrbench": {"written": 94, "skipped": 5}
  },
  "skipped": [
    {
      "source": "c_cpp",
      "source_id": "example-42",
      "reason": "branch_unavailable",
      "detail": "origin/review-branch was not found"
    }
  ]
}
```

An unavailable item is reported in the terminal, recorded in `skipped`, and
does not stop the remaining items from being built.
