# pyright: reportPrivateUsage=false


from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from typing import ClassVar
from typing import Never
from typing import cast

import pytest

from pylynxley import core
from pylynxley.cli import run_cli
from pylynxley.core import BinReader
from pylynxley.core import BinWriter
from pylynxley.core import EntryType
from pylynxley.core import LinkFlags
from pylynxley.core import LnkError
from pylynxley.core import LnkFormatError
from pylynxley.extradata import IconEnvironmentDataBlock
from pylynxley.extradata import PropertyStore
from pylynxley.extradata import TypedPropertyValue
from pylynxley.idlist import DriveEntry
from pylynxley.idlist import PathSegmentEntry
from pylynxley.idlist import RootEntry
from pylynxley.idlist import _parse_root_or_raw
from pylynxley.idlist import parse_id_list
from pylynxley.linkinfo import LinkInfo
from pylynxley.lnk import Lnk
from pylynxley.lnk import _cli
from pylynxley.lnk import parse_hotkey
from pylynxley.lnk import resolve_lnk
from pylynxley.resolver import _choose_primary_target
from pylynxley.resolver import resolve_known_folder_canonical
from pylynxley.resolver import resolve_lnk_path
from pylynxley.uwp import UwpMainBlock
from pylynxley.uwp import UwpSegmentEntry


@dataclass
class _FakeLinkInfo:
    local: bool = False
    remote: bool = False
    local_base_path: str | None = None
    local_base_path_unicode: str | None = None
    network_share_name: str | None = None
    base_name: str | None = None
    base_name_unicode: str | None = None
    _path: str | None = None

    def path(self) -> str | None:
        return self._path


@dataclass
class _FakeExtraData:
    value: str | None = None

    def first_env_path(self) -> str | None:
        return self.value


@dataclass
class _FakeIdList:
    items: list[object]
    value: str | None = None

    def get_path(self) -> str | None:
        return self.value


@dataclass
class _FakeLnk:
    link_info: _FakeLinkInfo | None
    extra_data: _FakeExtraData
    id_list: _FakeIdList | None
    source_path: Path | None
    working_dir: str | None = None


