import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from validation.common import JsonObject, load_yaml_mapping, required_text
from validation.downloader import PreparedReview

PROMPT_PATH = Path("/home/sbor/.pi/agent/validation_prompt.txt")
AGENT_DIR = Path("/home/sbor/.pi/agent")


def load_llm_configuration(path: Path | None, read_stdin: bool) -> JsonObject:
    if read_stdin:
        payload = yaml.safe_load(sys.stdin.read())
    elif path is not None:
        payload = load_yaml_mapping(path)
    else:
        raise ValueError("LLM configuration source is required")

    if not isinstance(payload, dict):
        raise ValueError("Expected LLM configuration mapping")

    for field in ("model", "base_url", "api", "token"):
        required_text(payload, field)

    return payload


def agent_user_ids() -> tuple[int, int]:
    user_stat = Path("/home/sbor").stat()

    return user_stat.st_uid, user_stat.st_gid


def configure_pi(
    llm_configuration: JsonObject,
    agent_dir: Path = AGENT_DIR,
) -> str:
    agent_dir = Path(agent_dir)
    agent_dir.mkdir(parents=True, exist_ok=True)
    model = required_text(llm_configuration, "model")
    payload = {
        "providers": {
            "validation": {
                "baseUrl": required_text(llm_configuration, "base_url"),
                "api": required_text(llm_configuration, "api"),
                "apiKey": required_text(llm_configuration, "token"),
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                },
                "models": [{"id": model, "reasoning": False}],
            }
        }
    }
    models_path = agent_dir / "models.json"
    models_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    user_id, group_id = agent_user_ids()
    os.chown(agent_dir, user_id, group_id)
    os.chown(models_path, user_id, group_id)
    models_path.chmod(0o600)

    return model


def render_prompt(
    prompt_path: Path,
    title: str,
    description: str,
    report_dir: Path,
) -> str:
    template = prompt_path.read_text(encoding="utf-8")

    return template.format(
        title=json.dumps(title, ensure_ascii=True),
        description=json.dumps(description, ensure_ascii=True),
        report_dir=str(report_dir),
    )


def reviewer_command(model: str, prompt: str) -> list[str]:
    return [
        "runuser",
        "-u",
        "sbor",
        "--",
        "env",
        "HOME=/home/sbor",
        "pi",
        "--provider",
        "validation",
        "--model",
        model,
        prompt,
    ]


def run_reviewer(
    prepared: PreparedReview,
    report_dir: Path,
    model: str,
    title: str,
    description: str,
    verbose: bool,
    prompt_path: Path = PROMPT_PATH,
) -> None:
    report_dir.mkdir()
    subprocess.run(
        [
            "chown",
            "-R",
            "sbor:sbor",
            str(prepared.repository_dir),
            str(prepared.diff_path),
            str(report_dir),
        ],
        check=True,
    )
    prompt = render_prompt(prompt_path, title, description, report_dir)
    command = reviewer_command(model, prompt)

    if verbose:
        result = subprocess.run(
            command,
            cwd=prepared.repository_dir,
            check=False,
        )
    else:
        result = subprocess.run(
            command,
            cwd=prepared.repository_dir,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
            check=False,
        )

    if result.returncode:
        detail = result.stderr.strip() if result.stderr else ""
        message = f"Reviewer exited with code {result.returncode}"

        if detail:
            message = f"{message}: {detail}"

        raise RuntimeError(message)
