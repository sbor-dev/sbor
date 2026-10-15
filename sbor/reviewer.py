import json
from pathlib import Path


def render_prompt(
    prompt_path: Path,
    title: str,
    description: str,
    report_dir: Path,
    diff_path: Path,
) -> str:
    template = prompt_path.read_text(encoding="utf-8")

    return template.format(
        title=json.dumps(title, ensure_ascii=True),
        description=json.dumps(description, ensure_ascii=True),
        report_dir=str(report_dir),
        diff_path=str(diff_path),
    )


def reviewer_command(
    model: str,
    prompt: str,
    provider: str,
    *,
    system_prompt: str | None = None,
    skill_paths: tuple[Path, ...] = (),
    isolated: bool = False,
) -> list[str]:
    command = ["pi"]

    if isolated:
        command.extend(["--no-session", "--no-context-files"])

    if system_prompt is not None:
        command.extend(["--system-prompt", system_prompt])

    for skill_path in skill_paths:
        command.extend(["--skill", str(skill_path)])

    command.extend(
        [
            "--provider",
            provider,
            "--model",
            model,
            "--mode",
            "json",
            prompt,
        ]
    )
    return command