def test_cli_parse_branch_in_process(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    class StubInst:
        def __init__(self) -> None:
            self.link_flags: int = (
                1 | 2 | 128 | 512 | 8
            )  # HasLinkTargetIDList|HasLinkInfo|IsUnicode|HasExpString|HasRelativePath
            self.show_command: int = 1
            self.file_size: int = 42
            self.path: str | None = "C:\\x"
            self.description: str | None = "d"
            self.working_dir: str | None = "C:\\wd"
            self.arguments: str | None = "--x"
            self.link_info: _FakeLinkInfo = _FakeLinkInfo(
                local=True,
                remote=False,
                local_base_path="C:\\x",
                local_base_path_unicode="C:\\x",
                network_share_name=None,
                base_name="x",
                base_name_unicode="x",
            )
            self.id_list: _FakeIdList | None = _FakeIdList(
                items=[DriveEntry("C:"), PathSegmentEntry.for_path("C:\\")],
                value="C:\\",
            )
            self.extra_data: _FakeExtraData = _FakeExtraData("%USERPROFILE%\\x")

        def save(self, path: Path) -> None:
            path.write_bytes(b"")

    class StubLnk:
        @classmethod
        def from_file(cls, _path: Path) -> StubInst:
            return StubInst()

        @classmethod
        def create_local(cls, *_args: Any, **_kwargs: Any) -> Never:  # pragma: no cover
            raise AssertionError

        @classmethod
        def create_remote(cls, *_args: Any, **_kwargs: Any) -> Never:  # pragma: no cover
            raise AssertionError

        @classmethod
        def create_uwp(cls, *_args: Any, **_kwargs: Any) -> Never:  # pragma: no cover
            raise AssertionError

    class StubFlags:
        HasLinkTargetIDList: ClassVar[int] = 1
        HasLinkInfo: ClassVar[int] = 2
        ForceNoLinkInfo: ClassVar[int] = 256
        IsUnicode: ClassVar[int] = 128
        HasExpString: ClassVar[int] = 512
        HasRelativePath: ClassVar[int] = 8

    class StubShow:
        NORMAL: ClassVar[int] = 1
        MAXIMIZED: ClassVar[int] = 3
        MINIMIZED: ClassVar[int] = 7

    monkeypatch.setattr("sys.argv", ["prog", "parse", str(tmp_path / "a.lnk")])
    assert run_cli(cast(Any, StubLnk), cast(Any, StubFlags), cast(Any, StubShow)) == 0
    out = capsys.readouterr().out
    assert "Flags:" in out
    assert "IDList composite path:" in out


def test_cli_create_and_help_branches(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, tuple[object, ...], dict[str, object], Path]] = []

    class StubInst:
        def save(self, path: Path) -> None:
            calls.append(("save", tuple(), {}, path))
            path.write_bytes(b"x")

    class StubLnk:
        @classmethod
        def from_file(cls, _path: Path):  # pragma: no cover
            raise AssertionError

        @classmethod
        def create_local(cls, *args, **kwargs):
            calls.append(("local", args, kwargs, Path(".")))
            return StubInst()

        @classmethod
        def create_remote(cls, *args, **kwargs):
            calls.append(("remote", args, kwargs, Path(".")))
            return StubInst()

        @classmethod
        def create_uwp(cls, *args, **kwargs):
            calls.append(("uwp", args, kwargs, Path(".")))
            return StubInst()

    class StubFlags:
        HasLinkTargetIDList: ClassVar[int] = 1
        HasLinkInfo: ClassVar[int] = 2
        ForceNoLinkInfo: ClassVar[int] = 256
        IsUnicode: ClassVar[int] = 128
        HasExpString: ClassVar[int] = 512
        HasRelativePath: ClassVar[int] = 8

    class StubShow:
        NORMAL: ClassVar[int] = 1
        MAXIMIZED: ClassVar[int] = 3
        MINIMIZED: ClassVar[int] = 7

    out_local = tmp_path / "local.lnk"
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "create-local",
            "C:\\Windows\\notepad.exe",
            str(out_local),
            "--window",
            "max",
            "--desc",
            "d",
            "--args",
            "x",
            "--icon",
            "C:\\i.ico",
            "--workdir",
            "C:\\Windows",
        ],
    )
    assert run_cli(cast(Any, StubLnk), cast(Any, StubFlags), cast(Any, StubShow)) == 0

    out_remote = tmp_path / "remote.lnk"
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "create-remote",
            "\\\\srv\\share\\f.txt",
            str(out_remote),
            "--desc",
            "r",
        ],
    )
    assert run_cli(cast(Any, StubLnk), cast(Any, StubFlags), cast(Any, StubShow)) == 0

    out_uwp = tmp_path / "uwp.lnk"
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "create-uwp",
            "PFN",
            "PFN!App",
            str(out_uwp),
            "--location",
            "C:\\Apps",
            "--logo44",
            "logo.png",
            "--desc",
            "u",
        ],
    )
    assert run_cli(cast(Any, StubLnk), cast(Any, StubFlags), cast(Any, StubShow)) == 0

    monkeypatch.setattr("sys.argv", ["prog"])
    assert run_cli(cast(Any, StubLnk), cast(Any, StubFlags), cast(Any, StubShow)) == 2
    assert "usage:" in capsys.readouterr().out


def test_core_encode_decode_override_and_binary_paths(monkeypatch):
    monkeypatch.setenv("PYLNK_ANSI_CODEC", "not-a-codec")
    assert core.decode_ansi(b"A") == "A"
    assert core.encode_ansi("A").startswith(b"A")

    br = BinReader(BytesIO(b"\x03\x00ABC"))
    assert br.read_sized_string(is_unicode=False) == "ABC"

    out = BytesIO()
    bw = BinWriter(out)
    bw.write_sized_string("AB", is_unicode=False)
    data = out.getvalue()
    assert data[:2] == b"\x03\x00"


def test_core_error_and_guid_helpers(monkeypatch):
    with pytest.raises(LnkFormatError):
        BinReader(BytesIO(b"\x00")).read_bytes(2)
    with pytest.raises(LnkFormatError):
        core._guid_from_bytes(b"short")
    with pytest.raises(LnkFormatError):
        core._bytes_from_guid("{BAD}")

    def raising_guid(_bs: bytes) -> str:
        raise LnkFormatError("bad")

    monkeypatch.setattr(core, "_guid_from_bytes", raising_guid)
    assert core._extract_first_guid_from_bytes(b"1234567890abcdef") is None


