from pathlib import Path

import pytest

from pylynxley.lnk import Lnk


@pytest.mark.parametrize(
    "filename,path",
    (
        ("mounted_folder1_file1.lnk", "Z:\\Downloads\\folder1\\file1.txt"),
        ("mounted_folder1_file2.lnk", "Z:\\Downloads\\folder1\\file12.txt"),
        ("mounted_folder2_file1.lnk", "Z:\\Downloads\\folder12\\file1.txt"),
        ("mounted_folder2_file2.lnk", "Z:\\Downloads\\folder12\\file12.txt"),
    ),
)
def test_local_mounted_share(examples_path, temp_filename, filename: str, path: str):
    """This links contains both local and network path."""
    full_filename = examples_path / filename
    lnk = Lnk.from_file(full_filename)
    assert lnk.path == path
    lnk.save(temp_filename)
    lnk2 = Lnk.from_file(Path(temp_filename))
    assert lnk2.path == path


def test_local_disk_link(examples_path, temp_filename):
    filename = examples_path / "local_disk.lnk"
    path = "C:\\"
    lnk = Lnk.from_file(filename)
    assert lnk.path == path
    lnk.save(temp_filename)
    lnk2 = Lnk.from_file(Path(temp_filename))
    assert lnk2.path == path


def test_local_file_link(examples_path, temp_filename):
    filename = examples_path / "local_file.lnk"
    path = "C:\\Windows\\explorer.exe"
    lnk = Lnk.from_file(filename)
    assert lnk.path == path
    lnk.save(temp_filename)
    lnk2 = Lnk.from_file(Path(temp_filename))
    assert lnk2.path == path


def test_local_folder_link(examples_path, temp_filename):
    filename = examples_path / "local_folder.lnk"
    path = "C:\\Users\\stray\\Desktop\\New folder"
    lnk = Lnk.from_file(filename)
    assert lnk.path == path
    lnk.save(temp_filename)
    lnk2 = Lnk.from_file(Path(temp_filename))
    assert lnk2.path == path


def test_local_send_to_fax(examples_path, temp_filename):
    filename = examples_path / "send_to_fax.lnk"
    path = "C:\\WINDOWS\\system32\\WFS.exe"
    lnk = Lnk.from_file(filename)
    first_path = lnk.path
    assert first_path is not None
    assert first_path.lower() == path.lower()
    lnk.save(temp_filename)
    lnk2 = Lnk.from_file(Path(temp_filename))
    second_path = lnk2.path
    assert second_path is not None
    assert second_path.lower() == path.lower()


def test_local_recent1(examples_path, temp_filename):
    filename = examples_path / "recent1.lnk"
    lnk = Lnk.from_file(filename)
    assert lnk.path is not None
    assert lnk.path.endswith("2020M09_01_contract.pdf")
    lnk.save(temp_filename)
    lnk2 = Lnk.from_file(Path(temp_filename))
    assert lnk2.path == lnk.path


def test_local_recent2(examples_path, temp_filename):
    filename = examples_path / "recent2.lnk"
    lnk = Lnk.from_file(filename)
    assert lnk.path is not None
    lnk.save(temp_filename)
    lnk2 = Lnk.from_file(Path(temp_filename))
    assert lnk2.path is not None
    assert lnk2.path.endswith("catastrophe_89f317b5c3.7z")


def test_empty_idlist(examples_path, temp_filename):
    filename = examples_path / "desktop.lnk"
    path = "C:\\Users\\heznik\\Desktop"
    lnk = Lnk.from_file(filename)
    assert lnk.path == path
    lnk.save(temp_filename)
    lnk2 = Lnk.from_file(Path(temp_filename))
    assert lnk2.path == path
