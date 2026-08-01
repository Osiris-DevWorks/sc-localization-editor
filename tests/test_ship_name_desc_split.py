"""Tests for src.models.string_model.is_ship_name_key (#329).

Ship description entries share the "Ships" category with ship name entries,
but only the name entry's custom_value feeds the in-game ASOP favorite-prefix
/ sort-order mechanism (ship_sort_prefix.py) -- a description being marked
"favorite" edits text nothing in-game reads sorted or starred. This locks the
key-pattern distinction the favorite/sort UI (string_table_model.py,
entry_filter.py) relies on to keep description rows out of that mechanism.
"""
import pytest

from src.models.string_model import StringEntry, is_favoritable_ship, is_ship_name_key

pytestmark = pytest.mark.unit


def _entry(key, category="Ships"):
    return StringEntry(
        key=key,
        source_file="global",
        category=category,
        original_value="v",
        custom_value="",
        status="Unmodified",
    )


def test_bare_vehicle_name_key_is_a_name():
    assert is_ship_name_key("vehicle_NameANVL_Carrack") is True


def test_bare_vehicle_desc_key_is_not_a_name():
    assert is_ship_name_key("vehicle_DescANVL_Carrack") is False


def test_case_insensitive():
    assert is_ship_name_key("VEHICLE_NAMEanvl_carrack") is True
    assert is_ship_name_key("VEHICLE_DESCanvl_carrack") is False


def test_wikelo_vehiclename_suffix_is_a_name():
    assert is_ship_name_key("TheCollector_ShipMod_01_VehicleName") is True


def test_wikelo_vehiclenameshort_suffix_is_a_name():
    assert is_ship_name_key("TheCollector_ShipMod_01_VehicleNameShort") is True


def test_wikelo_vehicledesc_suffix_is_not_a_name():
    assert is_ship_name_key("TheCollector_ShipMod_01_VehicleDesc") is False


def test_unrelated_key_is_not_a_name():
    assert is_ship_name_key("item_NameSHLD_Aspirum") is False
    assert is_ship_name_key("mission_title_001") is False


def test_empty_or_none_key_is_not_a_name():
    assert is_ship_name_key("") is False
    assert is_ship_name_key(None) is False


class TestIsFavoritableShip:
    """is_favoritable_ship pairs the key-shape check with the entry's stored
    category. Both halves matter: the category is NOT always derived from
    the key (ini_parser assigns it from the source enhancement file when
    enhancements_key_categories applies), so the stored category is the
    authority on which bucket a row is displayed under."""

    def test_ship_name_row_is_favoritable(self):
        assert is_favoritable_ship(_entry("vehicle_NameANVL_Carrack")) is True

    def test_ship_description_row_is_not(self):
        assert is_favoritable_ship(_entry("vehicle_DescANVL_Carrack")) is False

    def test_wikelo_name_row_is_favoritable(self):
        assert is_favoritable_ship(_entry("TheCollector_ShipMod_01_VehicleName")) is True

    def test_non_ships_category_is_not_favoritable(self):
        assert is_favoritable_ship(_entry("item_NameSHLD_Aspirum", category="Ship Items")) is False

    def test_name_shaped_key_recategorized_away_from_ships_is_not_favoritable(self):
        """The reason the category half can't be dropped: a key whose SHAPE
        says ship-name but whose stored category says otherwise (the
        enhancements_key_categories override path in ini_parser) must not
        get a star, because it isn't displayed under Ships."""
        e = _entry("vehicle_NameANVL_Carrack", category="Other")
        assert is_ship_name_key(e.key) is True
        assert is_favoritable_ship(e) is False
