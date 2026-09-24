import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from validation.common import JsonObject, required_mapping, required_text


@dataclass(frozen=True)
class PreparedReview:
    repository_dir: Path
    diff_path: Path
    diff_sha256: str


def run_git(arguments: list[str], cwd: Path | None = None) -> str:
    command = ["git", *arguments]
    result = subprocess.run(
        command,
        cwd=cwd,
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


def prepare_review(item: JsonObject, work_dir: Path) -> PreparedReview:
    repository_url = required_text(item, "repo_url")
    mr = required_mapping(item, "mr")
    base_sha = required_text(mr, "base_sha")
    head_sha = required_text(mr, "head_sha")
    repository_dir = work_dir / "repository"
    diff_path = work_dir / "diff.patch"

    run_git(["clone", "--no-checkout", repository_url, str(repository_dir)])
    run_git(
        ["fetch", "--no-tags", "origin", base_sha, head_sha],
        repository_dir,
    )
    run_git(["checkout", "--detach", head_sha], repository_dir)
    diff = run_git(
        ["diff", "--binary", "--no-ext-diff", f"{base_sha}..{head_sha}"],
        repository_dir,
    )
    diff_path.write_text(diff, encoding="utf-8")

    return PreparedReview(
        repository_dir=repository_dir,
        diff_path=diff_path,
        diff_sha256=sha256(diff.encode("utf-8")).hexdigest(),
    )
