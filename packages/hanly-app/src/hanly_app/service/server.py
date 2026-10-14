"""Bounded JSONL entry point for the supervised desktop service."""

from __future__ import annotations

import argparse
import os
import re
import sys
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

from .application import DesktopService, ServiceError
from .event_loop import SerializedEventLoop
from .protocol import (
    MAX_FRAME_BYTES,
    ProtocolFailure,
    Request,
    encode_event,
    encode_reply,
    parse_request,
)

_ROI_PATTERN = re.compile(r"^(\d{1,5})[x,](\d{1,5})$")
_READ_CHUNK_BYTES = 64 * 1024


class _ProtocolTraceSink:
    """Enable only metadata trace forwarding for the explicit lab flag."""

    def emit(self, _event: object) -> None:
        return None


def main(argv: list[str] | None = None) -> int:
    """Serve requests on stdin and write protocol messages on stdout only."""

    args = _build_parser().parse_args(argv)
    with _protocol_output() as writer:
        return _serve(args, writer)


def _serve(args: argparse.Namespace, writer: BinaryIO) -> int:
    loop: SerializedEventLoop[Request | ProtocolFailure] = SerializedEventLoop()
    try:
        service = DesktopService(
            args.app_config,
            runtime_config_path=args.runtime_config,
            roi_size=args.roi,
            installation_root=args.installation_root,
            root_pid=args.root_pid,
            event_loop=loop,
            trace_sink=_ProtocolTraceSink() if args.trace else None,
            self_check_mode=args.self_check_mode,
        )
    except Exception:
        _diagnostic("service_start_failed")
        return 2

    # A daemon blocked in BufferedReader.readline() can hold stdin's internal
    # lock while the interpreter finalizes after an explicit shutdown. Read
    # the descriptor directly so an open supervisor pipe cannot deadlock exit.
    reader = _FrameReader(sys.stdin.fileno())
    event_sequence = 0

    def write_event(name: str, payload: Mapping[str, Any]) -> None:
        nonlocal event_sequence
        event_sequence += 1
        try:
            frame = encode_event(event_sequence, name, payload)
        except (TypeError, ValueError):
            _diagnostic("event_rejected")
            return
        writer.write(frame)
        writer.flush()

    service.set_event_sink(write_event)

    def read_requests() -> None:
        while True:
            try:
                frame = reader.read_frame()
            except ProtocolFailure as error:
                loop.fail_input()
                _diagnostic(error.code)
                return
            except OSError:
                loop.fail_input()
                _diagnostic("stdin_read_failed")
                return
            if frame is None:
                loop.close_input()
                return
            try:
                request = parse_request(frame)
            except ProtocolFailure as error:
                if error.request_id is None:
                    loop.fail_input()
                    _diagnostic(error.code)
                    return
                item: Request | ProtocolFailure = error
            else:
                item = request
            if not loop.enqueue_request(item):
                loop.fail_input()
                _diagnostic("pending_overflow")
                return

    reader_thread = threading.Thread(
        target=read_requests,
        name="hanly-service-stdin",
        daemon=True,
    )
    reader_thread.start()

    def handle(item: Request | ProtocolFailure) -> None:
        if isinstance(item, ProtocolFailure):
            _write_reply(
                writer,
                item.request_id,
                error={"code": item.code, "message": item.message},
            )
            return

        try:
            result = service.dispatch(item)
        except ServiceError as error:
            _write_reply(
                writer,
                item.request_id,
                error={"code": error.code, "message": error.message},
            )
        except Exception as error:
            service.log.record(
                "Service",
                f"{item.method} failed ({type(error).__name__}).",
                level="error",
            )
            _diagnostic("request_failed")
            _write_reply(
                writer,
                item.request_id,
                error={
                    "code": "internal_error",
                    "message": "The service could not complete the request.",
                },
            )
        else:
            _write_reply(writer, item.request_id, result=result)
            service.after_reply(item)

        if service.shutdown_requested:
            loop.stop()

    try:
        clean = loop.run(handle)
    finally:
        service.close()
    return 0 if clean else 2


