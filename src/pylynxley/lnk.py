# ruff: noqa: D102, D101, D107, ANN204
"""Top-level shell link model and orchestration helpers.

This module wires together core primitives and split domain modules to expose
the public `Lnk` API, convenience constructors, and hotkey formatting helpers.
"""

import datetime as dt
import ntpath
import sys
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from io import BufferedIOBase
from io import BytesIO
from pathlib import Path
from typing import Any
from typing import cast

if __name__ == "__main__" and (__package__ is None or __package__ == ""):  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pylynxley.core import HOTKEY_ALPHA_END
from pylynxley.core import HOTKEY_ALPHA_START
from pylynxley.core import HOTKEY_DIGIT_END
from pylynxley.core import HOTKEY_DIGIT_START
from pylynxley.core import HOTKEY_FKEY_BASE
from pylynxley.core import HOTKEY_FKEY_COUNT
from pylynxley.core import HOTKEY_NUMLOCK
from pylynxley.core import HOTKEY_SCROLLLOCK
from pylynxley.core import LNK_SIGNATURE
from pylynxley.core import SHELL_LINK_CLSID_LE
from pylynxley.core import UWP_LOGO_RESOURCE_GUID
from pylynxley.core import UWP_METADATA_EXEC_GUID
from pylynxley.core import UWP_ROOT_APPS_GUID
from pylynxley.core import BinReader
from pylynxley.core import BinWriter
from pylynxley.core import FileAttributes
from pylynxley.core import LinkFlags
from pylynxley.core import LnkError
from pylynxley.core import LnkFormatError
from pylynxley.core import LnkMissingInfoError
from pylynxley.core import ShowCommand
from pylynxley.core import datetime_to_filetime
from pylynxley.core import filetime_to_datetime
from pylynxley.extradata import EnvironmentVariableDataBlock
from pylynxley.extradata import ExtraData
from pylynxley.idlist import DriveEntry
from pylynxley.idlist import LinkTargetIDList
from pylynxley.idlist import PathSegmentEntry
from pylynxley.idlist import RawIdListItem
from pylynxley.idlist import RootEntry
from pylynxley.idlist import parse_id_list
from pylynxley.linkinfo import LinkInfo
from pylynxley.uwp import UwpMainBlock
from pylynxley.uwp import UwpSegmentEntry
from pylynxley.uwp import UwpSubBlock

# ---------------------------------------------------------------------------
# Hotkeys helpers (extended)
# ---------------------------------------------------------------------------
_KEYS: dict[int, str] = {
    **{i: str(i - HOTKEY_DIGIT_START) for i in range(HOTKEY_DIGIT_START, HOTKEY_DIGIT_END)},  # 0-9
    **{i: chr(i) for i in range(HOTKEY_ALPHA_START, HOTKEY_ALPHA_END)},  # A-Z
    **{HOTKEY_FKEY_BASE + i: f"F{i + 1}" for i in range(HOTKEY_FKEY_COUNT)},  # F1-F24
    HOTKEY_NUMLOCK: "NUM LOCK",
    HOTKEY_SCROLLLOCK: "SCROLL LOCK",
}
_MODS = ("SHIFT", "CONTROL", "ALT")


def format_hotkey(low: int, high: int) -> str:
    """Convert low/high hotkey bytes to textual 'MOD+KEY' description.
    >>> format_hotkey(0, 0)
    ''
    """
    key = _KEYS.get(low, "")
    mods = [m for i, m in enumerate(_MODS) if high & (1 << i)]
    return ("+".join([*mods, key])).strip("+")


def parse_hotkey(text: str) -> tuple[int, int]:
    """Parse 'MOD+KEY' into low/high bytes.
    >>> parse_hotkey("")
    (0, 0)
    """
    if not text:
        return 0, 0
    parts = text.split("+")
    key = parts[-1]
    low = next((k for k, v in _KEYS.items() if v == key), 0)
    high = sum(1 << i for i, m in enumerate(_MODS) if m in parts)
    return low, high


