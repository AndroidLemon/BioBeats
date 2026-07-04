# Tests for the GUI command center: the pure request validation, OSC send
# forwarding, /rt2/status ingestion, and the real HTTP server end-to-end on an
# ephemeral port (stdlib only — no browser, no network beyond loopback HTTP).

import json
import threading
import urllib.error
import urllib.request

import pytest

from src.gui.command_center import CommandCenter, parse_send
from stubs.osc_client_stub import StubOSCClient
from stubs.osc_server_stub import StubOSCServer


# --- parse_send (pure) -------------------------------------------------------


def test_parse_send_accepts_rt2_addresses_and_scalars():
    assert parse_send(b'{"address": "/rt2/prompt", "value": "dub"}') == (
        "/rt2/prompt",
        "dub",
    )
    assert parse_send(b'{"address": "/rt2/intensity", "value": 0.5}') == (
        "/rt2/intensity",
        0.5,
    )
    assert parse_send(b'{"address": "/rt2/note/on", "value": 60}') == (
        "/rt2/note/on",
        60,
    )


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"address": "/rt2/prompt"}',  # missing value
        b'{"value": 1}',  # missing address
        b'{"address": "/other/prompt", "value": 1}',  # outside /rt2/*
        b'{"address": "/rt2/prompt", "value": [1, 2]}',  # non-scalar
        b'{"address": "/rt2/prompt", "value": true}',  # bool is not an OSC scalar here
        b'{"address": 5, "value": 1}',  # non-string address
    ],
)
def test_parse_send_rejects_bad_requests(body):
    with pytest.raises(ValueError):
        parse_send(body)


# --- status ingestion --------------------------------------------------------


def test_status_ingestion_via_osc_server():
    center = CommandCenter(StubOSCClient())
    server = StubOSCServer()
    center.attach_status_server(server)
    server.dispatch("/rt2/status", json.dumps({"state": "STREAMING", "chunk": 3}))
    latest = center.latest_status()
    assert latest["status"] == {"state": "STREAMING", "chunk": 3}
    assert latest["age_seconds"] >= 0


def test_status_starts_empty_and_ignores_garbage():
    center = CommandCenter(StubOSCClient())
    assert center.latest_status()["status"] is None
    center.handle_status("/rt2/status", "{not json")
    assert center.latest_status()["status"] is None
    center.handle_status("/rt2/status")  # no args
    assert center.latest_status()["status"] is None


# --- HTTP end-to-end ---------------------------------------------------------


@pytest.fixture()
def http_center():
    sender = StubOSCClient()
    center = CommandCenter(sender)
    httpd = center.make_http_server("127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield center, sender, base
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _post(base, path, payload):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read() or b"{}")


def test_index_page_is_served(http_center):
    _, _, base = http_center
    with urllib.request.urlopen(base + "/", timeout=5) as response:
        assert response.status == 200
        body = response.read().decode()
    assert "BioBeats" in body


def test_post_send_forwards_over_osc(http_center):
    _, sender, base = http_center
    status, _ = _post(base, "/api/send", {"address": "/rt2/prompt", "value": "dub"})
    assert status == 200
    status, _ = _post(base, "/api/send", {"address": "/rt2/note/on", "value": 60})
    assert status == 200
    assert sender.sent == [("/rt2/prompt", "dub"), ("/rt2/note/on", 60)]


def test_post_send_rejects_bad_payload_with_400(http_center):
    _, sender, base = http_center
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(base, "/api/send", {"address": "/hack/it", "value": 1})
    assert excinfo.value.code == 400
    assert sender.sent == []


def test_get_status_returns_latest(http_center):
    center, _, base = http_center
    center.handle_status("/rt2/status", json.dumps({"state": "STREAMING"}))
    with urllib.request.urlopen(base + "/api/status", timeout=5) as response:
        payload = json.loads(response.read())
    assert payload["status"] == {"state": "STREAMING"}


def test_unknown_paths_are_404(http_center):
    _, _, base = http_center
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(http_center[2] + "/nope", timeout=5)
    assert excinfo.value.code == 404


# --- hostile / malformed HTTP ------------------------------------------------


def test_parse_send_rejects_nonfinite_numbers():
    # Python's json.loads accepts NaN/Infinity; NaN slips through clamps as the
    # MAXIMUM (min(hi, nan) returns hi), slamming knobs to extremes. Reject.
    for bad in (b"NaN", b"Infinity", b"-Infinity", b"1e999"):
        with pytest.raises(ValueError):
            parse_send(b'{"address": "/rt2/temperature", "value": ' + bad + b"}")


def _raw_post(base, path, body: bytes, headers: dict):
    request = urllib.request.Request(
        base + path, data=body, headers=headers, method="POST"
    )
    return urllib.request.urlopen(request, timeout=5)


def test_post_without_json_content_type_is_rejected(http_center):
    # Forces browsers to CORS-preflight /api/send: a hostile page's "simple"
    # text/plain POST must not be able to drive the engine.
    _, sender, base = http_center
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _raw_post(
            base,
            "/api/send",
            b'{"address": "/rt2/stop", "value": 1}',
            {"Content-Type": "text/plain"},
        )
    assert excinfo.value.code == 415
    assert sender.sent == []


def test_bad_content_length_is_a_400_not_a_crash(http_center):
    import http.client

    _, sender, base = http_center
    host, port = base.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.putrequest("POST", "/api/send")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "not-a-number")
    conn.endheaders()
    response = conn.getresponse()
    assert response.status == 400
    conn.close()
    assert sender.sent == []


def test_oversized_body_is_rejected(http_center):
    _, sender, base = http_center
    huge = b'{"address": "/rt2/prompt", "value": "' + b"x" * 100_000 + b'"}'
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _raw_post(base, "/api/send", huge, {"Content-Type": "application/json"})
    assert excinfo.value.code == 413
    assert sender.sent == []
