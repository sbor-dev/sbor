import subprocess
from pathlib import Path

import click

from sbor.review import ReviewRequest, run_review


@click.command()
@click.option(
    "--workspace",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
)
@click.option("--base-sha", required=True)
@click.option("--head-sha", required=True)
@click.option("--change-id", required=True)
@click.option("--title", required=True)
@click.option("--description", required=True)
@click.option("--url", required=True)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--assets-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    envvar="SBOR_REVIEWER_ASSETS_DIR",
    default=Path("/opt/sbor/reviewer"),
    show_default=True,
)
def main(
    workspace: Path,
    base_sha: str,
    head_sha: str,
    change_id: str,
    title: str,
    description: str,
    url: str,
    output_dir: Path,
    assets_dir: Path,
) -> None:
    """Review one already checked-out merge or pull request."""
    request = ReviewRequest(
        workspace=workspace,
        base_sha=base_sha,
        head_sha=head_sha,
        change_id=change_id,
        title=title,
        description=description,
        url=url,
        output_dir=output_dir,
        assets_dir=assets_dir,
    )

    try:
        result = run_review(request)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise click.ClickException(str(error)) from error

    click.echo(
        f"Review completed with {result['findings_count']} finding(s); "
        f"artifacts: {output_dir.resolve()}"
    )


if __name__ == "__main__":
    main()
