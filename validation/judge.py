import json
import os
import subprocess
from pathlib import Path

from validation.common import JsonObject
from validation.downloader import PreparedReview
from validation.reviewer import configure_pi

JUDGE_DIR = Path("/home/sbor/.pi/judge")
PROMPT_PATH = JUDGE_DIR / "judgment_prompt.txt"


def configure_judge_pi(llm_configuration: JsonObject) -> str:
    return configure_pi(llm_configuration, JUDGE_DIR)


def render_prompt(
    prompt_path: Path,
    key: str,
    label: JsonObject,
    report_path: Path,
    judgment_path: Path,
) -> str:
    template = prompt_path.read_text(encoding="utf-8")

    return template.format(
        key=json.dumps(key, ensure_ascii=True),
        label=json.dumps(label, ensure_ascii=True, indent=2),
        report_path=str(report_path),
        judgment_path=str(judgment_path),
    )


def judge_command(model: str, prompt: str) -> list[str]:
    return [
        "runuser",
        "-u",
        "sbor",
        "--",
        "env",
        "HOME=/home/sbor",
        f"PI_CODING_AGENT_DIR={JUDGE_DIR}",
        "pi",
        "--provider",
        "validation",
        "--model",
        model,
        prompt,
    ]


def run_judge(
    prepared: PreparedReview,
    report_path: Path,
    judgment_path: Path,
    model: str,
    key: str,
    label: JsonObject,
    verbose: bool,
    prompt_path: Path = PROMPT_PATH,
) -> None:
    judgment_path.parent.mkdir()
    user_stat = Path("/home/sbor").stat()
    os.chown(judgment_path.parent, user_stat.st_uid, user_stat.st_gid)
    prompt = render_prompt(prompt_path, key, label, report_path, judgment_path)
    command = judge_command(model, prompt)

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
        message = f"Judge exited with code {result.returncode}"

        if detail:
            message = f"{message}: {detail}"

        raise RuntimeError(message)
