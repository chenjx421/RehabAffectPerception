"""Offline transport checks; these tests never call the paid provider."""
import importlib.util
from pathlib import Path
from unittest.mock import patch, Mock

import requests

spec = importlib.util.spec_from_file_location(
    "gateway_probe", Path(__file__).resolve().parents[1] / "scripts/probe_demo3_multimodal.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_transport_retains_tls_and_disables_redirects():
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": "43"}}], "usage": {"total_tokens": 10}}
    with patch.object(probe.requests, "post", return_value=response) as post:
        result = probe.call("test-secret", "test-model", "test")
    assert result["reply"] == "43"
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs.get("verify", True) is True
    assert post.call_args.kwargs["json"]["max_tokens"] == 768
    assert "test-secret" not in str(result)


def test_http_error_never_echoes_provider_body():
    response = Mock(status_code=400, text="sensitive-echo")
    with patch.object(probe.requests, "post", return_value=response):
        result = probe.call("secret", "model", "input")
    assert result["error"] == "provider_http_error"
    assert "sensitive" not in str(result)
    response.json.assert_not_called()


def test_tls_error_fails_closed():
    with patch.object(probe.requests, "post", side_effect=requests.exceptions.SSLError("secret")):
        assert probe.call("secret", "model", "input") == {"error": "tls_verification_failed"}


def test_timeout_is_not_retried():
    with patch.object(probe.requests, "post", side_effect=requests.exceptions.Timeout()) as post:
        assert probe.call("secret", "model", "input") == {"error": "timeout"}
    assert post.call_count == 1


def test_inline_encodes_bytes():
    assert probe.inline(b"abc", "image/png") == "data:image/png;base64,YWJj"


def test_error_hints_are_categories_not_raw_payload():
    response = Mock(status_code=400, text='{"error":{"message":"invalid content"}}')
    with patch.object(probe.requests, "post", return_value=response):
        result = probe.call("secret", "model", "input")
    assert result["error_hints"] == ["invalid_parameter"]
    assert "message" not in result
