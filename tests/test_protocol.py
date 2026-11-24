import json

import pytest

from ssh_open.protocol import OpenRequest, OpenResponse


def test_request_round_trip():
    request = OpenRequest(url="https://example.com/?a=1")
    data = request.serialize()

    assert data.endswith(b"\n")
    assert OpenRequest.deserialize(data) == request


def test_request_rejects_unknown_version():
    data = json.dumps({"url": "https://example.com", "version": 2}).encode()

    with pytest.raises(ValueError, match="version"):
        OpenRequest.deserialize(data)


def test_response_round_trip():
    response = OpenResponse(success=False, forwarded_ports=[8080], error="boom")

    assert OpenResponse.deserialize(response.serialize()) == response
