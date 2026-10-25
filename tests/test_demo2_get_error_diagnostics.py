"""Unexpected GET failures expose a safe API error and a private stack only."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from src.rehab_affect import scenario_lab_server as api


@pytest.mark.parametrize("failure_at, error_type, os_code", [
    ("repository", "PermissionError", "errno=13"),
    ("media_open", "FileNotFoundError", "errno=2"),
])
def test_get_audio_failure_logs_private_stack_without_request_data(
    tmp_path, monkeypatch, capsys, failure_at, error_type, os_code
):
    secrets = ("private-cookie-value", "private-query-value", "private-body-value")
    private_file = tmp_path / "private-audio-name.wav"

    class Store:
        def account_video_media(self, token, task_id, asset):
            assert token == secrets[0] and task_id == secrets[1] and asset == "audio"
            if failure_at == "repository":
                raise PermissionError(13, ":".join(secrets), str(private_file))
            return private_file, "audio/wav"

    monkeypatch.setattr(api, "get_demo2_student_store", Store)
    handler = object.__new__(api.create_handler(scenario_dir=tmp_path, model_path=tmp_path, policy_name="rule"))
    handler._require_account = lambda: {"role": "school_uploader"}
    handler._session_cookie_token = lambda: secrets[0]
    responses = []
    handler._send_json_error = lambda status, code, message: responses.append((status, code, message))
    handler._handle_demo2_api_get(urlparse("/api/v1/demo2/upload/media?id=" + secrets[1] + "&asset=audio"))

    assert responses == [(500, "internal_error", "服务器暂时无法处理请求，请稍后重试")]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert error_type in captured.err and os_code in captured.err and "pid=" in captured.err
    assert "_handle_demo2_api_get" in captured.err
    assert ("account_video_media" if failure_at == "repository" else "_send_media") in captured.err
    for secret in (*secrets, "private-audio-name.wav", "/api/v1/demo2/upload/media?id="):
        assert secret not in captured.err
        assert secret not in str(responses)


def test_expected_unavailable_media_stays_404_without_unexpected_error_log(tmp_path, monkeypatch, capsys):
    class Store:
        def account_video_media(self, *args, **kwargs):
            raise ValueError("媒体文件不存在")

    monkeypatch.setattr(api, "get_demo2_student_store", Store)
    handler = object.__new__(api.create_handler(scenario_dir=tmp_path, model_path=tmp_path, policy_name="rule"))
    handler._require_account = lambda: {"role": "school_uploader"}
    handler._session_cookie_token = lambda: "test-token"
    responses = []
    handler._send_json_error = lambda status, code, message: responses.append((status, code))
    handler._handle_demo2_api_get(urlparse("/api/v1/demo2/upload/media?id=test-task&asset=audio"))
    assert responses == [(404, "media_unavailable")]
    assert capsys.readouterr().err == ""
