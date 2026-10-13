"""Bounded JSONL process entry point for the desktop service."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import BinaryIO

from .application import DesktopService, ServiceError
from .protocol import MAX_FRAME_BYTES, ProtocolFailure, encode_reply, parse_request


def main(argv: list[str] | None = None) -> int:
    """Serve requests on stdin and write protocol replies on stdout only."""

    args = _build_parser().parse_args(argv)
    try:
        service = DesktopService(args.app_config)
    except Exception:
        _diagnostic("service_start_failed")
        return 2

    reader = sys.stdin.buffer
    writer = sys.stdout.buffer
    while True:
        try:
            frame = _read_frame(reader)
        except ProtocolFailure as error:
            _diagnostic(error.code)
            return 2
        if frame is None:
            return 0

        try:
            request = parse_request(frame)
        except ProtocolFailure as error:
            if error.request_id is None:
                _diagnostic(error.code)
                return 2
            writer.write(
                encode_reply(
                    error.request_id,
                    error={"code": error.code, "message": error.message},
                )
            )
            writer.flush()
            continue

        try:
            result = service.dispatch(request)
        except ServiceError as error:
            response = encode_reply(
                request.request_id,
                error={"code": error.code, "message": error.message},
            )
        except Exception:
            _diagnostic("request_failed")
            response = encode_reply(
                request.request_id,
                error={
                    "code": "internal_error",
                    "message": "The service could not complete the request.",
                },
            )
        else:
            try:
                response = encode_reply(request.request_id, result=result)
            except (TypeError, ValueError):
                response = encode_reply(
                    request.request_id,
                    error={
                        "code": "response_too_large",
                        "message": "Service response exceeds the frame limit.",
                    },
                )

        writer.write(response)
        writer.flush()
        if service.shutdown_requested:
            return 0


def _read_frame(reader: BinaryIO) -> bytes | None:
    """Read one bounded LF-delimited frame, draining oversize input safely."""

    line = reader.readline(MAX_FRAME_BYTES + 2)
    if not line:
        return None
    if not line.endswith(b"\n"):
        if len(line) > MAX_FRAME_BYTES:
            raise ProtocolFailure("frame_too_large", "Request frame exceeds 1 MiB.")
        raise ProtocolFailure("unterminated_frame", "Request frame is not newline terminated.")

    frame = line[:-1]
    if frame.endswith(b"\r"):
        frame = frame[:-1]
    if len(frame) > MAX_FRAME_BYTES:
        raise ProtocolFailure("frame_too_large", "Request frame exceeds 1 MiB.")
    return frame


def _diagnostic(code: str) -> None:
    """Write a frame-free error marker to stderr for the native supervisor."""

    try:
        sys.stderr.write(f"hanly-service: {code}\n")
        sys.stderr.flush()
    except (OSError, ValueError, AttributeError):
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hanly-service", add_help=True)
    parser.add_argument(
        "--app-config",
        type=Path,
        help="path to the per-user desktop settings JSON file",
    )
    return parser
