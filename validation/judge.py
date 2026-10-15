import json
import os
import subprocess
from pathlib import Path

from validation.common import JsonObject
from validation.downloader import PreparedReview
from validation.pi_output import run_pi_with_reasoning_capture
from validation.reviewer import configure_pi

JUDGE_DIR = Path("/home/sbor/.pi/judge")
PROMPT_PATH = JUDGE_DIR / "judgment_prompt.txt"
SYSTEM_PATH = JUDGE_DIR / "SYSTEM.md"
SKILL_PATH = JUDGE_DIR / "skills/judge-skill/SKILL.md"
TEMPLATE_PATH = JUDGE_DIR / "skills/judge-skill/assets/template.json"


def configure_judge_pi(llm_configuration: JsonObject) -> str:
    return configure_pi(llm_configuration, JUDGE_DIR)


def render_prompt(
    prompt_path: Path,
    key: str,
    label: JsonObject,
    report_path: Path,
    diff_path: Path,
    judgment_path: Path,
    template_path: Path = TEMPLATE_PATH,
    validation_error: str | None = None,
) -> str:
    template = prompt_path.read_text(encoding="utf-8")
    repair_instruction = ""

    if validation_error is not None:
        repair_instruction = (
            "A previous judgment failed validation with this error:\n"
            f"{validation_error}\n"
            "Rewrite judgment.json from scratch. Do not preserve the previous shape."
        )

    return template.format(
        key=json.dumps(key, ensure_ascii=True),
        label=json.dumps(label, ensure_ascii=True, indent=2),
        report_path=str(report_path),
        diff_path=str(diff_path),
        judgment_path=str(judgment_path),
        judgment_schema=template_path.read_text(encoding="utf-8").strip(),
        repair_instruction=repair_instruction,
    )


def judge_command(
    model: str,
    prompt: str,
    capture_reasoning: bool = False,
) -> list[str]:
    command = [
        "runuser",
        "-u",
        "sbor",
        "--",
        "env",
        "HOME=/home/sbor",
        f"PI_CODING_AGENT_DIR={JUDGE_DIR}",
        "pi",
    ]

    if capture_reasoning:
        command.extend(["--mode", "json"])
    else:
        command.append("--print")

    command.extend(
        [
            "--no-session",
            "--no-context-files",
            "--system-prompt",
            SYSTEM_PATH.read_text(encoding="utf-8"),
            "--skill",
            str(SKILL_PATH),
            "--provider",
            "validation",
            "--model",
            model,
            prompt,
        ]
    )
    return command


def run_judge(
    prepared: PreparedReview,
    report_path: Path,
    judgment_path: Path,
    model: str,
    key: str,
    label: JsonObject,
    verbose: bool,
    prompt_path: Path = PROMPT_PATH,
    validation_error: str | None = None,
    reasoning_path: Path | None = None,
) -> None:
    judgment_path.parent.mkdir(exist_ok=True)
    user_stat = Path("/home/sbor").stat()
    os.chown(judgment_path.parent, user_stat.st_uid, user_stat.st_gid)
    prompt = render_prompt(
        prompt_path,
        key,
        label,
        report_path,
        prepared.diff_path,
        judgment_path,
        validation_error=validation_error,
    )
    command = judge_command(model, prompt, reasoning_path is not None)

    if reasoning_path is not None:
        run_pi_with_reasoning_capture(
            command,
            prepared.repository_dir,
            reasoning_path,
            verbose,
            "Judge",
        )
        return

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
