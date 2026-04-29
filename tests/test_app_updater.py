"""Pure-function tests for utils.app_updater.

Network-hitting paths (AppUpdateCheckWorker.run) aren't covered here —
tested manually against real GitHub. These cover the version parsing and
comparison logic, which is where silent regressions would hurt (we'd either
stop nagging when we should, or start nagging on valid data).
"""

import pytest
from src.utils.app_updater import is_newer, parse_version


@pytest.mark.unit
class TestParseVersion:
    def test_plain(self):
        assert parse_version("0.9.3") == (0, 9, 3)

    def test_v_prefix(self):
        assert parse_version("v0.9.3") == (0, 9, 3)

    def test_uppercase_v_prefix(self):
        assert parse_version("V0.9.3") == (0, 9, 3)

    def test_surrounding_whitespace(self):
        assert parse_version("  0.9.3  ") == (0, 9, 3)

    def test_missing_patch(self):
        assert parse_version("0.9") == (0, 9, 0)

    def test_extra_segments_ignored(self):
        assert parse_version("1.2.3.4") == (1, 2, 3)

    def test_non_numeric(self):
        assert parse_version("garbage") is None

    def test_empty(self):
        assert parse_version("") is None

    def test_none_safe(self):
        # Pass a string that hits the len<2 branch without splitting.
        assert parse_version("0") is None

    def test_partial_numeric(self):
        # Mixed alphanumeric should fail rather than partially parse.
        assert parse_version("0.9.3-rc1") is None

    def test_large_numbers(self):
        assert parse_version("v100.200.300") == (100, 200, 300)


@pytest.mark.unit
class TestIsNewer:
    def test_strictly_newer_patch(self):
        assert is_newer("0.9.4", "0.9.3") is True

    def test_strictly_newer_minor(self):
        assert is_newer("0.10.0", "0.9.9") is True

    def test_strictly_newer_major(self):
        assert is_newer("1.0.0", "0.9.9") is True

    def test_equal(self):
        assert is_newer("0.9.3", "0.9.3") is False

    def test_older(self):
        assert is_newer("0.9.2", "0.9.3") is False

    def test_v_prefix_both(self):
        assert is_newer("v0.9.4", "v0.9.3") is True

    def test_v_prefix_one_side(self):
        assert is_newer("v0.9.4", "0.9.3") is True
        assert is_newer("0.9.4", "v0.9.3") is True

    def test_unparseable_latest_fails_safe(self):
        # When we can't read the remote tag, don't nag — behave as
        # "nothing newer available."
        assert is_newer("garbage", "0.9.3") is False

    def test_unparseable_current_fails_safe(self):
        assert is_newer("0.9.4", "garbage") is False

    def test_both_unparseable(self):
        assert is_newer("garbage", "other-garbage") is False

    def test_empty_strings(self):
        assert is_newer("", "") is False
        assert is_newer("", "0.9.3") is False
        assert is_newer("0.9.3", "") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
