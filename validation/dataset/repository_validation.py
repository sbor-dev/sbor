import os
import subprocess
from pathlib import Path

from validation.dataset.common import JsonObject


class RepositoryValidationError(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def validate_repository(item: JsonObject, work_dir: Path) -> None:
    repository_url = _required_text(item, "repo_url")
    mr = _required_mapping(item, "mr")
    base_sha = _required_text(mr, "base_sha")
    head_sha = _required_text(mr, "head_sha")
    work_dir.mkdir(parents=True)

    _require_git(
        ["ls-remote", repository_url, "HEAD"],
        reason="repository_unavailable",
    )

    repository_dir = work_dir / "repository.git"
    _require_git(["init", "--bare", "--quiet", str(repository_dir)])
    _require_git(["remote", "add", "origin", repository_url], cwd=repository_dir)
    _fetch_revision(repository_dir, base_sha, "base_revision_unavailable")
    _fetch_revision(repository_dir, head_sha, "head_revision_unavailable")

    result = _run_git(["merge-base", base_sha, head_sha], cwd=repository_dir)

    if result.returncode:
        detail = _git_error(result)

        if result.returncode == 1:
            detail = f"Revisions {base_sha} and {head_sha} have no common ancestor"

        reason = (
            "history_mismatch"
            if result.returncode == 1
            else "repository_validation_failed"
        )
        raise RepositoryValidationError(reason, detail)


def _fetch_revision(repository_dir: Path, revision: str, reason: str) -> None:
    _require_git(
        [
            "fetch",
            "--quiet",
            "--no-tags",
            "--filter=tree:0",
            "origin",
            revision,
        ],
        cwd=repository_dir,
        reason=reason,
    )


def _run_git(
    arguments: list[str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"

    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _require_git(
    arguments: list[str],
    cwd: Path | None = None,
    reason: str = "repository_validation_failed",
) -> None:
    result = _run_git(arguments, cwd)

    if result.returncode:
        raise RepositoryValidationError(reason, _git_error(result))


def _git_error(result: subprocess.CompletedProcess[str]) -> str:
    detail = result.stderr.strip() or result.stdout.strip()

    if detail:
        return detail

    return f"Git exited with code {result.returncode}"


def _required_mapping(configuration: JsonObject, field: str) -> JsonObject:
    value = configuration.get(field)

    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping field {field}")

    return value


def _required_text(configuration: JsonObject, field: str) -> str:
    value = configuration.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string field {field}")

    return value.strip()
