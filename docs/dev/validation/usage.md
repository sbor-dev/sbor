# Validation usage

The validation contracts are documented in:

- [Experiment and artifact schemas](artifacts.md)
- [Validation dataset](dataset.md)

## Validation dataset

### Building

```bash
python -m validation.dataset.build --output-dir sbor-dataset --verbose
```

or via uv:

```bash
uv run python -m validation.dataset.build --output-dir sbor-dataset --verbose
```

### Generating subsets

Subset membership is defined by item keys in `config/validation_dataset_subsets.yaml`. Generate the configured datasets with:

```bash
uv run python -m validation.dataset.subsets \
  --dataset-dir sbor-dataset \
  --output-dir sbor-dataset/subsets/ \
  --verbose
```

Each generated subset is a standalone dataset directory containing a copy of `metadata.json` and filtered `input.jsonl` and `labels.jsonl` files

## Validation

Run validation with Deepseek API

```bash
{
  printf '%s\n' 'model: deepseek-chat'
  printf '%s\n' 'base_url: https://api.deepseek.com/v1'
  printf '%s\n' 'api: openai-completions'
  printf 'token: %s\n' "$DEEPSEEK_TOKEN"
} | uv run --no-sync python -m validation.validate \
  --dataset-dir sbor-dataset \
  --output-dir runs \
  --metadata experiment.yaml \
  --verbose
```