def test_core_known_folder_canonical(monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"C:\\Users\\A")
    assert core._resolve_known_folder_canonical("x") is None
    assert core._resolve_known_folder_canonical("::{broken") is None
    assert core._resolve_known_folder_canonical("::{00000000-0000-0000-0000-000000000000}") is None


def test_idlist_error_and_fallback_paths(monkeypatch):
    with pytest.raises(LnkFormatError):
        RootEntry.from_bytes(b"\x00\x00")
    with pytest.raises(LnkFormatError):
        DriveEntry.from_bytes(b"\x2f")

    def missing_stat(_self: Path):
        raise FileNotFoundError

    monkeypatch.setattr(Path, "stat", missing_stat)
    p = PathSegmentEntry.for_path(r"C:\\not-there")
    assert p.file_size == 0

    with pytest.raises(Exception):
        PathSegmentEntry(entry_type=EntryType.KNOWN_FOLDER).to_bytes()

    fallback = _parse_root_or_raw(b"\x1f\x50")
    assert fallback.__class__.__name__ == "RawIdListItem"

    raw = b"\x02\x00" + b"\x00\x00"
    parsed = parse_id_list(raw)
    assert parsed.items == []


def test_linkinfo_low_level_edges():
    assert LinkInfo().path() is None
    assert LinkInfo._read_cstr_at(b"abc", 5, 0) == ""
    assert LinkInfo._read_cstr_at(b"abc", 0, 0) == "abc"
    assert LinkInfo._read_cuni_at(b"\x00", 1, 0) == ""

    li = LinkInfo(local=True)
    LinkInfo._populate_local_fields(li, b"", 0, 0, 0, 0)
    LinkInfo._populate_local_fields(li, b"", 0, 1, 0, 0)

    out = BytesIO()
    bw = BinWriter(out)
    LinkInfo(local=False, remote=False).write(bw, include_unicode=False)

    with pytest.raises(RuntimeError):
        LinkInfo._patch_header_offsets(
            BinWriter(BytesIO()),
            (0, 0, 0, 0, 0, 0, None, None),
            0,
            0,
            0,
            0,
            0,
            0,
            True,
        )


def test_extradata_typed_and_property_store_paths():
    br = BinReader(BytesIO(b"\x13\x00\x00\x00"))
    tp = TypedPropertyValue.read(br)
    assert tp.vt_type == 0x13

    br_lpwstr = BinReader(BytesIO(b"\x1f\x00\x00\x00" + (4).to_bytes(4, "little") + b"A\x00"))
    tp_lpwstr = TypedPropertyValue.read(br_lpwstr)
    assert tp_lpwstr.vt_type == 0x1F

    str_raw = (4).to_bytes(4, "little") + "A\x00".encode("utf-16-le")
    assert TypedPropertyValue.parse(0x1F, str_raw) == "A"
    assert TypedPropertyValue.parse(0x15, (9).to_bytes(8, "little")) == 9
    ft = (0).to_bytes(8, "little")
    assert isinstance(TypedPropertyValue.parse(0x40, ft), datetime)

    with pytest.raises(LnkFormatError):
        PropertyStore.read(BinReader(BytesIO((12).to_bytes(4, "little") + (0).to_bytes(4, "little") + b"\x00" * 4)))

    name_bytes = "Name".encode("utf-16-le")
    value_blob = (0x13).to_bytes(2, "little") + b"\x00\x00" + (7).to_bytes(4, "little")
    value_size = 9 + len(value_blob)
    payload = (
        value_size.to_bytes(4, "little")
        + len(name_bytes).to_bytes(4, "little")
        + b"\x00"
        + name_bytes
        + value_blob
        + (0).to_bytes(4, "little")
    )
    blob = (
        (8 + 16 + len(payload)).to_bytes(4, "little")
        + core.PROPERTY_STORE_VERSION_SPS1.to_bytes(4, "little")
        + core.PROPERTY_STORE_STRING_FORMAT_ID
        + payload
    )
    out = PropertyStore.read(BinReader(BytesIO(blob)))
    assert out is not None
    assert out.properties

    store = PropertyStore(
        format_id=core.PROPERTY_STORE_STRING_FORMAT_ID,
        is_strings=True,
        properties=[("Name", TypedPropertyValue(0x13, (7).to_bytes(4, "little")))],
    )
    assert store.to_bytes().startswith(b"\x00") is False

    icon = IconEnvironmentDataBlock(target_ansi="A", target_unicode="B")
    clone = IconEnvironmentDataBlock.from_bytes(icon.to_bytes()[8:])
    assert clone.target_ansi.startswith("A")


