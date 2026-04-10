from pathlib import Path

import pytest


@pytest.fixture()
def examples_path():
    return Path(__file__).parent / "examples"


@pytest.fixture()
def temp_filename(tmp_path: Path):
    return tmp_path / "temp.lnk"
