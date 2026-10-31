"""Runner: records for every attempt, errors included; HTTP transport
against a real local server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from provider_parity.probes import Checker, Probe
from provider_parity.runner import (
    ProviderConfig,
    RawResponse,
    Record,
    TransportError,
    http_transport,
    load_providers,
    load_records,
    run_probes,
    write_records,
)

PROBE = Probe("p1", "What is 17 + 25?", Checker("exact", expected="42"))
OFFICIAL = ProviderConfig("official", "https://example.invalid/v1", "model-x")
RESELLER = ProviderConfig("reseller", "https://example.invalid/v1", "model-x")


def fake_transport(provider, probe, timeout_s):
    text = "42" if provider.name == "official" else "41"
    return RawResponse(
        text=text, prompt_tokens=11, completion_tokens=1, latency_s=0.5
    )


def test_run_probes_applies_checker_per_provider():
    records = run_probes([PROBE], [OFFICIAL, RESELLER], transport=fake_transport)
    by_provider = {r.provider: r for r in records}
    assert by_provider["official"].success is True
    assert by_provider["reseller"].success is False
    assert by_provider["reseller"].error is None  # wrong answer != error
    assert by_provider["official"].prompt_tokens == 11


def test_run_probes_records_transport_errors():
    def boom(provider, probe, timeout_s):
        raise TransportError("HTTP 503 from official")

    records = run_probes([PROBE], [OFFICIAL], transport=boom)
    (record,) = records
    assert record.success is False
    assert "HTTP 503" in record.error


def test_records_roundtrip(tmp_path):
    records = [
        Record("official", "p1", True, 0.5, 11, 1, "42", None),
        Record("reseller", "p1", False, 0.0, None, None, "", "boom"),
    ]
    path = tmp_path / "run.jsonl"
    write_records(path, records)
    assert load_records(path) == records


def test_load_records_rejects_empty_and_bad(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no records"):
        load_records(path)
    path.write_text('{"provider": "x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing field"):
        load_records(path)


def test_load_providers(tmp_path):
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "name": "a",
                        "base_url": "https://a.example/v1/",
                        "model": "m",
                        "api_key_env": "A_KEY",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (provider,) = load_providers(path)
    assert provider.base_url == "https://a.example/v1"  # trailing slash stripped
    assert provider.api_key_env == "A_KEY"
    path.write_text(json.dumps({"providers": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty"):
        load_providers(path)


class _Handler(BaseHTTPRequestHandler):
    seen = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).seen = {
            "path": self.path,
            "body": body,
            "auth": self.headers.get("Authorization"),
        }
        if "/fail" in self.path:
            self.send_response(500)
            self.end_headers()
            return
        payload = {
            "choices": [{"message": {"content": "42"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1},
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


def test_http_transport_against_local_server(server, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sekrit")
    provider = ProviderConfig(
        "official", f"http://127.0.0.1:{server}/v1", "model-x",
        api_key_env="TEST_KEY",
    )
    raw = http_transport(provider, PROBE, 5.0)
    assert raw.text == "42"
    assert raw.prompt_tokens == 10
    assert raw.completion_tokens == 1
    assert raw.latency_s >= 0
    seen = _Handler.seen
    assert seen["path"] == "/v1/chat/completions"
    assert seen["body"]["model"] == "model-x"
    assert seen["body"]["temperature"] == 0
    assert seen["auth"] == "Bearer sekrit"


def test_http_transport_http_error_and_missing_key(server, monkeypatch):
    provider = ProviderConfig(
        "official", f"http://127.0.0.1:{server}/fail", "model-x"
    )
    with pytest.raises(TransportError, match="HTTP 500"):
        http_transport(provider, PROBE, 5.0)
    monkeypatch.delenv("NOPE_KEY", raising=False)
    provider = ProviderConfig(
        "official", f"http://127.0.0.1:{server}/v1", "model-x",
        api_key_env="NOPE_KEY",
    )
    with pytest.raises(TransportError, match="is not set"):
        http_transport(provider, PROBE, 5.0)


def test_http_transport_malformed_payload(server):
    class BadHandler(_Handler):
        def do_POST(self):
            data = json.dumps({"nope": True}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), BadHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        provider = ProviderConfig(
            "official", f"http://127.0.0.1:{httpd.server_address[1]}/v1", "m"
        )
        with pytest.raises(TransportError, match="malformed"):
            http_transport(provider, PROBE, 5.0)
    finally:
        httpd.shutdown()
