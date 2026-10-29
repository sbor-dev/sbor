import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sbor.common import JsonObject
from sbor.pi import configure_pi, load_runtime_configuration
from sbor.pi_output import run_pi_json
from sbor.reports import load_reports
from sbor.reviewer import render_prompt, reviewer_command

PROVIDER_NAME = "sbor"


@dataclass(frozen=True)
class ReviewRequest:
    workspace: Path
    base_sha: str
    head_sha: str
    change_id: str
    title: str
    description: str
    url: str
    output_dir: Path
    assets_dir: Path


def run_review(
    request: ReviewRequest,
    environment: Mapping[str, str] | None = None,
) -> JsonObject:
    source_environment = os.environ if environment is None else environment
    output_dir = request.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_managed_outputs(output_dir)
    started_at = _timestamp()
    result = _base_result(request, started_at)

    try:
        workspace = _validate_workspace(request.workspace)
        base_sha = _resolve_commit(workspace, request.base_sha, "base")
        head_sha = _resolve_commit(workspace, request.head_sha, "head")
        _validate_checkout(workspace, head_sha)
        assets = _reviewer_assets(request.assets_dir)
        llm_configuration = load_runtime_configuration(
            "reviewer",
            source_environment,
        )

        with tempfile.TemporaryDirectory(prefix="sbor-review-") as temporary:
            runtime_dir = Path(temporary)
            diff_path = runtime_dir / "diff.patch"
            diff = _create_diff(workspace, base_sha, head_sha)
            diff_path.write_bytes(diff)
            report_dir = runtime_dir / "report"
            report_dir.mkdir()
            agent_dir = runtime_dir / "agent"
            shutil.copytree(assets["system"].parent, agent_dir)
            model = configure_pi(
                llm_configuration,
                agent_dir,
                PROVIDER_NAME,
            )
            diff_sha256 = hashlib.sha256(diff).hexdigest()
            result.update(
                {
                    "base_sha": base_sha,
                    "head_sha": head_sha,
                    "diff_sha256": diff_sha256,
                    "model": model,
                }
            )
            prompt = render_prompt(
                agent_dir / "validation_prompt.txt",
                request.title,
                request.description,
                report_dir,
                diff_path,
            )
            command = reviewer_command(
                model,
                prompt,
                PROVIDER_NAME,
                isolated=True,
            )
            pi_environment = dict(source_environment)
            pi_environment["PI_CODING_AGENT_DIR"] = str(agent_dir)
            inference = run_pi_json(
                command,
                workspace,
                True,
                "Reviewer",
                environment=pi_environment,
            )
            findings = load_reports(report_dir, workspace)
            shutil.copy2(report_dir / "report.json", output_dir / "report.json")
            shutil.copy2(report_dir / "report.md", output_dir / "report.md")

        result.update(
            {
                "status": "succeeded",
                "finished_at": _timestamp(),
                "findings_count": len(findings),
                "inference": {
                    "output_tokens": inference.output_tokens,
                    "duration_seconds": inference.duration_seconds,
                },
                "error": None,
            }
        )
    except Exception as error:
        result.update(
            {
                "status": "failed",
                "finished_at": _timestamp(),
                "error": str(error),
            }
        )
        _write_json(output_dir / "result.json", result)
        raise

    _write_json(output_dir / "result.json", result)
    return result


def _base_result(request: ReviewRequest, started_at: str) -> JsonObject:
    return {
        "schema_version": "1.0",
        "status": "running",
        "started_at": started_at,
        "finished_at": None,
        "change": {
            "id": request.change_id,
            "title": request.title,
            "url": request.url,
        },
        "base_sha": None,
        "head_sha": None,
        "diff_sha256": None,
        "model": None,
        "findings_count": None,
        "inference": None,
        "error": None,
    }


def _validate_workspace(path: Path) -> Path:
    workspace = path.resolve()

    if not workspace.is_dir():
        raise ValueError(f"Workspace is not a directory: {workspace}")

    root = _run_git(workspace, "rev-parse", "--show-toplevel").strip()
    repository_root = Path(root).resolve()

    if repository_root != workspace:
        raise ValueError(
            f"Workspace must be the repository root: {workspace} != {repository_root}"
        )

    return workspace


def _resolve_commit(workspace: Path, revision: str, role: str) -> str:
    if not revision.strip():
        raise ValueError(f"{role} SHA must not be empty")

    try:
        return _run_git(
            workspace,
            "rev-parse",
            "--verify",
            f"{revision}^{{commit}}",
        ).strip()
    except RuntimeError as error:
        raise ValueError(f"Could not resolve {role} SHA {revision}") from error


def _validate_checkout(workspace: Path, head_sha: str) -> None:
    checkout_sha = _run_git(workspace, "rev-parse", "HEAD").strip()

    if checkout_sha != head_sha:
        raise ValueError(
            f"Workspace HEAD {checkout_sha} does not match requested head {head_sha}"
        )

    status = subprocess.run(
        _git_command(workspace, "diff", "--quiet", "HEAD", "--"),
        cwd=workspace,
        check=False,
    )

    if status.returncode == 1:
        raise ValueError("Workspace contains changes to tracked files")

    if status.returncode:
        raise RuntimeError(
            f"Could not inspect workspace changes: git exited with {status.returncode}"
        )


def _create_diff(workspace: Path, base_sha: str, head_sha: str) -> bytes:
    result = subprocess.run(
        _git_command(
            workspace,
            "diff",
            "--binary",
            "--no-ext-diff",
            f"{base_sha}..{head_sha}",
        ),
        cwd=workspace,
        capture_output=True,
        check=False,
    )

    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        message = (
            "Could not create canonical diff: "
            f"git exited with {result.returncode}"
        )

        if detail:
            message = f"{message}: {detail}"

        raise RuntimeError(message)

    return result.stdout


def _reviewer_assets(directory: Path) -> dict[str, Path]:
    root = directory.resolve()
    assets = {
        "system": root / "SYSTEM.md",
        "prompt": root / "validation_prompt.txt",
        "audit_skill": root / "skills/audit-skill/SKILL.md",
        "report_skill": root / "skills/report-skill/SKILL.md",
    }

    for name, path in assets.items():
        if not path.is_file():
            raise ValueError(f"Missing reviewer asset {name}: {path}")

    return assets


def _run_git(workspace: Path, *arguments: str) -> str:
    result = subprocess.run(
        _git_command(workspace, *arguments),
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        message = f"Git command failed with exit code {result.returncode}"

        if detail:
            message = f"{message}: {detail}"

        raise RuntimeError(message)

    return result.stdout


def _git_command(workspace: Path, *arguments: str) -> list[str]:
    return [
        "git",
        "-c",
        f"safe.directory={workspace.resolve()}",
        *arguments,
    ]


def _clear_managed_outputs(output_dir: Path) -> None:
    for name in ("report.json", "report.md", "result.json"):
        (output_dir / name).unlink(missing_ok=True)


def _write_json(path: Path, payload: JsonObject) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
