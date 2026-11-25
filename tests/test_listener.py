import asyncio

import pytest

from ssh_open import listener as listener_module
from ssh_open.listener import Listener, extract_localhost_ports
from ssh_open.protocol import OpenRequest, OpenResponse, PingRequest


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:8080/", [8080]),
        ("http://127.0.0.1:3000/cb", [3000]),
        ("https://auth.example.com/?redirect_uri=http://localhost:8123/cb", [8123]),
        ("http://localhost/", []),
        ("https://example.com:8443/", []),
        ("http://localhost:99999/", []),  # invalid port must not raise
    ],
)
def test_extract_localhost_ports(url, expected):
    assert extract_localhost_ports(url) == expected


async def _send(port: int, data: bytes) -> OpenResponse:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(data)
    await writer.drain()
    raw = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return OpenResponse.deserialize(raw)


async def _roundtrip(data: bytes) -> tuple[Listener, OpenResponse]:
    listener = Listener(host="example-host", port=0)
    await listener.start()
    task = asyncio.create_task(listener.serve())
    try:
        return listener, await _send(listener.port, data)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.fixture
def opened(monkeypatch):
    urls: list[str] = []
    monkeypatch.setattr(listener_module, "open_url_on_host", urls.append)
    return urls


def test_listener_opens_url(opened):
    url = "https://example.com/"
    listener, response = asyncio.run(_roundtrip(OpenRequest(url=url).serialize()))

    assert listener.port != 0
    assert response.success is True
    assert response.forwarded_ports == []
    assert opened == [url]


def test_listener_rejects_garbage(opened):
    _, response = asyncio.run(_roundtrip(b"not json\n"))

    assert response.success is False
    assert response.error
    assert opened == []


def test_listener_answers_ping(opened):
    _, response = asyncio.run(_roundtrip(PingRequest().serialize()))

    # find-sock greps for this exact substring.
    assert b'"success": true' in response.serialize()
    assert response.success is True
    assert opened == []