@contextmanager
def _protocol_output() -> Iterator[BinaryIO]:
    """Keep Python and native stdout noise away from the JSONL channel."""

    original_stdout = sys.stdout
    stdout_fd: int | None = None
    writer: BinaryIO | None = None
    quiet_stream = None
    try:
        stdout_fd = original_stdout.fileno()
        protocol_fd = os.dup(stdout_fd)
        quiet_stream = open(os.devnull, "w", encoding="utf-8")
        os.dup2(quiet_stream.fileno(), stdout_fd)
        writer = os.fdopen(protocol_fd, "wb", buffering=0)
        sys.stdout = quiet_stream
    except (AttributeError, OSError, ValueError):
        if writer is not None:
            writer.close()
        if quiet_stream is not None:
            quiet_stream.close()
        writer = getattr(original_stdout, "buffer", None)
        if writer is None:
            raise RuntimeError("protocol stdout is unavailable")
        quiet_stream = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = quiet_stream

    try:
        yield writer
    finally:
        sys.stdout = original_stdout
        if stdout_fd is not None and writer is not None:
            try:
                os.dup2(writer.fileno(), stdout_fd)
            except (OSError, ValueError):
                pass
        if writer is not None and writer is not getattr(original_stdout, "buffer", None):
            writer.close()
        if quiet_stream is not None:
            quiet_stream.close()


def _write_reply(
    writer: BinaryIO,
    request_id: str | None,
    *,
    result: object | None = None,
    error: dict[str, str] | None = None,
) -> None:
    if request_id is None:
        _diagnostic("uncorrelated_error")
        return
    try:
        frame = encode_reply(
            request_id,
            result=result if isinstance(result, dict) else None,
            error=error,
        )
    except (TypeError, ValueError):
        frame = encode_reply(
            request_id,
            error={
                "code": "response_too_large",
                "message": "Service response exceeds the frame limit.",
            },
        )
    writer.write(frame)
    writer.flush()


class _FrameReader:
    """Read bounded JSONL frames from an unbuffered descriptor."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor
        self._buffer = bytearray()

    def read_frame(self) -> bytes | None:
        """Return the next LF-delimited frame, retaining any following bytes."""

        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                frame = line[:-1] if line.endswith(b"\r") else line
                if len(frame) > MAX_FRAME_BYTES:
                    raise ProtocolFailure(
                        "frame_too_large", "Request frame exceeds 1 MiB."
                    )
                return frame

            if len(self._buffer) > MAX_FRAME_BYTES + 1:
                raise ProtocolFailure(
                    "frame_too_large", "Request frame exceeds 1 MiB."
                )

            remaining = MAX_FRAME_BYTES + 2 - len(self._buffer)
            chunk = os.read(self._descriptor, min(_READ_CHUNK_BYTES, remaining))
            if not chunk:
                if not self._buffer:
                    return None
                if len(self._buffer) > MAX_FRAME_BYTES:
                    raise ProtocolFailure(
                        "frame_too_large", "Request frame exceeds 1 MiB."
                    )
                raise ProtocolFailure(
                    "unterminated_frame", "Request frame is not newline terminated."
                )
            self._buffer.extend(chunk)


def _diagnostic(code: str) -> None:
    """Write a frame-free diagnostic marker for the native supervisor."""

    try:
        sys.stderr.write(f"hanly-service: {code}\n")
        sys.stderr.flush()
    except (OSError, ValueError, AttributeError):
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hanly-service", add_help=True)
    parser.add_argument("--app-config", type=Path)
    parser.add_argument("--runtime-config", type=Path)
    parser.add_argument("--roi", type=_parse_roi, default=(200, 100))
    parser.add_argument("--installation-root", type=Path)
    parser.add_argument("--root-pid", type=_positive_pid)
    parser.add_argument("--trace", action="store_true")
    parser.add_argument(
        "--self-check-mode",
        choices=("inventory", "ocr", "worker", "ui"),
    )
    return parser


def _parse_roi(value: str) -> tuple[int, int]:
    match = _ROI_PATTERN.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError("ROI must be WIDTHxHEIGHT")
    width, height = int(match.group(1)), int(match.group(2))
    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise argparse.ArgumentTypeError("ROI dimensions must be between 1 and 4096")
    return width, height


def _positive_pid(value: str) -> int:
    try:
        pid = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("root PID must be a positive integer") from error
    if pid <= 0:
        raise argparse.ArgumentTypeError("root PID must be a positive integer")
    return pid