def test_uwp_error_branches():
    with pytest.raises(LnkFormatError):
        UwpMainBlock.from_bytes(BinReader(BytesIO(b"BAD!" + b"\x00" * 32)))

    with pytest.raises(LnkFormatError):
        UwpSegmentEntry.from_bytes(b"\x00\x00\x14\x00NOPE" + b"\x00" * 20)

    with pytest.raises(LnkFormatError):
        UwpSegmentEntry.from_bytes(b"\x00\x00\x10\x00APPS\x04\x00" + b"\x00" * 10)

    with pytest.raises(LnkFormatError):
        UwpSegmentEntry.from_bytes(
            b"\x00\x00\x40\x00APPS\x20\x00" + b"\x08\x00\x03\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 4
        )

    with pytest.raises(LnkFormatError):
        UwpSegmentEntry.from_bytes(
            b"\x00\x00\x16\x00APPS\x04\x00" + b"\x08\x00\x03\x00\x00\x00\x00\x00\x00\x00" + b"\x03\x00\x00\x00"
        )

    with pytest.raises(LnkFormatError):
        UwpSegmentEntry.from_bytes(
            b"\x00\x00\x14\x00APPS\x0a\x00" + b"\x08\x00\x03\x00\x00\x00\x00\x00\x00\x00" + b"\x00\x00"
        )

    with pytest.raises(LnkFormatError):
        UwpSegmentEntry.from_bytes(
            b"\x00\x00\x14\x00APPS\x02\x00" + b"\x08\x00\x03\x00\x00\x00\x00\x00\x00\x00" + b"\x00\x00"
        )

    with pytest.raises(LnkFormatError):
        UwpSegmentEntry.from_bytes(
            b"\x00\x00\x1c\x00APPS\x08\x00"
            + b"\x08\x00\x03\x00\x00\x00\x00\x00\x00\x00"
            + b"\x0c\x00\x00\x00"
            + b"\x00\x00\x00\x00"
        )

    ok_with_tail = UwpSegmentEntry.from_bytes(
        b"\x00\x00\x1a\x00APPS\x06\x00"
        + b"\x08\x00\x03\x00\x00\x00\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x01\x00"
    )
    assert ok_with_tail.main_blocks == []


