from pathlib import Path

from pylynxley.lnk import Lnk
from pylynxley.uwp import UwpSegmentEntry

SUBBLOCK_NAMES = {
    0x11: "PackageFamilyName",
    0x15: "PackageFullName",
    0x05: "Target",
    0x0F: "Location",
    0x0B: "DisplayName",
    0x0A: "DisplayNameAlt",
    0x02: "Logo44x44",
}


def get_sub_blocks(lnk: Lnk) -> dict[str, str | bytes]:
    id_list = lnk.id_list
    assert id_list is not None
    uwp_segment = id_list.items[1]
    assert isinstance(uwp_segment, UwpSegmentEntry)
    sub_blocks: dict[str, str | bytes] = {}
    for main_block in uwp_segment.main_blocks:
        for sub_block in main_block.sub_blocks:
            name = SUBBLOCK_NAMES.get(sub_block.type_id)
            if not name or name in sub_blocks:
                continue
            sub_blocks[name] = sub_block.value
    return sub_blocks


def as_text(value: str | bytes) -> str:
    if isinstance(value, str):
        return value
    return value.decode("utf-16-le", errors="replace").replace("\x00", "")


def test_uwp_read(examples_path: Path):
    full_filename = examples_path / "uwp_calc.lnk"
    lnk = Lnk.from_file(full_filename)

    sub_blocks = get_sub_blocks(lnk)
    assert as_text(sub_blocks["PackageFamilyName"]) == "Microsoft.WindowsCalculator_8wekyb3d8bbwe"
    assert as_text(sub_blocks["PackageFullName"]) == "Microsoft.WindowsCalculator_10.2008.2.0_x64__8wekyb3d8bbwe"
    assert as_text(sub_blocks["Target"]) == "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
    assert (
        as_text(sub_blocks["Location"])
        == "C:\\Program Files\\WindowsApps\\Microsoft.WindowsCalculator_10.2008.2.0_x64__8wekyb3d8bbwe"
    )
    assert as_text(sub_blocks.get("DisplayName") or sub_blocks["DisplayNameAlt"]) == "Calculator"


def test_uwp_write(examples_path: Path, temp_filename: Path):
    full_filename = examples_path / "uwp_calc.lnk"
    lnk = Lnk.from_file(full_filename)
    lnk.save(temp_filename)
    lnk2 = Lnk.from_file(temp_filename)

    sub_blocks = get_sub_blocks(lnk2)
    assert as_text(sub_blocks["PackageFamilyName"]) == "Microsoft.WindowsCalculator_8wekyb3d8bbwe"
    assert as_text(sub_blocks["PackageFullName"]) == "Microsoft.WindowsCalculator_10.2008.2.0_x64__8wekyb3d8bbwe"
    assert as_text(sub_blocks["Target"]) == "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
    assert (
        as_text(sub_blocks["Location"])
        == "C:\\Program Files\\WindowsApps\\Microsoft.WindowsCalculator_10.2008.2.0_x64__8wekyb3d8bbwe"
    )
    assert as_text(sub_blocks.get("DisplayName") or sub_blocks["DisplayNameAlt"]) == "Calculator"


def test_as_text_bytes_branch():
    assert as_text("A") == "A"
    assert as_text("B\x00".encode("utf-16-le")) == "B"
