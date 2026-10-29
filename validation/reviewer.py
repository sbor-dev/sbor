import os
import subprocess
from pathlib import Path

from sbor.pi import configure_pi as configure_pi_runtime
from sbor.pi_output import InferenceStats, run_pi_json
from sbor.reviewer import render_prompt as render_reviewer_prompt
from sbor.reviewer import reviewer_command as build_reviewer_command
from validation.common import JsonObject
from validation.downloader import PreparedReview

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
    model = configure_pi_runtime(llm_configuration, agent_dir, "validation")
    models_path = agent_dir / "models.json"
    user_id, group_id = agent_user_ids()
    os.chown(agent_dir, user_id, group_id)
    os.chown(models_path, user_id, group_id)

    return model


def render_prompt(
    prompt_path: Path,
    title: str,
    description: str,
    report_dir: Path,
    diff_path: Path = Path("../diff.patch"),
) -> str:
    return render_reviewer_prompt(
        prompt_path,
        title,
        description,
        report_dir,
        diff_path,
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
        *build_reviewer_command(model, prompt, "validation"),
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
    prompt = render_prompt(
        prompt_path,
        title,
        description,
        report_dir,
        prepared.diff_path,
    )
    command = reviewer_command(model, prompt)
    return run_pi_json(
        command,
        prepared.repository_dir,
        verbose,
        "Reviewer",
        reasoning_path,
    )
