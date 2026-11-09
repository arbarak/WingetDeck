import pytest

from wingetdeck.paths import resolve_data_dir


@pytest.fixture
def tmp_data(tmp_path):
    return resolve_data_dir(tmp_path / "app", tmp_path / "local")
