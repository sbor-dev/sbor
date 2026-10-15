import json
import os
import subprocess
from pathlib import Path

from validation.common import JsonObject, required_text
from validation.downloader import PreparedReview
from validation.pi_output import InferenceStats, run_pi_json

PROMPT_PATH = Path("/home/sbor/.pi/agent/validation_prompt.txt")
AGENT_DIR = Path("/home/sbor/.pi/agent")


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


def reviewer_command(
    model: str,
    prompt: str,
) -> list[str]:
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
        "--mode",
        "json",
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
    reasoning_path: Path | None = None,
) -> InferenceStats:
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
    return run_pi_json(
        command,
        prepared.repository_dir,
        verbose,
        "Reviewer",
        reasoning_path,
    )
