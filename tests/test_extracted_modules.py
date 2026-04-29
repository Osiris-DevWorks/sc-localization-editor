"""Tests for the extracted utility modules: applied_file_validator, entry_filter, markdown_renderer."""

import pytest
from src.gui.markdown_renderer import (
    _convert_markdown_inline,
    _convert_markdown_links,
    create_anchor_id,
    markdown_to_html,
)
from src.models.string_model import StringEntry
from src.utils.applied_file_validator import validate_applied_file
from src.utils.entry_filter import filter_entry_indices

# ---------------------------------------------------------------------------
# applied_file_validator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateAppliedFile:
    def _make_entry(self, key: str, value: str, tmp_path, filename: str) -> None:
        f = tmp_path / filename
        f.write_text(f"{key}={value}\n", encoding="utf-8")

    def test_identical_keys_returns_empty(self, tmp_path):
        stock = {"k1", "k2"}
        written = tmp_path / "written.ini"
        written.write_text("k1=a\nk2=b\n", encoding="utf-8")
        assert validate_applied_file(written, tmp_path, stock_keys=stock) == ""

    def test_missing_key_returns_message(self, tmp_path):
        stock = {"k1", "k2", "k3"}
        written = tmp_path / "written.ini"
        written.write_text("k1=a\nk2=b\n", encoding="utf-8")
        result = validate_applied_file(written, tmp_path, stock_keys=stock)
        assert "k3" in result
        assert "missing" in result.lower()

    def test_extra_keys_reported(self, tmp_path):
        stock = {"k1"}
        written = tmp_path / "written.ini"
        written.write_text("k1=a\nextra_key=x\n", encoding="utf-8")
        result = validate_applied_file(written, tmp_path, stock_keys=stock)
        assert "extra_key" in result

    def test_no_cache_without_stock_keys_skips(self, tmp_path):
        written = tmp_path / "written.ini"
        written.write_text("k=v\n", encoding="utf-8")
        # No base.ini in tmp_path — should skip silently
        result = validate_applied_file(written, tmp_path, stock_keys=None)
        assert result == ""

    def test_loads_stock_keys_from_cache(self, tmp_path):
        (tmp_path / "base.ini").write_text("k1=a\nk2=b\n", encoding="utf-8")
        written = tmp_path / "written.ini"
        written.write_text("k1=x\n", encoding="utf-8")  # k2 missing
        result = validate_applied_file(written, tmp_path)
        assert "k2" in result

    def test_values_may_differ(self, tmp_path):
        stock = {"k1"}
        written = tmp_path / "written.ini"
        written.write_text("k1=different_value\n", encoding="utf-8")
        assert validate_applied_file(written, tmp_path, stock_keys=stock) == ""

    def test_missing_written_file_returns_warning(self, tmp_path):
        # A non-existent written file yields 0 written keys → every stock key "missing"
        result = validate_applied_file(tmp_path / "nonexistent.ini", tmp_path, stock_keys={"k"})
        assert "missing" in result.lower()


# ---------------------------------------------------------------------------
# entry_filter
# ---------------------------------------------------------------------------


def _make_entry(key: str, category: str, status: str, custom: str = "", original: str = "") -> StringEntry:
    return StringEntry(
        key=key,
        source_file="global",
        category=category,
        original_value=original,
        custom_value=custom,
        status=status,
    )


