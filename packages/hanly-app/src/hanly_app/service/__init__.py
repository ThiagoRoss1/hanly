"""Internal Python desktop service and its bounded protocol."""

from __future__ import annotations

from .application import DesktopService, ServiceError
from .protocol import (
    MAX_FRAME_BYTES,
    MAX_PENDING_REQUESTS,
    MAX_STRUCTURE_DEPTH,
    PROTOCOL_VERSION,
    ProtocolFailure,
    Request,
    encode_event,
    encode_reply,
    parse_request,
    validate_event,
)

__all__ = [
    "DesktopService",
    "ServiceError",
    "MAX_FRAME_BYTES",
    "MAX_PENDING_REQUESTS",
    "MAX_STRUCTURE_DEPTH",
    "PROTOCOL_VERSION",
    "ProtocolFailure",
    "Request",
    "encode_event",
    "encode_reply",
    "parse_request",
    "validate_event",
]