def test_resolver_branches(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("USERPROFILE", r"C:\\Users\\A")
    assert resolve_known_folder_canonical("x") is None
    assert resolve_known_folder_canonical("::{bad") is None
    assert resolve_known_folder_canonical("::{00000000-0000-0000-0000-000000000000}") is None

    dummy = _FakeLnk(
        link_info=_FakeLinkInfo(local=False, base_name_unicode="tail.txt", _path="\\\\srv\\share\\tail.txt"),
        extra_data=_FakeExtraData(None),
        id_list=_FakeIdList(items=[DriveEntry("Z:")], value="Z:\\"),
        source_path=None,
    )
    assert _choose_primary_target(dummy, "\\\\srv\\share\\tail.txt", None, "Z:\\", "Z:") == "Z:\\tail.txt"

    assert _choose_primary_target(dummy, None, None, "%MY_COMPUTER%\\C:\\x", None) == "C:\\x"
    assert _choose_primary_target(dummy, None, None, "%USERPROFILE%\\::{GUID}", None) == "{GUID}"
    assert _choose_primary_target(dummy, None, None, "::{GUID}", None) == "::{GUID}"

    no_result = _FakeLnk(link_info=None, extra_data=_FakeExtraData(None), id_list=None, source_path=None)
    assert resolve_lnk_path(no_result) is None

    rel = _FakeLnk(
        link_info=_FakeLinkInfo(_path="relative\\file.txt"),
        extra_data=_FakeExtraData(None),
        id_list=None,
        source_path=None,
        working_dir=None,
    )
    assert resolve_lnk_path(rel) == "relative\\file.txt"

    base = tmp_path / "base"
    base.mkdir()
    rel2 = _FakeLnk(
        link_info=_FakeLinkInfo(_path="relative\\file.txt"),
        extra_data=_FakeExtraData(None),
        id_list=None,
        source_path=base / "x.lnk",
        working_dir=None,
    )
    resolved_rel2 = resolve_lnk_path(rel2)
    assert resolved_rel2 is not None
    assert resolved_rel2.endswith("relative\\file.txt")


def test_lnk_factory_and_helper_branches(monkeypatch, tmp_path: Path):
    with pytest.raises(LnkFormatError):
        Lnk.read(BytesIO(b"BAD!" + b"\x00" * 72))

    bad = Lnk.create_local(r"C:\\Windows\\notepad.exe")
    bad.link_flags |= LinkFlags.HasLinkTargetIDList
    bad.id_list = None
    with pytest.raises(Exception):
        bad.to_bytes()

    missing_link_info = Lnk.create_local(r"C:\\Windows\\notepad.exe")
    missing_link_info.link_info = None
    with pytest.raises(Exception):
        missing_link_info.to_bytes()

    with_all_opts = Lnk.create_local(
        r"C:\\Windows\\notepad.exe",
        description="d",
        args="x",
        icon="i",
        working_dir=r"C:\\Windows",
    )
    assert with_all_opts.description == "d"

    force = Lnk.create_local(r"C:\\Windows\\notepad.exe")
    force.link_flags |= LinkFlags.ForceNoLinkInfo
    force.link_info = None
    force.to_bytes()

    with pytest.raises(Exception):
        Lnk.create_local("relative\\x.txt")

    remote = Lnk.create_remote(r"\\srv\share\f.txt", description="d", args="--x", icon="i")
    assert remote.link_info is not None

    uwp = Lnk.create_uwp("PFN", "PFN!App", location="C:\\Apps", logo44x44="logo", description="d")
    assert uwp.id_list is not None

    assert parse_hotkey("ALT+F1") == (0x70, 4)

    out = tmp_path / "x.lnk"
    force.save(out)
    parsed = Lnk.from_file(out)
    assert parsed is not None

    class StubLnkObj:
        path: str = "C:\\x"

    def _from_file_ok(_cls: type[Lnk], _path: Path) -> StubLnkObj:
        return StubLnkObj()

    monkeypatch.setattr(Lnk, "from_file", classmethod(_from_file_ok))
    assert resolve_lnk(Path("x.lnk")) == Path("C:\\x")

    def _from_file_fail(_cls: type[Lnk], _path: Path) -> Never:
        raise LnkError("x")

    monkeypatch.setattr(
        Lnk,
        "from_file",
        classmethod(_from_file_fail),
    )
    assert resolve_lnk(Path("x.lnk")) == Path("x.lnk")


def test_lnk_import_fallback_branches(monkeypatch):
    import pylynxley.lnk as lnk_module
    import pylynxley.resolver as resolver_module

    monkeypatch.setattr(lnk_module, "__package__", "")

    original = resolver_module.resolve_lnk_path

    def fake_resolve(_lnk):
        return "C:\\fallback"

    monkeypatch.setattr(resolver_module, "resolve_lnk_path", fake_resolve)
    loc = Lnk.create_local(r"C:\\Windows\\notepad.exe")
    assert loc.path == "C:\\fallback"

    import pylynxley.cli as cli_module

    def _run_cli_9(*_args: object, **_kwargs: object) -> int:
        return 9

    monkeypatch.setattr(cli_module, "run_cli", _run_cli_9)
    assert _cli() == 9

    monkeypatch.setattr(lnk_module, "__package__", "pylynxley")

    def _run_cli_8(*_args: object, **_kwargs: object) -> int:
        return 8

    monkeypatch.setattr(cli_module, "run_cli", _run_cli_8)
    assert _cli() == 8

    monkeypatch.setattr(resolver_module, "resolve_lnk_path", original)
