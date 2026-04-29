from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest
from src.utils.updater import _MAX_DOWNLOAD_BYTES, _require_https, download_file, download_file_if_changed

pytestmark = pytest.mark.unit

_URL = "https://example.com/file.ini"
_HTTP_URL = "http://example.com/file.ini"


# ---------------------------------------------------------------------------
# _require_https
# ---------------------------------------------------------------------------


def test_require_https_rejects_http():
    with pytest.raises(ValueError):
        _require_https(_HTTP_URL)


def test_require_https_rejects_empty():
    with pytest.raises(ValueError):
        _require_https("")


def test_require_https_accepts_https():
    _require_https(_URL)


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------


def test_download_file_rejects_non_https(tmp_path):
    with pytest.raises(ValueError):
        download_file(_HTTP_URL, tmp_path / "out.ini")


def _make_urlopen_mock(data: bytes):
    response = MagicMock()
    response.read.side_effect = [data, b""]
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=response)
    cm.__exit__ = MagicMock(return_value=False)
    mock_urlopen = MagicMock(return_value=cm)
    return mock_urlopen, response


def test_download_file_success(tmp_path):
    data = b"hello world"
    mock_urlopen, _ = _make_urlopen_mock(data)
    out = tmp_path / "out.ini"
    with patch("src.utils.updater.urlopen", mock_urlopen):
        result = download_file(_URL, out)
    assert isinstance(result, Path)
    assert out.read_bytes() == data


def test_download_file_size_cap(tmp_path):
    too_big = b"x" * (_MAX_DOWNLOAD_BYTES + 1)
    mock_urlopen, _ = _make_urlopen_mock(too_big)
    with patch("src.utils.updater.urlopen", mock_urlopen):
        with pytest.raises(ValueError, match="limit"):
            download_file(_URL, tmp_path / "out.ini")


def test_download_file_creates_directory(tmp_path):
    data = b"data"
    mock_urlopen, _ = _make_urlopen_mock(data)
    out = tmp_path / "subdir" / "file.txt"
    with patch("src.utils.updater.urlopen", mock_urlopen):
        download_file(_URL, out)
    assert out.exists()


def test_download_file_reraises_on_oserror(tmp_path):
    mock_urlopen = MagicMock(side_effect=OSError("disk full"))
    with patch("src.utils.updater.urlopen", mock_urlopen):
        with pytest.raises(OSError):
            download_file(_URL, tmp_path / "out.ini")


# ---------------------------------------------------------------------------
# download_file_if_changed
# ---------------------------------------------------------------------------


def _make_simple_urlopen_mock(data: bytes):
    response = MagicMock()
    response.read.return_value = data
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=response)
    cm.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=cm)


def test_download_file_if_changed_rejects_non_https(tmp_path):
    with pytest.raises(ValueError):
        download_file_if_changed(_HTTP_URL, tmp_path / "out.ini")


def test_download_file_if_changed_no_local_file(tmp_path):
    data = b"fresh data"
    mock_urlopen = _make_simple_urlopen_mock(data)
    out = tmp_path / "out.ini"
    with patch("src.utils.updater.urlopen", mock_urlopen) as m:
        result = download_file_if_changed(_URL, out)
    assert result is True
    assert out.read_bytes() == data
    call_args = m.call_args
    req = call_args[0][0]
    assert "If-Modified-Since" not in req.headers


def test_download_file_if_changed_with_local_file(tmp_path):
    data = b"updated data"
    mock_urlopen = _make_simple_urlopen_mock(data)
    out = tmp_path / "out.ini"
    out.write_bytes(b"old data")
    with patch("src.utils.updater.urlopen", mock_urlopen) as m:
        result = download_file_if_changed(_URL, out)
    assert result is True
    call_args = m.call_args
    req = call_args[0][0]
    assert "If-modified-since" in req.headers


def test_download_file_if_changed_304(tmp_path):
    out = tmp_path / "out.ini"
    out.write_bytes(b"old data")
    err = HTTPError(_URL, 304, "Not Modified", {}, None)
    mock_urlopen = MagicMock(side_effect=err)
    with patch("src.utils.updater.urlopen", mock_urlopen):
        result = download_file_if_changed(_URL, out)
    assert result is False
    assert out.read_bytes() == b"old data"


def test_download_file_if_changed_non_304_http_error(tmp_path):
    err = HTTPError(_URL, 500, "Internal Server Error", {}, None)
    mock_urlopen = MagicMock(side_effect=err)
    with patch("src.utils.updater.urlopen", mock_urlopen):
        with pytest.raises(HTTPError) as exc_info:
            download_file_if_changed(_URL, tmp_path / "out.ini")
    assert exc_info.value.code == 500


def test_download_file_if_changed_size_cap(tmp_path):
    too_big = b"x" * (_MAX_DOWNLOAD_BYTES + 2)
    mock_urlopen = _make_simple_urlopen_mock(too_big)
    with patch("src.utils.updater.urlopen", mock_urlopen):
        with pytest.raises(ValueError, match="limit"):
            download_file_if_changed(_URL, tmp_path / "out.ini")
