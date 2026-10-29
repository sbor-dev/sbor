import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, cast

from sbor.common import JsonObject


@dataclass(frozen=True)
class InferenceStats:
    output_tokens: int
    duration_seconds: float


def run_pi_with_reasoning_capture(
    command: list[str],
    cwd: Path,
    reasoning_path: Path,
    verbose: bool,
    role: str,
) -> InferenceStats:
    return run_pi_json(command, cwd, verbose, role, reasoning_path)


def run_pi_json(
    command: list[str],
    cwd: Path,
    verbose: bool,
    role: str,
    reasoning_path: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> InferenceStats:
    if reasoning_path is not None:
        reasoning_path.parent.mkdir(parents=True, exist_ok=True)

    reasoning_context = (
        reasoning_path.open("a", encoding="utf-8")
        if reasoning_path is not None
        else nullcontext(None)
    )

    with (
        reasoning_context as optional_reasoning_file,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file,
    ):
        reasoning_file = cast(TextIO | None, optional_reasoning_file)
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=None if verbose else stderr_file,
            text=True,
        )
        assistant_error: str | None = None
        text_was_streamed = False
        text_ends_with_newline = True
        thinking_block_started = False
        response_started_at: float | None = None
        response_output_tokens: int | None = None
        output_tokens = 0
        inference_seconds = 0.0

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

                message = event.get("message")

                if (
                    event.get("type") == "message_start"
                    and isinstance(message, dict)
                    and message.get("role") == "assistant"
                ):
                    response_started_at = time.monotonic()
                    response_output_tokens = None

                update = _assistant_update(event)

                if update is not None:
                    if response_started_at is None:
                        response_started_at = time.monotonic()

                    usage_output = _usage_output_tokens(event.get("usage"))

                    if usage_output is not None:
                        response_output_tokens = usage_output

                    update_type = update.get("type")
                    delta = update.get("delta")

                    if update_type == "thinking_start":
                        thinking_block_started = False
                    elif (
                        reasoning_file is not None
                        and update_type == "thinking_delta"
                        and isinstance(delta, str)
                    ):
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

                if (
                    event.get("type") == "message_end"
                    and isinstance(message, dict)
                    and message.get("role") == "assistant"
                ):
                    final_output = _usage_output_tokens(message.get("usage"))

                    if final_output is not None:
                        response_output_tokens = final_output

                    if response_started_at is not None:
                        inference_seconds += time.monotonic() - response_started_at

                    if response_output_tokens is not None:
                        output_tokens += response_output_tokens

                    response_started_at = None
                    response_output_tokens = None

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

    return InferenceStats(output_tokens, inference_seconds)


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


def _usage_output_tokens(value: object) -> int | None:
    if not isinstance(value, dict):
        return None

    output = value.get("output")

    if isinstance(output, int) and not isinstance(output, bool) and output >= 0:
        return output

    return None


def _start_reasoning_block(handle: TextIO) -> None:
    if handle.tell() == 0:
        return

    handle.seek(0, 2)
    handle.write("\n\n")
