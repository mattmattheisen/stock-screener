import io
import json
from urllib.error import HTTPError

import pytest

from research.canslim_adaptive_entry_study.uw_rest_probe import fetch, archive


class FakeResponse:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stream.close()

    def read(self, n):
        return self.stream.read(n)


def test_probe_does_not_assume_volume_or_adjustments(tmp_path):
    def opener(req, timeout):
        assert req.get_header("Authorization") == "Bearer fake-secret"
        assert timeout == 30
        return FakeResponse(b'{"data":[{"date":"2026-11-10","open":"10","close":"11"}]}')
    raw = fetch("ANET", "fake-secret", opener=opener)
    result = archive("ANET", raw, tmp_path / "raw.json")
    assert result["records"] == 1
    assert result["has_underlying_volume_field"] is False
    assert result["price_adjustment_verified"] is False
    assert "fake-secret" not in json.dumps(result)


def test_archive_does_not_overwrite(tmp_path):
    path = tmp_path / "raw.json"
    archive("ANET", b'{"data":[]}', path)
    with pytest.raises(FileExistsError):
        archive("ANET", b'{"data":[]}', path)


def test_no_token_or_invalid_ticker():
    with pytest.raises(ValueError):
        fetch("ANET", "")
    with pytest.raises(ValueError):
        fetch("../BAD", "token")


def test_http_error_does_not_leak_token():
    def fail(req, timeout):
        raise HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        fetch("ANET", "sensitive-token", opener=fail)
    assert "sensitive-token" not in str(error.value)
