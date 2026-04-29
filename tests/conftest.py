"""
Pytest configuration and fixtures for Open Strings tests

Provides:
- Temporary directories for file-based tests
- Mock fixtures for external dependencies
- Logging configuration
- Custom markers
"""

import os
import sys
import tempfile

import pytest

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def temp_dir():
    """Provide a temporary directory that's cleaned up after test"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_ini_file(temp_dir):
    """Provide a sample INI file with test data"""
    ini_path = os.path.join(temp_dir, "sample.ini")
    content = """vehicle_NameHunter=Drake Cutlass Black
vehicle_DescHunter=A versatile fighter spacecraft
item_NameSHLD_Aspirum=Aspirum Shield
item_NamePOWR_TR1=TR1 Power Plant
items_commodities_AluminumOre=Aluminum Ore
contract_001_name=First Contract
item_Name_GMNL_rifle=Gemini Rifle
"""
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write(content)
    return ini_path


@pytest.fixture
def sample_sources():
    """Provide sample source dictionaries for merge testing"""
    return {
        "global": {
            "vehicle_NameHunter": "Drake Cutlass Black",
            "vehicle_NameAvenger": "Aegis Avenger",
            "item_NameSHLD_Aspirum": "Aspirum Shield",
            "custom_key_1": "value1",
        },
        "contracts": {
            "contract_001_name": "Mining Contract",
            "contract_002_name": "Delivery Contract",
            "item_NameSHLD_Aspirum": "Aspirum Energy Shield",  # Override
        },
        "ships": {
            "vehicle_DescHunter": "Max Speed: 210 m/s",
            "vehicle_DescAvenger": "Max Speed: 180 m/s",
        },
        "user": {},
    }


@pytest.fixture
def mock_game_path(temp_dir):
    """Provide a mock game installation path"""
    game_path = os.path.join(temp_dir, "StarCitizen", "LIVE", "data", "Localization", "english")
    os.makedirs(game_path, exist_ok=True)

    # Create a dummy global.ini
    ini_path = os.path.join(game_path, "global.ini")
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write("vehicle_NameHunter=Drake Cutlass Black\n")

    return game_path


@pytest.fixture
def mock_cache_dir(temp_dir):
    """Provide a mock cache directory structure"""
    cache_dir = os.path.join(temp_dir, "Documents", "Open Strings", "LIVE", "cache")
    os.makedirs(cache_dir, exist_ok=True)

    # Create subdirectories
    for subdir in [
        "backups",
        "dataforge",
        "dataforge/entity",
        "dataforge/entities",
        "dataforge/ships",
    ]:
        os.makedirs(os.path.join(cache_dir, subdir), exist_ok=True)

    return cache_dir


@pytest.fixture
def mock_p4k_path(temp_dir):
    """Provide a mock P4K file path"""
    p4k_path = os.path.join(temp_dir, "Data.p4k")
    # Create a dummy p4k file (not real, just for path testing)
    with open(p4k_path, "wb") as f:
        f.write(b"DUMMY_P4K_DATA")
    return p4k_path


def pytest_configure(config):
    """Configure pytest with custom markers"""
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=PendingDeprecationWarning)
    config.addinivalue_line("markers", "unit: Unit test (fast, no I/O)")
    config.addinivalue_line("markers", "integration: Integration test (file I/O or external tools)")
    config.addinivalue_line("markers", "slow: Slow test (P4K extraction, large file operations)")
    config.addinivalue_line("markers", "critical: Critical feature test (must pass before release)")
    config.addinivalue_line("markers", "regression: Regression test for previously found bugs")
    config.addinivalue_line("markers", "gui: GUI test (requires PyQt6, requires manual testing)")


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests by their location"""
    for item in items:
        # Mark all tests in test_core.py as unit tests by default
        if "test_core.py" in str(item.fspath):
            if "Error" in item.nodeid:
                item.add_marker(pytest.mark.critical)
            elif "Merge" in item.nodeid or "StringEntry" in item.nodeid:
                item.add_marker(pytest.mark.critical)
            else:
                item.add_marker(pytest.mark.unit)

        # Mark all tests in test_pak_extraction.py appropriately
        if "test_pak_extraction.py" in str(item.fspath):
            if "Cache" in item.nodeid or "Extract" in item.nodeid:
                item.add_marker(pytest.mark.critical)
                item.add_marker(pytest.mark.integration)
            else:
                item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def test_data_dir():
    """Provide path to test data directory"""
    tests_dir = os.path.dirname(__file__)
    data_dir = os.path.join(tests_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


class TestReporter:
    """Helper class for test reporting"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def record_pass(self, test_name):
        self.passed += 1
        print(f"✓ {test_name}")

    def record_fail(self, test_name, error):
        self.failed += 1
        print(f"✗ {test_name}: {error}")

    def summary(self):
        total = self.passed + self.failed + self.skipped
        return f"Results: {self.passed} passed, {self.failed} failed, {self.skipped} skipped out of {total}"


@pytest.fixture
def reporter():
    """Provide a test reporter fixture"""
    return TestReporter()
