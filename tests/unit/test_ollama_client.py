from unittest.mock import Mock

import pytest
import requests

from remy.ollama_client import raise_for_ollama_status


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
