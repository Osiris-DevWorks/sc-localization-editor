"""Regression tests for `_mirror_scitem_siblings` (#190).

CIG ships some components under several loc-key spellings for one item. The
generator enhances the key the entity XML references; this helper mirrors the
enhanced value onto the sibling spellings the game may actually display.

The #190 case: every S3 quantum drive (Balandin, Erebos, Wanderer, ...) has an
entity that references a LOWERCASE ``item_name*`` / ``item_desc*`` ``_SCItem``
key, while base.ini also carries the CAPITALIZED bare key (``item_Name*`` /
``item_Desc*``) that the game renders. Before the fix the mirror only tried the
same-case strip, so the displayed key stayed stock: shown as Unmodified, no
[CLASS-Sx-grade] tag, and unmatchable for Owned.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_scitem_mirror_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_lowercase_scitem_mirrors_to_capital_bare_key(gen_module):
    """#190: a lowercase ``item_name*``/``item_desc*`` _SCItem enhancement is
    mirrored onto the capitalized bare key the game displays."""
    sep = gen_module.ENHANCEMENT_SEPARATOR
    out = {
        "item_descQDRV_WETK_S03_Balandin_SCItem": f"Stock blurb.{sep}\\nQT Speed: 339",
        "item_nameQDRV_WETK_S03_Balandin_SCItem": "[MIL-S3-B] Balandin",
    }
    loc = {
        "item_descQDRV_WETK_S03_Balandin_SCItem": "Stock blurb.",
        "item_nameQDRV_WETK_S03_Balandin_SCItem": "Balandin",
        # The keys the game actually renders:
        "item_DescQDRV_WETK_S03_Balandin": "Stock blurb.",
        "item_NameQDRV_WETK_S03_Balandin": "Balandin",
    }

    gen_module._mirror_scitem_siblings(out, loc)

    # The displayed name key now carries the tag.
    assert out["item_NameQDRV_WETK_S03_Balandin"] == "[MIL-S3-B] Balandin"
    # The displayed desc key now carries the stats block.
    assert out["item_DescQDRV_WETK_S03_Balandin"] == f"Stock blurb.{sep}\\nQT Speed: 339"
    # No phantom lowercase bare key (it isn't in base.ini).
    assert "item_nameQDRV_WETK_S03_Balandin" not in out
    assert "item_descQDRV_WETK_S03_Balandin" not in out


def test_mirror_returns_sibling_counts(gen_module):
    sep = gen_module.ENHANCEMENT_SEPARATOR
    out = {
        "item_descQDRV_WETK_S03_Balandin_SCItem": f"Stock.{sep}\\nstats",
        "item_nameQDRV_WETK_S03_Balandin_SCItem": "[MIL-S3-B] Balandin",
    }
    loc = {
        "item_DescQDRV_WETK_S03_Balandin": "Stock.",
        "item_NameQDRV_WETK_S03_Balandin": "Balandin",
        "item_descQDRV_WETK_S03_Balandin_SCItem": "Stock.",
        "item_nameQDRV_WETK_S03_Balandin_SCItem": "Balandin",
    }
    scitem_count, legacy_count = gen_module._mirror_scitem_siblings(out, loc)
    assert scitem_count == 2  # capital desc + capital name
    assert legacy_count == 0


def test_same_case_bare_key_still_mirrors(gen_module):
    """No regression: the original same-case path (capital ``item_DescX_SCItem``
    + capital bare ``item_DescX``, e.g. PTU 4.8 Juno/ARCCorp QDRVs) still works,
    including suffix-placed tags."""
    sep = gen_module.ENHANCEMENT_SEPARATOR
    out = {
        "item_DescQDRV_RSI_S03_Agni_SCItem": f"Stock.{sep}\\nstats",
        "item_NameQDRV_RSI_S03_Agni_SCItem": "Agni [MIL-S3-A]",  # suffix tag
    }
    loc = {
        "item_DescQDRV_RSI_S03_Agni_SCItem": "Stock.",
        "item_NameQDRV_RSI_S03_Agni_SCItem": "Agni",
        "item_DescQDRV_RSI_S03_Agni": "Stock.",
        "item_NameQDRV_RSI_S03_Agni": "Agni",
    }

    gen_module._mirror_scitem_siblings(out, loc)

    assert out["item_DescQDRV_RSI_S03_Agni"] == f"Stock.{sep}\\nstats"
    # Suffix tag is rebuilt from the stock bare name + the trailing tag.
    assert out["item_NameQDRV_RSI_S03_Agni"] == "Agni [MIL-S3-A]"


def test_no_bare_sibling_in_loc_is_noop(gen_module):
    """If neither the same-case nor the capitalized bare key exists in base.ini,
    nothing is mirrored (and the _SCItem entry is left untouched)."""
    out = {"item_nameQDRV_XXXX_S03_Ghost_SCItem": "[MIL-S3-A] Ghost"}
    loc = {"item_nameQDRV_XXXX_S03_Ghost_SCItem": "Ghost"}

    scitem_count, legacy_count = gen_module._mirror_scitem_siblings(out, loc)

    assert scitem_count == 0
    assert legacy_count == 0
    assert out == {"item_nameQDRV_XXXX_S03_Ghost_SCItem": "[MIL-S3-A] Ghost"}
