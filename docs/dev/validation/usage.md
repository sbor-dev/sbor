# Validation usage

## Validation dataset

### Building

```bash
python -m validation.dataset.build --output-dir sbor-dataset
```

or via uv:

```bash
uv run python -m validation.dataset.build --output-dir sbor-dataset
```

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
  --verbose
```