# ---------------------------------------------------------------------------
# Lnk top-level structure
# ---------------------------------------------------------------------------
@dataclass
class Lnk:
    link_flags: LinkFlags
    file_attrs: FileAttributes
    creation_time: datetime
    access_time: datetime
    modification_time: datetime
    file_size: int
    icon_index: int
    show_command: ShowCommand
    hot_key: str
    id_list: LinkTargetIDList | None = None
    link_info: LinkInfo | None = None
    description: str | None = None
    relative_path: str | None = None
    working_dir: str | None = None
    arguments: str | None = None
    icon_location: str | None = None
    extra_data: ExtraData = field(default_factory=ExtraData)
    source_path: Path | None = None  # used for relative resolution

    # --- Factory & IO ---
    @classmethod
    def from_file(cls, path: Path) -> Lnk:
        with path.open("rb") as fp:
            lnk = cls.read(fp)
        lnk.source_path = path
        return lnk

    @staticmethod
    def _read_header(
        br: BinReader,
    ) -> tuple[
        LinkFlags,
        FileAttributes,
        datetime,
        datetime,
        datetime,
        int,
        int,
        ShowCommand,
        str,
    ]:
        if br.read_bytes(4) != LNK_SIGNATURE or br.read_bytes(16) != SHELL_LINK_CLSID_LE:
            msg = "Not a valid .lnk signature/GUID."
            raise LnkFormatError(msg)
        flags = LinkFlags(br.read_u32())
        file_attrs = FileAttributes(br.read_u32())
        creation = filetime_to_datetime(br.read_u64())
        access = filetime_to_datetime(br.read_u64())
        modification = filetime_to_datetime(br.read_u64())
        file_size = br.read_u32()
        icon_index = br.read_u32()
        show_id = br.read_u32()
        show = ShowCommand(show_id) if show_id in ShowCommand._value2member_map_ else ShowCommand.NORMAL
        low = br.read_u8()
        high = br.read_u8()
        _ = br.read_bytes(10)
        return (
            flags,
            file_attrs,
            creation,
            access,
            modification,
            file_size,
            icon_index,
            show,
            format_hotkey(low, high),
        )

    @staticmethod
    def _read_optional_string(br: BinReader, flags: LinkFlags, flag: LinkFlags) -> str | None:
        if not (flags & flag):
            return None
        return br.read_sized_string(bool(flags & LinkFlags.IsUnicode))

    @staticmethod
    def _write_optional_string(bw: BinWriter, text: str | None, flags: LinkFlags, flag: LinkFlags) -> None:
        if flags & flag and text is not None:
            bw.write_sized_string(text, bool(flags & LinkFlags.IsUnicode))

    def _write_header(self, bw: BinWriter) -> None:
        bw.write_bytes(LNK_SIGNATURE)
        bw.write_bytes(SHELL_LINK_CLSID_LE)
        bw.write_u32(int(self.link_flags))
        bw.write_u32(int(self.file_attrs))
        bw.write_u64(datetime_to_filetime(self.creation_time))
        bw.write_u64(datetime_to_filetime(self.access_time))
        bw.write_u64(datetime_to_filetime(self.modification_time))
        bw.write_u32(self.file_size)
        bw.write_u32(self.icon_index)
        bw.write_u32(int(self.show_command))
        low, high = parse_hotkey(self.hot_key)
        bw.write_u8(low)
        bw.write_u8(high)
        bw.write_bytes(b"\x00" * 10)

    def _write_link_target_id_list(self, bw: BinWriter) -> None:
        if not (self.link_flags & LinkFlags.HasLinkTargetIDList):
            return
        if not self.id_list:
            msg = "HasLinkTargetIDList but id_list is None."
            raise LnkMissingInfoError(msg)
        id_bytes = self.id_list.to_bytes()
        bw.write_u16(len(id_bytes))
        bw.write_bytes(id_bytes)

    def _write_link_info(self, bw: BinWriter) -> None:
        if not (self.link_flags & LinkFlags.HasLinkInfo):
            return
        if self.link_flags & LinkFlags.ForceNoLinkInfo:
            return
        if not self.link_info:
            msg = "HasLinkInfo but link_info is None."
            raise LnkMissingInfoError(msg)
        self.link_info.write(bw, include_unicode=True)

    @classmethod
    def read(cls, fp: BufferedIOBase) -> Lnk:
        br = BinReader(fp)
        (
            flags,
            file_attrs,
            creation,
            access,
            modification,
            file_size,
            icon_index,
            show,
            hotkey_desc,
        ) = cls._read_header(br)
        id_list = None
        if flags & LinkFlags.HasLinkTargetIDList:
            size = br.read_u16()
            raw = br.read_bytes(size)
            id_list = parse_id_list(raw)
        link_info = None
        if (flags & LinkFlags.HasLinkInfo) and not (flags & LinkFlags.ForceNoLinkInfo):
            link_info = LinkInfo.read(br)
        desc = cls._read_optional_string(br, flags, LinkFlags.HasName)
        rel = cls._read_optional_string(br, flags, LinkFlags.HasRelativePath)
        work = cls._read_optional_string(br, flags, LinkFlags.HasWorkingDir)
        args = cls._read_optional_string(br, flags, LinkFlags.HasArguments)
        icon_loc = cls._read_optional_string(br, flags, LinkFlags.HasIconLocation)
        extra = ExtraData.read(br)
        return cls(
            flags,
            file_attrs,
            creation,
            access,
            modification,
            file_size,
            icon_index,
            show,
            hotkey_desc,
            id_list,
            link_info,
            desc,
            rel,
            work,
            args,
            icon_loc,
            extra,
        )

    def to_bytes(self) -> bytes:
        out = BytesIO()
        bw = BinWriter(out)
        self._write_header(bw)
        self._write_link_target_id_list(bw)
        self._write_link_info(bw)
        self._write_optional_string(bw, self.description, self.link_flags, LinkFlags.HasName)
        self._write_optional_string(bw, self.relative_path, self.link_flags, LinkFlags.HasRelativePath)
        self._write_optional_string(bw, self.working_dir, self.link_flags, LinkFlags.HasWorkingDir)
        self._write_optional_string(bw, self.arguments, self.link_flags, LinkFlags.HasArguments)
        self._write_optional_string(bw, self.icon_location, self.link_flags, LinkFlags.HasIconLocation)
        bw.write_bytes(self.extra_data.to_bytes())
        return out.getvalue()

    def save(self, path: Path) -> None:
        path.write_bytes(self.to_bytes())

    # --- Helpers/API ---
    @property
    def path(self) -> str | None:
        if __package__:
            from .resolver import LnkLike
            from .resolver import resolve_lnk_path
        else:
            from pylynxley.resolver import LnkLike
            from pylynxley.resolver import resolve_lnk_path

        return resolve_lnk_path(cast(LnkLike, self))

    @classmethod
    def create_local(  # noqa: PLR0913
        cls,
        target: str,
        description: str | None = None,
        args: str | None = None,
        icon: str | None = None,
        working_dir: str | None = None,
        window: ShowCommand = ShowCommand.NORMAL,
    ) -> Lnk:
        now = datetime.now(dt.UTC)
        flags = LinkFlags.HasLinkTargetIDList | LinkFlags.HasLinkInfo | LinkFlags.IsUnicode
        if description:
            flags |= LinkFlags.HasName
        if args:
            flags |= LinkFlags.HasArguments
        if icon:
            flags |= LinkFlags.HasIconLocation
        if working_dir:
            flags |= LinkFlags.HasWorkingDir
        drive, rest = ntpath.splitdrive(target)
        if not drive:
            msg = "Target must include drive (e.g., 'C:\\...')."
            raise LnkMissingInfoError(msg)
        drive_letter = drive.upper().rstrip(":\\/")  # e.g., "C"
        id_items: list[PathSegmentEntry | DriveEntry | RootEntry | UwpSegmentEntry | RawIdListItem] = [
            DriveEntry(f"{drive_letter}:")
        ]
        # Accumulate for stat/info correctness
        parts = [p for p in rest.strip("\\/").split("\\") if p]
        acc = f"{drive_letter}:\\"
        for part in parts:
            acc = ntpath.join(acc, part)
            id_items.append(PathSegmentEntry.for_path(acc))
        id_list = LinkTargetIDList(id_items)
        li = LinkInfo(local=True, local_base_path=target, local_base_path_unicode=target)
        return cls(
            flags,
            FileAttributes.NORMAL,
            now,
            now,
            now,
            0,
            0,
            window,
            "",
            id_list,
            li,
            description,
            None,
            working_dir,
            args,
            icon,
            ExtraData(),
        )

    @classmethod
    def create_remote(
        cls,
        unc_path: str,
        description: str | None = None,
        args: str | None = None,
        icon: str | None = None,
        window: ShowCommand = ShowCommand.NORMAL,
    ) -> Lnk:
        """Create a remote (UNC) shortcut with environment block for path expansion."""
        now = datetime.now(tz=dt.UTC)
        flags = LinkFlags.HasLinkInfo | LinkFlags.IsUnicode | LinkFlags.HasExpString
        if description:
            flags |= LinkFlags.HasName
        if args:
            flags |= LinkFlags.HasArguments
        if icon:
            flags |= LinkFlags.HasIconLocation
        # Robust UNC parsing: \\server\share\path\file
        share, tail = ntpath.splitdrive(unc_path)
        share = ntpath.normpath(share)  # e.g. \\server\share
        base = tail.lstrip("\\")  # e.g. "path\file.txt"
        li = LinkInfo(
            remote=True,
            network_share_name=share.upper(),
            base_name=base,
            base_name_unicode=base,
        )
        extra = ExtraData(blocks=[EnvironmentVariableDataBlock(target_ansi=unc_path, target_unicode=unc_path)])
        return cls(
            flags,
            FileAttributes.NORMAL,
            now,
            now,
            now,
            0,
            0,
            window,
            "",
            None,
            li,
            description,
            None,
            None,
            args,
            icon,
            extra,
        )

    @classmethod
    def create_uwp(
        cls,
        package_family_name: str,
        target: str,
        location: str | None = None,
        logo44x44: str | None = None,
        description: str | None = None,
    ) -> Lnk:
        """Create a UWP app shortcut using APPS segment and RootEntry UWP GUID."""
        blocks = [
            UwpMainBlock(
                guid_str=UWP_METADATA_EXEC_GUID,
                sub_blocks=[
                    UwpSubBlock(0x11, package_family_name),
                    UwpSubBlock(0x05, target),
                    *([UwpSubBlock(0x0F, location)] if location else []),
                ],
            )
        ]
        if logo44x44:
            blocks.append(
                UwpMainBlock(
                    guid_str=UWP_LOGO_RESOURCE_GUID,
                    sub_blocks=[UwpSubBlock(0x02, logo44x44)],
                )
            )
        uwp = UwpSegmentEntry(blocks)
        id_list = LinkTargetIDList(items=[RootEntry(UWP_ROOT_APPS_GUID), uwp])
        now = datetime.now(tz=dt.UTC)
        flags = LinkFlags.HasLinkTargetIDList | LinkFlags.IsUnicode | LinkFlags.EnableTargetMetadata
        if description:
            flags |= LinkFlags.HasName
        return cls(
            flags,
            FileAttributes.NORMAL,
            now,
            now,
            now,
            0,
            0,
            ShowCommand.NORMAL,
            "",
            id_list,
            None,
            description,
            None,
            None,
            None,
            None,
            ExtraData(),
        )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------
def resolve_lnk(lnk_path: Path) -> Path:
    """Resolve a .lnk file to its best target path.
    Returns the target Path (may not exist).
    >>> isinstance(resolve_lnk(Path("dummy.lnk")), Path)
    True
    """
    try:
        lnk = Lnk.from_file(lnk_path)
        return Path(lnk.path or "")
    except OSError, LnkError:
        return lnk_path


# ---------------------------------------------------------------------------
# Minimal CLI
# ---------------------------------------------------------------------------
def _cli() -> int:
    if __package__:
        from .cli import run_cli
    else:
        from pylynxley.cli import run_cli

    return run_cli(cast(Any, Lnk), cast(Any, LinkFlags), cast(Any, ShowCommand))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
