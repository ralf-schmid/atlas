import pytest


@pytest.fixture(autouse=True)
def _apply_migration(_migrated_schema: None) -> None:
    """Opts this suite into the real-Postgres schema — see tests/conftest.py."""