@pytest.mark.unit
class TestFilterEntryIndices:
    def _no_filters(self):
        return dict(
            column_filters=[""] * 7,
            category_filter="All",
            status_filter="All",
            hide_unmodified=False,
            favorites_only=False,
            favorite_prefix="★",
        )

    def test_no_filter_returns_all(self):
        entries = [_make_entry("k1", "Ships", "Unmodified"), _make_entry("k2", "Gear", "Modified")]
        result = filter_entry_indices(entries, {}, **self._no_filters())
        assert result == [0, 1]

    def test_category_filter(self):
        entries = [_make_entry("k1", "Ships", "Unmodified"), _make_entry("k2", "Gear", "Modified")]
        result = filter_entry_indices(entries, {}, **{**self._no_filters(), "category_filter": "Ships"})
        assert result == [0]

    def test_status_filter(self):
        entries = [_make_entry("k1", "Ships", "Unmodified"), _make_entry("k2", "Gear", "Modified")]
        result = filter_entry_indices(entries, {}, **{**self._no_filters(), "status_filter": "Modified"})
        assert result == [1]

    def test_hide_unmodified(self):
        entries = [_make_entry("k1", "Ships", "Unmodified"), _make_entry("k2", "Gear", "Modified")]
        result = filter_entry_indices(entries, {}, **{**self._no_filters(), "hide_unmodified": True})
        assert result == [1]

    def test_favorites_only(self):
        entries = [
            _make_entry("k1", "Ships", "Modified", custom="★Cutlass"),
            _make_entry("k2", "Ships", "Unmodified"),
        ]
        result = filter_entry_indices(entries, {}, **{**self._no_filters(), "favorites_only": True})
        assert result == [0]

    def test_column_filter_key(self):
        entries = [
            _make_entry("vehicle_NameHawk", "Ships", "Unmodified"),
            _make_entry("item_NameShield", "Gear", "Unmodified"),
        ]
        filters = list([""] * 7)
        filters[1] = "hawk"  # column 1 = Key
        result = filter_entry_indices(entries, {}, **{**self._no_filters(), "column_filters": filters})
        assert result == [0]

    def test_column_filter_custom_value(self):
        entries = [
            _make_entry("k1", "Ships", "Modified", custom="my custom"),
            _make_entry("k2", "Ships", "Unmodified"),
        ]
        filters = list([""] * 7)
        filters[5] = "custom"  # column 5 = Custom Value
        result = filter_entry_indices(entries, {}, **{**self._no_filters(), "column_filters": filters})
        assert result == [0]

    def test_empty_entries_returns_empty(self):
        assert filter_entry_indices([], {}, **self._no_filters()) == []


# ---------------------------------------------------------------------------
# markdown_renderer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAnchorId:
    def test_spaces_become_hyphens(self):
        assert create_anchor_id("Hello World") == "hello-world"

    def test_dots_removed(self):
        assert create_anchor_id("v1.0.2") == "v102"

    def test_ampersand_becomes_and(self):
        assert create_anchor_id("Terms & Conditions") == "terms-and-conditions"


@pytest.mark.unit
class TestConvertMarkdownLinks:
    def test_basic_link(self):
        result = _convert_markdown_links("[GitHub](https://github.com)")
        assert result == '<a href="https://github.com">GitHub</a>'

    def test_no_link_unchanged(self):
        assert _convert_markdown_links("plain text") == "plain text"


@pytest.mark.unit
class TestConvertMarkdownInline:
    def test_bold_double_star(self):
        assert "<strong>bold</strong>" in _convert_markdown_inline("**bold**")

    def test_italic_single_star(self):
        assert "<em>italic</em>" in _convert_markdown_inline("*italic*")

    def test_inline_code(self):
        result = _convert_markdown_inline("`code`")
        assert "<code>code</code>" in result

    def test_code_protects_star_content(self):
        # Stars inside backticks should not become italic/bold
        result = _convert_markdown_inline("`vehicle_Name*`")
        assert "<em>" not in result
        assert "vehicle_Name*" in result


@pytest.mark.unit
class TestMarkdownToHtml:
    def test_returns_html_document(self):
        html = markdown_to_html("# Title\n\nParagraph.")
        assert html.startswith("<html>")
        assert "<h1" in html
        assert "<p>" in html

    def test_h1_gets_anchor(self):
        html = markdown_to_html("# My Section")
        assert "id='my-section'" in html

    def test_unordered_list(self):
        html = markdown_to_html("- item one\n- item two")
        assert "<ul>" in html
        assert "<li>" in html

    def test_ordered_list(self):
        html = markdown_to_html("1. first\n2. second")
        assert "<ol>" in html

    def test_code_block(self):
        html = markdown_to_html("```\ncode here\n```")
        assert "<pre><code>" in html

    def test_colors_injected(self):
        html = markdown_to_html("text", text_color="#ff0000", base_color="#00ff00", link_color="#0000ff")
        assert "#ff0000" in html
        assert "#00ff00" in html
        assert "#0000ff" in html

    def test_empty_input(self):
        html = markdown_to_html("")
        assert "<html>" in html
        assert "</html>" in html
