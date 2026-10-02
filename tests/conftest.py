import pytest

from helpers import load_plugin


@pytest.fixture(scope="session")
def plugin():
    return load_plugin()


@pytest.fixture(autouse=True)
def charts_home(tmp_path, monkeypatch):
    """Write PNGs into a temp HERMES_HOME, never the user's real one."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    return tmp_path
