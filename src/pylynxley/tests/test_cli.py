import subprocess
import sys
from pathlib import Path

from pylynxley.lnk import Lnk


def call_cli(*params: str, check: bool = True) -> str:
    exec_path = Path(__file__).resolve().parents[1] / "lnk.py"
    result = subprocess.run(
        [sys.executable, str(exec_path), *params],
        check=check,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_cli_create_local(temp_filename):
    path = "C:\\folder\\file.txt"
    call_cli("create-local", path, str(temp_filename))
    lnk = Lnk.from_file(temp_filename)
    assert lnk.path == path


def test_cli_create_net(temp_filename):
    path = "\\\\192.168.1.1\\SHARE\\path\\file.txt"
    call_cli("create-remote", path, str(temp_filename))
    lnk = Lnk.from_file(temp_filename)
    assert lnk.path == path


def test_cli_parse(examples_path):
    path = examples_path / "local_file.lnk"
    output = call_cli("parse", str(path), check=False)
    assert "Path: C:\\Windows\\explorer.exe" in output
