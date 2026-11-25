import json
from dataclasses import asdict, dataclass

PROTOCOL_VERSION = 1
ENCODING = "utf-8"
MESSAGE_TERMINATOR = b"\n"


@dataclass
class OpenRequest:
    url: str
    version: int = PROTOCOL_VERSION

    def serialize(self) -> bytes:
        return (json.dumps(asdict(self)) + "\n").encode(ENCODING)

    @staticmethod
    def deserialize(data: bytes) -> "OpenRequest":
        obj = json.loads(data.decode(ENCODING).strip())
        if obj.get("version", 1) != PROTOCOL_VERSION:
            raise ValueError(f"Unsupported protocol version: {obj.get('version')}")
        return OpenRequest(url=obj["url"], version=obj.get("version", PROTOCOL_VERSION))


@dataclass
class PingRequest:
    """Liveness probe: lets the remote tell a live socket from a stale one."""

    ping: bool = True
    version: int = PROTOCOL_VERSION

    def serialize(self) -> bytes:
        return (json.dumps(asdict(self)) + "\n").encode(ENCODING)


def deserialize_request(data: bytes) -> "OpenRequest | PingRequest":
    """Decode any request sent by the remote."""
    obj = json.loads(data.decode(ENCODING).strip())
    if obj.get("ping"):
        return PingRequest(version=obj.get("version", PROTOCOL_VERSION))
    return OpenRequest.deserialize(data)


@dataclass
class OpenResponse:
    success: bool
    forwarded_ports: list[int]
    error: str | None = None
    version: int = PROTOCOL_VERSION

    def serialize(self) -> bytes:
        return (json.dumps(asdict(self)) + "\n").encode(ENCODING)

    @staticmethod
    def deserialize(data: bytes) -> "OpenResponse":
        obj = json.loads(data.decode(ENCODING).strip())
        return OpenResponse(
            success=obj["success"],
            forwarded_ports=obj.get("forwarded_ports", []),
            error=obj.get("error"),
            version=obj.get("version", PROTOCOL_VERSION),
        )
