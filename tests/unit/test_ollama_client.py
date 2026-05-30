import json
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from remy.ollama_client import format_stats, raise_for_ollama_status, stream_request


def _streaming_post(lines):
    """Build a mock for requests.post used as a streaming context manager."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.iter_lines.return_value = iter(lines)
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return MagicMock(return_value=cm)


def _collect_callback():
    events: list[tuple[str, str]] = []
    return events, lambda kind, text: events.append((kind, text))


def test_raises_on_http_error():
    resp = Mock(spec=requests.Response)
    resp.status_code = 404
    resp.text = '{"error":"model not found"}'
    resp.raise_for_status.side_effect = requests.HTTPError("404 Client Error")

    with pytest.raises(requests.HTTPError):
        raise_for_ollama_status(resp, model="missing-model", endpoint="/api/chat")

    resp.raise_for_status.assert_called_once()


def test_passes_on_success():
    resp = Mock(spec=requests.Response)
    resp.raise_for_status.return_value = None

    raise_for_ollama_status(resp, model="ok-model", endpoint="/api/generate")

    resp.raise_for_status.assert_called_once()


class TestFormatStats:
    def test_converts_nanoseconds_and_tokens(self):
        chunk = {
            "total_duration": 2_500_000_000,
            "eval_duration": 1_000_000_000,
            "prompt_eval_count": 12,
            "eval_count": 48,
        }
        stats = format_stats(chunk)
        assert "total=2.50s" in stats
        assert "eval=1.00s" in stats
        assert "prompt_tokens=12" in stats
        assert "output_tokens=48" in stats

    def test_ignores_missing_and_non_int_fields(self):
        assert format_stats({}) == ""
        assert format_stats({"total_duration": "fast"}) == ""


class TestStreamRequest:
    def test_accumulates_generate_response_chunks(self):
        lines = [
            json.dumps({"response": "Tom"}),
            json.dumps({"response": "ato"}),
            json.dumps({"done": True, "total_duration": 1_000_000_000}),
        ]
        events, cb = _collect_callback()
        with patch("remy.ollama_client.requests.post", _streaming_post(lines)):
            result = stream_request("/api/generate", {"model": "m"}, cb, timeout=5)

        assert result == "Tomato"
        assert ("response", "Tom") in events
        assert ("response", "ato") in events
        assert any(kind == "stats" and "total=1.00s" in text for kind, text in events)

    def test_handles_chat_message_content_shape(self):
        lines = [
            json.dumps({"message": {"content": "Step 1"}}),
            json.dumps({"message": {"content": " done"}, "done": True}),
        ]
        events, cb = _collect_callback()
        with patch("remy.ollama_client.requests.post", _streaming_post(lines)):
            result = stream_request("/api/chat", {"model": "m"}, cb, timeout=5)

        assert result == "Step 1 done"

    def test_emits_thinking_chunks(self):
        lines = [
            json.dumps({"thinking": "hmm"}),
            json.dumps({"response": "answer", "done": True}),
        ]
        events, cb = _collect_callback()
        with patch("remy.ollama_client.requests.post", _streaming_post(lines)):
            stream_request("/api/generate", {"model": "m"}, cb, timeout=5)

        assert ("thinking", "hmm") in events

    def test_skips_unparseable_lines(self):
        lines = ["", "not-json", json.dumps({"response": "ok", "done": True})]
        events, cb = _collect_callback()
        with patch("remy.ollama_client.requests.post", _streaming_post(lines)):
            result = stream_request("/api/generate", {"model": "m"}, cb, timeout=5)

        assert result == "ok"

    def test_raises_on_error_chunk(self):
        lines = [json.dumps({"error": "out of memory"})]
        _events, cb = _collect_callback()
        with (
            patch("remy.ollama_client.requests.post", _streaming_post(lines)),
            pytest.raises(RuntimeError, match="out of memory"),
        ):
            stream_request("/api/chat", {"model": "m"}, cb, timeout=5)
