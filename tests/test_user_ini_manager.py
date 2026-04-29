"""Tests for src.utils.user_ini_manager."""

import pytest
from src.models.string_model import StringEntry
from src.utils.user_ini_manager import generate_user_ini_from_diff, save_user_ini, save_user_ini_dict

pytestmark = pytest.mark.unit


class TestSaveUserIni:
    def test_writes_only_modified_entries(self, tmp_path):
        path = tmp_path / "user.ini"
        entries = [
            StringEntry(key="key1", source_file="global", original_value="v1", custom_value="custom1"),
            StringEntry(key="key2", source_file="global", original_value="v2", custom_value=""),
        ]
        count = save_user_ini(entries, path)
        assert count == 1
        content = path.read_text(encoding="utf-8")
        assert "key1=custom1" in content
        assert "key2" not in content

    def test_creates_parent_directories(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "user.ini"
        entries = [StringEntry(key="k", source_file="global", original_value="v", custom_value="new")]
        save_user_ini(entries, deep_path)
        assert deep_path.exists()

    def test_returns_count_of_written_entries(self, tmp_path):
        path = tmp_path / "user.ini"
        entries = [
            StringEntry(key="k1", source_file="global", original_value="v1", custom_value="c1"),
            StringEntry(key="k2", source_file="global", original_value="v2", custom_value="c2"),
        ]
        count = save_user_ini(entries, path)
        assert count == 2

    def test_no_modified_entries_writes_empty_file(self, tmp_path):
        path = tmp_path / "user.ini"
        entries = [StringEntry(key="k", source_file="global", original_value="v", custom_value="")]
        count = save_user_ini(entries, path)
        assert count == 0
        assert path.read_text(encoding="utf-8") == ""


class TestSaveUserIniDict:
    def test_writes_all_keys(self, tmp_path):
        path = tmp_path / "user.ini"
        data = {"k1": "v1", "k2": "v2"}
        count = save_user_ini_dict(data, path)
        assert count == 2
        content = path.read_text(encoding="utf-8")
        assert "k1=v1" in content
        assert "k2=v2" in content

    def test_empty_dict_writes_empty_file(self, tmp_path):
        path = tmp_path / "user.ini"
        count = save_user_ini_dict({}, path)
        assert count == 0
        assert path.read_text(encoding="utf-8") == ""

    def test_creates_parent_directories(self, tmp_path):
        deep_path = tmp_path / "x" / "y" / "user.ini"
        save_user_ini_dict({"k": "v"}, deep_path)
        assert deep_path.exists()


class TestGenerateUserIniFromDiff:
    def test_returns_zero_when_reference_missing(self, tmp_path):
        result = generate_user_ini_from_diff(
            tmp_path / "ref.ini",
            tmp_path / "current.ini",
            tmp_path / "user.ini",
        )
        assert result == 0

    def test_returns_zero_when_current_missing(self, tmp_path):
        ref = tmp_path / "ref.ini"
        ref.write_text("k=v\n", encoding="utf-8")
        result = generate_user_ini_from_diff(ref, tmp_path / "current.ini", tmp_path / "user.ini")
        assert result == 0

    def test_returns_zero_when_user_ini_already_exists(self, tmp_path):
        ref = tmp_path / "ref.ini"
        ref.write_text("k=v\n", encoding="utf-8")
        current = tmp_path / "current.ini"
        current.write_text("k=changed\n", encoding="utf-8")
        user_ini = tmp_path / "user.ini"
        user_ini.write_text("existing\n", encoding="utf-8")
        result = generate_user_ini_from_diff(ref, current, user_ini)
        assert result == 0

    def test_writes_diff_entries(self, tmp_path):
        ref = tmp_path / "ref.ini"
        ref.write_text("k1=v1\nk2=v2\n", encoding="utf-8")
        current = tmp_path / "current.ini"
        current.write_text("k1=v1\nk2=changed\n", encoding="utf-8")
        user_ini = tmp_path / "user.ini"
        result = generate_user_ini_from_diff(ref, current, user_ini)
        assert result == 1
        content = user_ini.read_text(encoding="utf-8")
        assert "k2=changed" in content

    def test_returns_zero_when_no_diff(self, tmp_path):
        ref = tmp_path / "ref.ini"
        ref.write_text("k=v\n", encoding="utf-8")
        current = tmp_path / "current.ini"
        current.write_text("k=v\n", encoding="utf-8")
        user_ini = tmp_path / "user.ini"
        result = generate_user_ini_from_diff(ref, current, user_ini)
        assert result == 0
        assert not user_ini.exists()

    def test_new_key_in_current_included_in_diff(self, tmp_path):
        ref = tmp_path / "ref.ini"
        ref.write_text("k1=v1\n", encoding="utf-8")
        current = tmp_path / "current.ini"
        current.write_text("k1=v1\nnew_key=brand_new\n", encoding="utf-8")
        user_ini = tmp_path / "user.ini"
        result = generate_user_ini_from_diff(ref, current, user_ini)
        assert result == 1
        assert "new_key=brand_new" in user_ini.read_text(encoding="utf-8")
