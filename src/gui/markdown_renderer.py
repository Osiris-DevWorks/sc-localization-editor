"""Markdown → styled HTML renderer for the About and Help panels.

Extracted from MainWindow.markdown_to_html so the conversion logic can be
tested without a running Qt application.

Usage with Qt palette colors:

    from PyQt6.QtGui import QPalette
    from PyQt6.QtWidgets import QApplication
    from src.gui.markdown_renderer import markdown_to_html

    palette = QApplication.palette()
    html = markdown_to_html(
        text,
        text_color=palette.color(QPalette.ColorRole.Text).name(),
        base_color=palette.color(QPalette.ColorRole.Base).name(),
        link_color=palette.color(QPalette.ColorRole.Link).name(),
    )
"""

import re
from html import escape


def create_anchor_id(text: str) -> str:
    """Convert a heading text into a URL-safe anchor id."""
    return text.lower().replace(" ", "-").replace(".", "").replace("&", "and")


def _convert_markdown_links(text: str) -> str:
    """Convert markdown links [text](url) to HTML <a> tags."""
    pattern = r"\[([^\]]+)\]\(([^\)]+)\)"
    replacement = r'<a href="\2">\1</a>'
    return re.sub(pattern, replacement, text)


def _convert_markdown_inline(text: str) -> str:
    """Apply inline Markdown (code, links, bold, italic) to a single line.

    Order matters: inline ``code`` is stashed first so ``**`` or ``_``
    inside a code span stay literal, then links / bold / italic run over
    the remaining text. Bold runs before italic so a ``**`` pair isn't
    mis-parsed as two ``*italic*`` brackets.
    """
    # 1. Stash inline code spans behind opaque placeholders so bold/italic
    #    regexes can't touch their content (e.g. `vehicle_Name*` shouldn't
    #    become vehicle_Name<em>).
    code_spans: list[str] = []

    def _stash(match: re.Match) -> str:
        code_spans.append(match.group(1))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _stash, text)

    # 2. Links — do before bold/italic so '_' inside URLs doesn't get chewed.
    text = _convert_markdown_links(text)

    # 3. Bold: **...** and __...__
    text = re.sub(r"\*\*([^*]+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+?)__", r"<strong>\1</strong>", text)

    # 4. Italic: *...* (only; '_' is too common in loc-keys/identifiers
    #    to italicize safely without a proper tokenizer). Require no '*'
    #    on either side of the pair so we don't steal halves of a '**'
    #    bold run that happened to not match step 3.
    text = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)", r"<em>\1</em>", text)

    # 5. Restore code spans — escape the content so any stray angle
    #    brackets inside a backtick span render as literal text.
    for i, content in enumerate(code_spans):
        text = text.replace(f"\x00CODE{i}\x00", f"<code>{escape(content)}</code>")

    return text


