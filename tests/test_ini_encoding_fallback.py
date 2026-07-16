"""Non-UTF-8 base.ini tolerance (#251).

A 2.2.0 user's Generate Enhancements crashed with ``UnicodeDecodeError:
'utf-8' codec can't decode byte 0xa0`` — their base.ini wasn't clean UTF-8,
on a stock English install. 0xA0 is the Windows-1252 non-breaking space:
CIG's text carries plenty of characters that cp1252 encodes as single high
bytes (é / ™ / ° / em dash / NBSP), so a cached base.ini re-saved by an
external editor in ANSI (legacy Notepad's default) or mangled by a sync/AV
tool decodes as invalid UTF-8 at the first such character. Both INI readers
now decode UTF-8 first and fall back to cp1252 instead of failing:

  * ``scripts/generate_enhancements_ini.parse_ini`` crashed the whole
    enhancements run on the first bad byte.
  * ``src/parser/ini_parser.parse_ini_file`` was quietly worse: its broad
    except caught the mid-iteration decode error and returned a silently
    TRUNCATED result — every key after the bad byte vanished.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.parser.ini_parser import parse_ini_file  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _generator_parse_ini():
    """Import the standalone generator script's parse_ini lazily so a missing
    lxml (its only third-party dep) skips these cases instead of erroring."""
    pytest.importorskip("lxml")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import generate_enhancements_ini as gen
    return gen.parse_ini


# The reported failure shape: an NBSP (0xA0) written as a bare cp1252 byte,
# with keys after the bad byte that a truncating parser would lose. The
# values here are French-flavored only because NBSP-heavy text makes the
# dense case; the actual report was a stock English install.
_CP1252_CONTENT = (
    "vehicle_NameHunter=Drake Cutlass Black\n"
    "mission_prompt=Continuer\xa0?\n"
    "item_NameSHLD_Aspirum=Bouclier «\xa0Aspirum\xa0»\n"
    "key_after_bad_byte=must survive\n"
)


@pytest.fixture
def cp1252_ini(tmp_path) -> Path:
    p = tmp_path / "base.ini"
    p.write_bytes(_CP1252_CONTENT.encode("cp1252"))
    return p


@pytest.fixture
def utf8_bom_ini(tmp_path) -> Path:
    p = tmp_path / "base.ini"
    p.write_bytes("﻿vehicle_NameHunter=Drake Cutlass Black\nk2=v2\n".encode("utf-8"))
    return p


class TestAppParser:
    def test_cp1252_file_parses_completely(self, cp1252_ini):
        result = parse_ini_file(cp1252_ini)
        # Pre-fix this returned only the keys before the 0xA0 byte.
        assert result["key_after_bad_byte"] == "must survive"
        assert result["mission_prompt"] == "Continuer\xa0?"
        assert result["item_NameSHLD_Aspirum"] == "Bouclier «\xa0Aspirum\xa0»"
        assert len(result) == 4

    def test_utf8_bom_still_parses(self, utf8_bom_ini):
        result = parse_ini_file(utf8_bom_ini)
        assert result == {"vehicle_NameHunter": "Drake Cutlass Black", "k2": "v2"}

    def test_utf8_without_bom_still_parses(self, tmp_path):
        p = tmp_path / "base.ini"
        p.write_text("clé=révisé — ✓\n", encoding="utf-8")
        assert parse_ini_file(p) == {"clé": "révisé — ✓"}

    def test_cp1252_undefined_byte_does_not_crash(self, tmp_path):
        # 0x81 is undefined even in cp1252; errors="replace" must absorb it.
        p = tmp_path / "base.ini"
        p.write_bytes(b"good_key=ok\nweird=\x81\nlater_key=still here\n")
        result = parse_ini_file(p)
        assert result["good_key"] == "ok"
        assert result["later_key"] == "still here"

    def test_bom_then_cp1252_body_strips_bom(self, tmp_path):
        # An editor can prepend a UTF-8 BOM and still save the body as ANSI.
        p = tmp_path / "base.ini"
        p.write_bytes(b"\xef\xbb\xbf" + "k=v\xa0!\n".encode("cp1252"))
        result = parse_ini_file(p)
        assert result == {"k": "v\xa0!"}
        assert "﻿k" not in result


class TestGeneratorParser:
    def test_cp1252_file_parses_completely(self, cp1252_ini):
        parse_ini = _generator_parse_ini()
        result = parse_ini(cp1252_ini)
        # Pre-fix this raised UnicodeDecodeError (the #251 traceback).
        assert result["key_after_bad_byte"] == "must survive"
        assert result["mission_prompt"] == "Continuer\xa0?"
        assert len(result) == 4

    def test_utf8_bom_still_parses(self, utf8_bom_ini):
        parse_ini = _generator_parse_ini()
        assert parse_ini(utf8_bom_ini) == {
            "vehicle_NameHunter": "Drake Cutlass Black", "k2": "v2",
        }

    def test_metadata_suffix_still_stripped(self, tmp_path):
        parse_ini = _generator_parse_ini()
        p = tmp_path / "base.ini"
        p.write_bytes("key,P=value\xa0x\n".encode("cp1252"))
        assert parse_ini(p) == {"key": "value\xa0x"}
