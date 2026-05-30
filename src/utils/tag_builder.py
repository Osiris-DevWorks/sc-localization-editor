"""Dynamic tag builder for enhancement name annotations.

Used by both the enhancement generator (CLI / worker thread) and the
Enhancements tab live preview, so it must be pure Python with no Qt
dependency. A `TagConfig` describes one category's tag (element order,
per-element style, separator, enclosing brackets, and the class-variant
mapping when applicable); `render_tag()` produces the final bracketed
string given that config plus a values dict.

Defaults in DEFAULT_TAG_CONFIGS are calibrated to match the previously
hardcoded format strings byte-for-byte so an existing user sees no
change in their generated INIs until they edit a config.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Category + element vocabulary ─────────────────────────────────────────────

CATEGORIES = ("components", "missiles", "ship_weapons", "commodities")

# Which element kinds each category supports — order here is the *default*
# order shown in the UI before the user reorders. Each kind maps to a value
# key in the values-dict passed to render_tag.
CATEGORY_ELEMENT_KINDS: dict[str, tuple[str, ...]] = {
    "components":   ("class", "size", "grade", "type"),
    "missiles":     ("ordinance", "size"),
    "ship_weapons": ("damage", "size"),
    "commodities":  ("label", "collection"),
}



# ── Style tables ──────────────────────────────────────────────────────────────
# Each entry is (style_key, human_label). The order here drives the dropdown
# option order; the first entry is what `DEFAULT_TAG_CONFIGS` selects unless
# the default config overrides.

STYLES_CLASS: tuple[tuple[str, str], ...] = (
    ("short", "Short (M)"),
    ("med",   "Medium (MIL)"),
    ("long",  "Long (Military)"),
)
STYLES_SIZE: tuple[tuple[str, str], ...] = (
    ("n",      "Number (2)"),
    ("sn",     "S-prefixed (S2)"),
    ("size_n", "Verbose (Size 2)"),
)
STYLES_GRADE: tuple[tuple[str, str], ...] = (
    ("letter",       "Letter (A)"),
    ("grade_letter", "Verbose (Grade A)"),
)
STYLES_ORDINANCE: tuple[tuple[str, str], ...] = (
    ("short", "Short (I)"),
    ("med",   "Medium (IR)"),
    ("long",  "Long (Infrared)"),
)
STYLES_DAMAGE: tuple[tuple[str, str], ...] = (
    ("short", "Short (E)"),
    ("med",   "Medium (EN)"),
    ("long",  "Long (Energy)"),
)
STYLES_TYPE: tuple[tuple[str, str], ...] = (
    ("short", "Short (SH)"),
    ("med",   "Medium (SHLD)"),
    ("long",  "Long (Shield)"),
)
STYLES_LABEL: tuple[tuple[str, str], ...] = (
    ("short", "Short (CF)"),
    ("med",   "Medium (Craft)"),
    ("long",  "Long (Crafting)"),
)
STYLES_COLLECTION: tuple[tuple[str, str], ...] = (
    ("short", "Short (Col)"),
    ("med",   "Medium (Collect)"),
    ("long",  "Long (Collection)"),
)

STYLES_BY_KIND: dict[str, tuple[tuple[str, str], ...]] = {
    "class":      STYLES_CLASS,
    "size":       STYLES_SIZE,
    "grade":      STYLES_GRADE,
    "ordinance":  STYLES_ORDINANCE,
    "damage":     STYLES_DAMAGE,
    "type":       STYLES_TYPE,
    "label":      STYLES_LABEL,
    "collection": STYLES_COLLECTION,
}

# Human-friendly element kind labels for the UI.
ELEMENT_LABELS: dict[str, str] = {
    "class":     "Class",
    "size":      "Size",
    "grade":     "Grade",
    "ordinance": "Ordinance",
    "damage":    "Damage type",
    "type":       "Type",
    "label":      "Label",
    "collection": "Collection",
}


# ── Separator + enclosing tables ─────────────────────────────────────────────

# (key, label, render_string)
SEPARATORS: tuple[tuple[str, str, str], ...] = (
    ("none",       "None",        ""),
    ("space",      "Space",       " "),
    ("hyphen",     "Hyphen ( - )", "-"),
    ("underscore", "Underscore ( _ )", "_"),
    ("dot",        "Period ( . )", "."),
    ("slash",      "Slash ( / )", "/"),
    ("pipe",       "Pipe ( | )",  "|"),
)

# (key, label, open, close)
ENCLOSINGS: tuple[tuple[str, str, str, str], ...] = (
    ("none",   "None (space only)", "",  ""),
    ("square", "Square [ ]",        "[", "]"),
    ("round",  "Round ( )",         "(", ")"),
    ("curly",  "Curly { }",         "{", "}"),
    ("angle",  "Angle < >",         "<", ">"),
)

_SEPARATOR_BY_KEY = {k: s for k, _, s in SEPARATORS}
_ENCLOSING_BY_KEY = {k: (o, c) for k, _, o, c in ENCLOSINGS}


# ── Built-in class/ordinance/damage variant mappings ─────────────────────────
# Tuple order is (short, med, long). Categories with only short/long
# (e.g. missiles) repeat the value in the unused slot.

DEFAULT_COMPONENT_CLASS_MAPPING: dict[str, tuple[str, str, str]] = {
    "Competition": ("R", "CMP", "Competition"),
    "Military":    ("M", "MIL", "Military"),
    "Civilian":    ("C", "CIV", "Civilian"),
    "Industrial":  ("I", "IND", "Industrial"),
    "Stealth":     ("S", "STH", "Stealth"),
}

# Missile ordinance: (short=1 char, med=2 chars, long=full word). Bomb's
# canonical shorthand is a single "B" at every length — duplicating it in
# all three slots matches what users expect to see in-game.
DEFAULT_MISSILE_ORDINANCE_MAPPING: dict[str, tuple[str, str, str]] = {
    "Infrared":        ("I", "IR", "Infrared"),
    "Electromagnetic": ("E", "EM", "Electromagnetic"),
    "CrossSection":    ("C", "CS", "CrossSection"),
    "Bomb":            ("B", "B",  "Bomb"),
}

# Keys are the full English damage names users see in the mapping editor.
# The ship-weapon tagger (_ship_weapon_name_tag_factory in
# scripts/generate_enhancements_ini.py) translates the generator's compact
# labels ("Phys", "Distort", "Bio") into these full forms before passing
# the value into render_tag, via DAMAGE_LABEL_TO_MAPPING_KEY below.
DEFAULT_SHIP_WEAPON_DAMAGE_MAPPING: dict[str, tuple[str, str, str]] = {
    "Energy":      ("E", "EN",  "Energy"),
    "Physical":    ("P", "PHY", "Physical"),
    "Distortion":  ("D", "DIS", "Distortion"),
    "Thermal":     ("T", "THM", "Thermal"),
    "Biochemical": ("B", "BIO", "Biochemical"),
    "Stun":        ("S", "STN", "Stun"),
}

# Compact label (as emitted by _DAMAGE_LABELS in generate_enhancements_ini.py)
# → full English name used as the mapping key. The generator uses short
# labels in description text ("Alpha Dmg: 5.0 (Phys)") for compactness;
# the tag mapping uses the full word so the variant editor reads naturally.
DAMAGE_LABEL_TO_MAPPING_KEY: dict[str, str] = {
    "Phys":    "Physical",
    "Distort": "Distortion",
    "Bio":     "Biochemical",
    # Energy / Thermal / Stun already match between compact and full forms.
}

DEFAULT_COMPONENT_TYPE_MAPPING: dict[str, tuple[str, str, str]] = {
    "Shield Generator": ("SH",  "SHLD", "Shield"),
    "Cooler":           ("CL",  "COOL", "Cooler"),
    "Power Plant":      ("PW",  "POWR", "Power"),
    "Quantum Drive":    ("QD",  "QDRV", "Quantum"),
    "Radar":            ("RD",  "RADR", "Radar"),
}

DEFAULT_COMMODITY_LABEL_MAPPING: dict[str, tuple[str, str, str]] = {
    "Crafting": ("CF", "Craft", "Crafting"),
}

# Collection-mission item flag. Combined with the crafting flag inside one
# <EM4>[…]</EM4> wrapper (e.g. "[CF|Collection]") when an item is both (#97).
DEFAULT_COMMODITY_COLLECTION_MAPPING: dict[str, tuple[str, str, str]] = {
    "Collection": ("Col", "Collect", "Collection"),
}

DEFAULT_KIND_MAPPINGS: dict[str, dict[str, tuple[str, str, str]]] = {
    "class":     DEFAULT_COMPONENT_CLASS_MAPPING,
    "type":      DEFAULT_COMPONENT_TYPE_MAPPING,
    "ordinance": DEFAULT_MISSILE_ORDINANCE_MAPPING,
    "damage":    DEFAULT_SHIP_WEAPON_DAMAGE_MAPPING,
    "label":     DEFAULT_COMMODITY_LABEL_MAPPING,
    "collection": DEFAULT_COMMODITY_COLLECTION_MAPPING,
}

# Element kinds whose value resolves through a variant mapping (vs. derived
# kinds like size/grade). Single source of truth — the renderer and the UI's
# mapping-edit affordances both key off this so adding a mapped kind only
# means adding it to DEFAULT_KIND_MAPPINGS above.
MAPPED_KIND_NAMES: frozenset[str] = frozenset(DEFAULT_KIND_MAPPINGS)


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class ElementSpec:
    kind: str          # one of "class", "size", "grade", "ordinance", "damage"
    enabled: bool = True
    style: str = ""    # style key from STYLES_BY_KIND[kind]; "" → first option


PLACEMENTS: tuple[tuple[str, str], ...] = (
    ("prepend", "Before name (default)"),
    ("append",  "After name"),
)


@dataclass
class TagConfig:
    elements: list[ElementSpec] = field(default_factory=list)
    separator: str = "hyphen"      # key from SEPARATORS
    enclosing: str = "square"      # key from ENCLOSINGS
    placement: str = "prepend"     # one of "prepend" / "append"
    class_mapping: dict[str, tuple[str, str, str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # asdict turns tuple values into lists — keep them as lists in JSON.
        d["class_mapping"] = {k: list(v) for k, v in self.class_mapping.items()}
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TagConfig":
        elements_raw = data.get("elements", [])
        elements = [
            ElementSpec(
                kind=e.get("kind", ""),
                enabled=bool(e.get("enabled", True)),
                style=e.get("style", "") or "",
            )
            for e in elements_raw
            if isinstance(e, dict) and e.get("kind")
        ]
        mapping_raw = data.get("class_mapping", {}) or {}
        mapping: dict[str, tuple[str, str, str]] = {}
        for k, v in mapping_raw.items():
            if isinstance(v, (list, tuple)) and len(v) >= 3:
                mapping[k] = (str(v[0]), str(v[1]), str(v[2]))
            elif isinstance(v, (list, tuple)) and len(v) == 2:
                mapping[k] = (str(v[0]), str(v[0]), str(v[1]))
        placement = data.get("placement", "prepend") or "prepend"
        if placement not in ("prepend", "append"):
            placement = "prepend"
        return cls(
            elements=elements,
            separator=data.get("separator", "hyphen") or "hyphen",
            enclosing=data.get("enclosing", "square") or "square",
            placement=placement,
            class_mapping=mapping,
        )

    @classmethod
    def from_json(cls, blob: str) -> "TagConfig":
        return cls.from_dict(json.loads(blob))


# ── Default configs (must match the previously hardcoded output) ─────────────

DEFAULT_TAG_CONFIGS: dict[str, TagConfig] = {
    "components": TagConfig(
        elements=[
            ElementSpec("class", True, "med"),     # MIL
            ElementSpec("size",  True, "sn"),      # S2
            ElementSpec("grade", True, "letter"),  # A
            ElementSpec("type",  False, "short"),  # SH (disabled by default)
        ],
        separator="hyphen",
        enclosing="square",
        class_mapping={**DEFAULT_COMPONENT_CLASS_MAPPING, **DEFAULT_COMPONENT_TYPE_MAPPING},
    ),
    # Missiles match the components default look: `[IR-S1]` for guided,
    # `[S2]` for bombs (the renderer's empty-value drop collapses the
    # ordinance + leading separator when seeker is absent). Default style
    # is "med" so the rendered abbreviation stays the familiar 2-letter
    # form even though Short (1 char) is now available too.
    "missiles": TagConfig(
        elements=[
            ElementSpec("ordinance", True, "med"),
            ElementSpec("size",      True, "sn"),
        ],
        separator="hyphen",
        enclosing="square",
        class_mapping=dict(DEFAULT_MISSILE_ORDINANCE_MAPPING),
    ),
    # Ship weapons: new tagging in 1.3.x — short damage letter + S-size,
    # same bracket+hyphen style as components, e.g. `[E-S2]`.
    "ship_weapons": TagConfig(
        elements=[
            ElementSpec("damage", True, "short"),
            ElementSpec("size",   True, "sn"),
        ],
        separator="hyphen",
        enclosing="square",
        class_mapping=dict(DEFAULT_SHIP_WEAPON_DAMAGE_MAPPING),
    ),
    # Commodity tagging: two conditional flags sharing one wrapper. Crafting
    # ("CF") for crafting materials, Collection ("Collection") for items used
    # as Collection-mission objectives. When an item is both, render_tag joins
    # them with the separator, e.g. "[CF|Collection]"; when only one flag
    # applies, the other's empty value is dropped so a single-flag item stays
    # "[CF]" or "[Collection]" (#97). Crafting-only output is unchanged from
    # the pre-1.5.0 single-label default.
    "commodities": TagConfig(
        elements=[
            ElementSpec("label", True, "short"),       # CF
            ElementSpec("collection", True, "long"),   # Collection
        ],
        separator="pipe",
        enclosing="square",
        placement="append",
        class_mapping={
            **DEFAULT_COMMODITY_LABEL_MAPPING,
            **DEFAULT_COMMODITY_COLLECTION_MAPPING,
        },
    ),
}


def default_config(category: str) -> TagConfig:
    """Return a fresh copy of the default config for *category*."""
    src = DEFAULT_TAG_CONFIGS[category]
    return TagConfig(
        elements=[ElementSpec(e.kind, e.enabled, e.style) for e in src.elements],
        separator=src.separator,
        enclosing=src.enclosing,
        placement=src.placement,
        class_mapping=dict(src.class_mapping),
    )


# ── Style application ────────────────────────────────────────────────────────

def _style_value(kind: str, style: str, raw: str,
                 mapping: dict[str, tuple[str, str, str]]) -> str:
    """Render *raw* (e.g. "Military", "2", "A") through *kind*/*style*.

    Missing or empty raw values return "" so the renderer can drop them.
    """
    if not raw:
        return ""

    if kind == "size":
        if style == "n":
            return raw
        if style == "size_n":
            return f"Size {raw}"
        # "sn" and any unknown style fall through to the historical default.
        return f"S{raw}"

    if kind == "grade":
        if style == "grade_letter":
            return f"Grade {raw}"
        return raw  # "letter"

    if kind in MAPPED_KIND_NAMES:
        variants = mapping.get(raw)
        if variants is None:
            # Unknown raw value — surface it verbatim so the user can edit
            # the mapping to add it (better than silently dropping).
            return raw
        idx_by_style = {"short": 0, "med": 1, "long": 2}
        idx = idx_by_style.get(style, 1)
        try:
            return variants[idx]
        except IndexError:
            return variants[0]

    return raw


# ── Renderer ─────────────────────────────────────────────────────────────────

def render_tag(config: TagConfig, values: dict[str, str]) -> str:
    """Render *config* against per-element *values* into a tag string.

    Returns "" when no element resolves to a non-empty value (caller skips
    prepending). The returned string already includes any enclosing brackets;
    callers prepend a single space between the tag and the item name.
    """
    if not config.elements:
        return ""

    sep = _SEPARATOR_BY_KEY.get(config.separator, "-")
    open_c, close_c = _ENCLOSING_BY_KEY.get(config.enclosing, ("[", "]"))

    parts: list[str] = []
    for el in config.elements:
        if not el.enabled:
            continue
        raw = str(values.get(el.kind, "") or "")
        styled = _style_value(el.kind, el.style or "", raw, config.class_mapping)
        if styled:
            parts.append(styled)

    if not parts:
        return ""

    body = sep.join(parts)
    return f"{open_c}{body}{close_c}"
