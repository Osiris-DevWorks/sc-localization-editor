"""Tests for tools_manager — download, presence check, and directory resolution."""

import io
import zipfile
from unittest.mock import patch

import pytest
from src.utils.tools_manager import (
    TOOLS_VERSION,
    download_tools,
    get_tools_dir,
    tools_are_present,
)


@pytest.mark.unit
class TestGetToolsDir:
    def test_contains_app_name(self):
        d = get_tools_dir()
        assert "Open Strings" in str(d)

    def test_contains_version(self):
        d = get_tools_dir()
        assert TOOLS_VERSION in str(d)

    def test_uses_appdata_env(self, tmp_path):
        with patch.dict("os.environ", {"APPDATA": str(tmp_path)}):
            d = get_tools_dir()
        assert str(tmp_path) in str(d)

    def test_falls_back_when_appdata_missing(self):
        env = {"APPDATA": ""}
        with patch.dict("os.environ", env):
            import os

            os.environ.pop("APPDATA", None)
            d = get_tools_dir()
        assert "Open Strings" in str(d)


@pytest.mark.unit
class TestToolsArePresent:
    def test_false_when_directory_empty(self, tmp_path):
        with patch("src.utils.tools_manager.get_tools_dir", return_value=tmp_path):
            assert not tools_are_present()

    def test_false_when_only_unp4k_exists(self, tmp_path):
        (tmp_path / "unp4k.exe").write_text("x")
        with patch("src.utils.tools_manager.get_tools_dir", return_value=tmp_path):
            assert not tools_are_present()

    def test_false_when_only_unforge_exists(self, tmp_path):
        (tmp_path / "unforge.cli.exe").write_text("x")
        with patch("src.utils.tools_manager.get_tools_dir", return_value=tmp_path):
            assert not tools_are_present()

    def test_true_when_both_exes_exist(self, tmp_path):
        (tmp_path / "unp4k.exe").write_text("x")
        (tmp_path / "unforge.cli.exe").write_text("x")
        with patch("src.utils.tools_manager.get_tools_dir", return_value=tmp_path):
            assert tools_are_present()


def _make_zip(*entries: tuple[str, str]) -> bytes:
    """Build an in-memory zip with the given (name, content) entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return buf.getvalue()


class _FakeResponse:
    """Minimal urllib response stand-in."""

    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n: int) -> bytes:
        return self._stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


@pytest.mark.unit
class TestDownloadTools:
    def _patch_urlopen(self, responses: list[bytes]):
        """Return a context-manager patch that serves responses in order."""
        call_iter = iter(responses)

        def fake_urlopen(url):
            return _FakeResponse(next(call_iter))

        return patch("urllib.request.urlopen", side_effect=fake_urlopen)

    def test_extracts_unp4k_and_unforge_exes(self, tmp_path):
        unp4k_zip = _make_zip(("unp4k.exe", "bin"), ("x64/libzstd.dll", "dll"))
        unforge_zip = _make_zip(("unforge.cli.exe", "bin"), ("Zstd.Net.dll", "dll"))

        with patch("src.utils.tools_manager.get_tools_dir", return_value=tmp_path):
            with self._patch_urlopen([unp4k_zip, unforge_zip]):
                download_tools()

        assert (tmp_path / "unp4k.exe").exists()
        assert (tmp_path / "unforge.cli.exe").exists()

    def test_supporting_files_also_extracted(self, tmp_path):
        unp4k_zip = _make_zip(("unp4k.exe", "b"), ("x64/libzstd.dll", "d"), ("x86/libzstd.dll", "d"))
        unforge_zip = _make_zip(
            ("unforge.cli.exe", "b"),
            ("ICSharpCode.SharpZipLib.dll", "d"),
            ("Zstd.Net.dll", "d"),
        )

        with patch("src.utils.tools_manager.get_tools_dir", return_value=tmp_path):
            with self._patch_urlopen([unp4k_zip, unforge_zip]):
                download_tools()

        assert (tmp_path / "x64" / "libzstd.dll").exists()
        assert (tmp_path / "Zstd.Net.dll").exists()

    def test_progress_callback_called(self, tmp_path):
        unp4k_zip = _make_zip(("unp4k.exe", "b"))
        unforge_zip = _make_zip(("unforge.cli.exe", "b"))
        messages = []

        with patch("src.utils.tools_manager.get_tools_dir", return_value=tmp_path):
            with self._patch_urlopen([unp4k_zip, unforge_zip]):
                download_tools(progress_callback=messages.append)

        assert any("unp4k" in m for m in messages)
        assert any("unforge" in m for m in messages)

    def test_cancel_event_aborts_before_second_download(self, tmp_path):
        import threading

        unp4k_zip = _make_zip(("unp4k.exe", "b"))
        cancel = threading.Event()

        call_count = 0

        def fake_urlopen(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                cancel.set()  # cancel after first zip starts
            return _FakeResponse(unp4k_zip)

        with patch("src.utils.tools_manager.get_tools_dir", return_value=tmp_path):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                with pytest.raises(RuntimeError, match="cancelled"):
                    download_tools(cancel_event=cancel)

        # Should not have attempted the second download
        assert call_count == 1

    def test_exe_in_subdirectory_promoted_to_flat_path(self, tmp_path):
        # Reproduces a zip layout where the exe is nested inside a subdirectory
        # rather than placed at the archive root.
        unp4k_zip = _make_zip(("unp4k.exe", "bin"))
        unforge_zip = _make_zip(("unforge-win-x64-v4.0.83/unforge.cli.exe", "bin"))

        with patch("src.utils.tools_manager.get_tools_dir", return_value=tmp_path):
            with self._patch_urlopen([unp4k_zip, unforge_zip]):
                download_tools()

        # Both exes must be at the flat expected location after promotion
        assert (tmp_path / "unp4k.exe").exists()
        assert (tmp_path / "unforge.cli.exe").exists()

    def test_tools_dir_created_if_missing(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        unp4k_zip = _make_zip(("unp4k.exe", "b"))
        unforge_zip = _make_zip(("unforge.cli.exe", "b"))

        with patch("src.utils.tools_manager.get_tools_dir", return_value=nested):
            with self._patch_urlopen([unp4k_zip, unforge_zip]):
                download_tools()

        assert nested.is_dir()


@pytest.mark.unit
class TestSafeExtractall:
    def test_normal_entries_extracted(self, tmp_path):
        from src.utils import tools_manager as _tm

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("unp4k.exe", "bin")
            zf.writestr("x64/libzstd.dll", "dll")
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            _tm._safe_extractall(zf, tmp_path)
        assert (tmp_path / "unp4k.exe").exists()
        assert (tmp_path / "x64" / "libzstd.dll").exists()

    def test_path_traversal_entry_rejected(self, tmp_path):
        from src.utils import tools_manager as _tm

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.exe", "bad")
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            with pytest.raises(ValueError, match="path traversal"):
                _tm._safe_extractall(zf, tmp_path)

    def test_absolute_path_entry_rejected(self, tmp_path):
        from src.utils import tools_manager as _tm

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/passwd", "bad")
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            with pytest.raises(ValueError, match="path traversal"):
                _tm._safe_extractall(zf, tmp_path)
