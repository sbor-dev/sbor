import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TextIO

from validation.common import JsonObject


def run_pi_with_reasoning_capture(
    command: list[str],
    cwd: Path,
    reasoning_path: Path,
    verbose: bool,
    role: str,
) -> None:
    reasoning_path.parent.mkdir(parents=True, exist_ok=True)

    with (
        reasoning_path.open("a", encoding="utf-8") as reasoning_file,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file,
    ):
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=None if verbose else stderr_file,
            text=True,
        )
        assistant_error: str | None = None
        text_was_streamed = False
        text_ends_with_newline = True
        thinking_block_started = False

        try:
            if process.stdout is None:
                raise RuntimeError(f"{role} stdout is unavailable")

            for line_number, line in enumerate(process.stdout, start=1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        f"{role} emitted invalid JSON on line {line_number}: {error}"
                    ) from error

                if not isinstance(event, dict):
                    continue

                update = _assistant_update(event)

                if update is not None:
                    update_type = update.get("type")
                    delta = update.get("delta")

                    if update_type == "thinking_start":
                        thinking_block_started = False
                    elif update_type == "thinking_delta" and isinstance(delta, str):
                        if not thinking_block_started:
                            _start_reasoning_block(reasoning_file)
                            thinking_block_started = True

                        reasoning_file.write(delta)
                        reasoning_file.flush()
                    elif update_type == "thinking_end":
                        thinking_block_started = False
                    elif (
                        verbose
                        and update_type == "text_delta"
                        and isinstance(delta, str)
                    ):
                        sys.stdout.write(delta)
                        sys.stdout.flush()
                        text_was_streamed = True
                        text_ends_with_newline = delta.endswith("\n")

                error_message = _assistant_error(event)

                if error_message is not None:
                    assistant_error = error_message
        except BaseException:
            process.terminate()
            process.wait()
            raise
        finally:
            if verbose and text_was_streamed and not text_ends_with_newline:
                sys.stdout.write("\n")
                sys.stdout.flush()

        returncode = process.wait()
        stderr_file.seek(0)
        stderr = stderr_file.read().strip()

    if returncode:
        message = f"{role} exited with code {returncode}"

        if stderr:
            message = f"{message}: {stderr}"

        raise RuntimeError(message)

    if assistant_error is not None:
        raise RuntimeError(f"{role} failed: {assistant_error}")


def _assistant_update(event: JsonObject) -> JsonObject | None:
    if event.get("type") != "message_update":
        return None

    update = event.get("assistantMessageEvent")

    return update if isinstance(update, dict) else None


def _assistant_error(event: JsonObject) -> str | None:
    if event.get("type") != "message_end":
        return None

    message = event.get("message")

    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None

    stop_reason = message.get("stopReason")

    if stop_reason not in {"error", "aborted"}:
        return None

    detail = message.get("errorMessage")

    return detail if isinstance(detail, str) and detail else str(stop_reason)


def _start_reasoning_block(handle: TextIO) -> None:
    if handle.tell() == 0:
        return

    handle.seek(0, 2)
    handle.write("\n\n")
