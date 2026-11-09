import pytest

from wingetdeck import i18n
from wingetdeck.paths import resolve_data_dir


@pytest.fixture(autouse=True)
def english_afterwards():
    """The language is one setting for the whole app, so a test that picks French must not leave it behind."""
    yield
    i18n.set_language("en")


@pytest.fixture
def tmp_data(tmp_path):
    return resolve_data_dir(tmp_path / "app", tmp_path / "local")