def markdown_to_html(
    markdown_text: str,
    text_color: str = "#000000",
    base_color: str = "#ffffff",
    link_color: str = "#0078d7",
) -> str:
    """Convert Markdown to styled HTML.

    Args:
        markdown_text: The Markdown source to convert.
        text_color: CSS colour for body text (hex or named).
        base_color: CSS colour for page background.
        link_color: CSS colour for headings and links.

    Returns:
        Full HTML document string.
    """
    html = "<html><head><style>"
    html += (
        f"body {{ font-family: Segoe UI, Arial, sans-serif; line-height: 1.8; "
        f"padding: 20px; font-size: 15px; color: {text_color}; "
        f"background-color: {base_color}; }}"
    )
    html += (
        f"h1 {{ color: {link_color}; border-bottom: 3px solid {link_color}; "
        f"padding-bottom: 10px; font-size: 32px; font-weight: bold; margin-top: 20px; }}"
    )
    html += (
        f"h2 {{ color: {link_color}; border-bottom: 2px solid {link_color}; "
        f"padding-bottom: 5px; margin-top: 30px; font-size: 24px; font-weight: bold; }}"
    )
    html += f"h3 {{ color: {link_color}; margin-top: 20px; font-size: 20px; font-weight: bold; }}"
    html += f"p {{ font-size: 15px; margin: 10px 0; color: {text_color}; }}"
    html += f"li {{ font-size: 15px; margin: 5px 0; color: {text_color}; }}"
    html += f"a {{ color: {link_color}; text-decoration: underline; font-weight: 500; }}"
    html += "a:hover { text-decoration: underline; opacity: 0.8; cursor: pointer; }"
    html += (
        "code { background-color: rgba(0,0,0,0.05); padding: 2px 6px; "
        "border-radius: 3px; font-family: 'Courier New', monospace; font-size: 14px; }"
    )
    html += (
        "pre { background-color: rgba(0,0,0,0.05); padding: 10px; "
        "border-radius: 5px; overflow-x: auto; font-size: 14px; }"
    )
    html += "ul { margin-left: 20px; font-size: 15px; }"
    html += "ol { margin-left: 20px; font-size: 15px; }"
    html += "strong { font-weight: bold; }"
    html += f"blockquote {{ border-left: 4px solid {link_color}; padding-left: 15px; font-style: italic; font-size: 15px; }}"
    html += "</style></head><body>"

    lines = markdown_text.split("\n")
    in_code_block = False
    in_list = False
    list_type: str | None = None
    prev_blank = False

    for line in lines:
        # Code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                html += "</pre>"
                in_code_block = False
            else:
                html += "<pre><code>"
                in_code_block = True
            continue

        if in_code_block:
            html += line + "\n"
            continue

        # Headers
        if line.startswith("# "):
            if in_list:
                html += f"</{list_type}>"
                in_list = False
            header_text = line[2:].strip()
            anchor_id = create_anchor_id(header_text)
            html += f"<h1 id='{anchor_id}'>{_convert_markdown_inline(header_text)}</h1>"
            prev_blank = False
        elif line.startswith("## "):
            if in_list:
                html += f"</{list_type}>"
                in_list = False
            header_text = line[3:].strip()
            anchor_id = create_anchor_id(header_text)
            html += f"<h2 id='{anchor_id}'>{_convert_markdown_inline(header_text)}</h2>"
            prev_blank = False
        elif line.startswith("### "):
            if in_list:
                html += f"</{list_type}>"
                in_list = False
            header_text = line[4:].strip()
            anchor_id = create_anchor_id(header_text)
            html += f"<h3 id='{anchor_id}'>{_convert_markdown_inline(header_text)}</h3>"
            prev_blank = False
        # Lists
        elif line.strip().startswith("- ") or line.strip().startswith("* "):
            if not in_list or list_type != "ul":
                if in_list:
                    html += f"</{list_type}>"
                html += "<ul>"
                in_list = True
                list_type = "ul"
            list_text = _convert_markdown_inline(line.strip()[2:].strip())
            html += f"<li>{list_text}</li>"
            prev_blank = False
        elif line.strip() and line[0].isdigit() and ". " in line:
            if not in_list or list_type != "ol":
                if in_list:
                    html += f"</{list_type}>"
                html += "<ol>"
                in_list = True
                list_type = "ol"
            list_text_raw = line.strip()
            list_text_raw = list_text_raw[list_text_raw.index(". ") + 2 :].strip()
            html += f"<li>{_convert_markdown_inline(list_text_raw)}</li>"
            prev_blank = False
        # Empty lines
        elif not line.strip():
            if in_list:
                html += f"</{list_type}>"
                in_list = False
                prev_blank = True
            elif not prev_blank:
                prev_blank = True
            continue
        # Paragraphs
        else:
            if in_list:
                html += f"</{list_type}>"
                in_list = False
            html += f"<p>{_convert_markdown_inline(line)}</p>"
            prev_blank = False

    if in_list:
        html += f"</{list_type}>"
    if in_code_block:
        html += "</pre>"

    html += "</body></html>"
    return html
