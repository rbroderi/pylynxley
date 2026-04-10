# pyright: reportPrivateUsage=false

"""ID list entries and parsing."""

import datetime as dt
import ntpath
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from struct import error as StructError

from .core import APPS_MAGIC
from .core import DRIVE_ENTRY_MIN_LEN
from .core import DRIVE_ENTRY_PADDING_LEN
from .core import IDLIST_DRIVE_PREFIX
from .core import IDLIST_ROOT_PREFIX
from .core import PATHSEG_ATTR_LEGACY
from .core import PATHSEG_INDICATOR_BASE
from .core import PATHSEG_MARKER_BEEF
from .core import PATHSEG_OFFSET_PART2_BASE
from .core import PATHSEG_UNICODE_BLOCK_TAG
from .core import PATHSEG_VER_FIELD_1
from .core import PATHSEG_VER_FIELD_2
from .core import BinReader
from .core import BinWriter
from .core import EntryType
from .core import LnkFormatError
from .core import LnkUnsupportedError
from .core import _bytes_from_guid
from .core import _guid_from_bytes
from .uwp import UwpSegmentEntry


@dataclass
class RootEntry:
    guid_str: str  # "{GUID}"

    @classmethod
    def from_bytes(cls, data: bytes) -> RootEntry:
        """Parse RootEntry (starts with 0x1F 0x50)."""
        if not data.startswith(IDLIST_ROOT_PREFIX):
            msg = "Not a RootEntry block."
            raise LnkFormatError(msg)
        # next 16 bytes are GUID in mixed-endian per spec
        guid = _guid_from_bytes(data[2:18])
        return cls(guid)

    def to_bytes(self) -> bytes:
        guid_le = _bytes_from_guid(self.guid_str)
        return IDLIST_ROOT_PREFIX + guid_le


@dataclass
class DriveEntry:
    drive: str  # e.g., "C:"

    @classmethod
    def from_bytes(cls, data: bytes) -> DriveEntry:
        r"""Parse a DriveEntry (0x2F + 'C' ':' '\' + padding)."""
        if not data.startswith(IDLIST_DRIVE_PREFIX) or len(data) < DRIVE_ENTRY_MIN_LEN:
            msg = "Not a DriveEntry block."
            raise LnkFormatError(msg)
        drive = data[1:3].decode(errors="replace")
        return cls(drive)

    def to_bytes(self) -> bytes:
        d = (self.drive if self.drive.endswith(":") else self.drive + ":").encode()
        return IDLIST_DRIVE_PREFIX + d + b"\\" + b"\x00" * DRIVE_ENTRY_PADDING_LEN


@dataclass
class PathSegmentEntry:
    entry_type: EntryType
    file_size: int = 0
    modified: datetime = field(default_factory=datetime.now)
    created: datetime = field(default_factory=datetime.now)
    accessed: datetime = field(default_factory=datetime.now)
    short_name: str = ""
    full_name: str = ""

    @classmethod
    def for_path(cls, path: str) -> PathSegmentEntry:
        r"""Create a PathSegmentEntry from a filesystem path.
        >>> e = PathSegmentEntry.for_path(r"C:\Windows")
        >>> isinstance(e, PathSegmentEntry)
        True
        """
        path_p = Path(path)
        et = EntryType.FOLDER if path_p.is_dir() else EntryType.FILE
        try:
            st = path_p.stat()
            size = st.st_size
            m = datetime.fromtimestamp(st.st_mtime, tz=dt.UTC)
            c = datetime.fromtimestamp(st.st_ctime, tz=dt.UTC)
            a = datetime.fromtimestamp(st.st_atime, tz=dt.UTC)
        except FileNotFoundError:
            size = 0
            m = c = a = datetime.now(tz=dt.UTC)
        name = ntpath.basename(path) or path
        return cls(
            entry_type=et,
            file_size=size,
            modified=m,
            created=c,
            accessed=a,
            short_name=name,
            full_name=name,
        )

    @staticmethod
    def _write_dos_datetime(bw: BinWriter, dt: datetime) -> None:
        date = (dt.year - 1980) << 9 | dt.month << 5 | dt.day
        time = dt.hour << 11 | dt.minute << 5 | (dt.second // 2)
        bw.write_u16(date)
        bw.write_u16(time)

    def to_bytes(self) -> bytes:
        """Serialize PathSegmentEntry."""
        out = BytesIO()
        bw = BinWriter(out)
        bw.write_u16(self.entry_type)
        if self.entry_type in (EntryType.KNOWN_FOLDER, EntryType.ROOT_KNOWN_FOLDER):
            msg = "KNOWN_FOLDER serialization is preserved via raw ID list entries."
            raise LnkUnsupportedError(msg)
        bw.write_u32(self.file_size)
        self._write_dos_datetime(bw, self.modified)
        bw.write_u16(PATHSEG_ATTR_LEGACY)
        bw.write_cstring(self.short_name, padding_even=True)
        indicator = PATHSEG_INDICATOR_BASE + 2 * len(self.short_name)
        bw.write_u16(indicator)
        bw.write_u16(PATHSEG_VER_FIELD_1)
        bw.write_u16(PATHSEG_VER_FIELD_2)
        bw.write_u16(PATHSEG_MARKER_BEEF)
        self._write_dos_datetime(bw, self.created)
        self._write_dos_datetime(bw, self.accessed)
        bw.write_u16(PATHSEG_UNICODE_BLOCK_TAG)
        bw.write_u16(0x00)
        bw.write_cunicode(self.full_name)
        offset_part2 = PATHSEG_OFFSET_PART2_BASE + (len(self.short_name) + 1) + ((len(self.short_name) + 1) % 2)
        bw.write_u16(offset_part2)
        return out.getvalue()


@dataclass
class RawIdListItem:
    """Raw SHITEMID entry we don't interpret but must round-trip."""

    raw: bytes

    def to_bytes(self) -> bytes:
        return self.raw


@dataclass
class LinkTargetIDList:
    items: list[RootEntry | DriveEntry | PathSegmentEntry | UwpSegmentEntry | RawIdListItem] = field(
        default_factory=list
    )

    def to_bytes(self) -> bytes:
        out = BytesIO()
        bw = BinWriter(out)
        for item in self.items:
            data = item.to_bytes()
            bw.write_u16(len(data) + 2)
            bw.write_bytes(data)
        bw.write_u16(0)
        return out.getvalue()

    def get_path(self) -> str | None:
        if not self.items:
            return None
        parts: list[str] = []
        drive: str | None = None
        root_guid: str | None = None
        for item in self.items:
            if isinstance(item, DriveEntry):
                drive = item.drive
            elif isinstance(item, RootEntry):
                root_guid = item.guid_str  # e.g. "{374DE290-...}"
            elif isinstance(item, PathSegmentEntry):
                name = item.full_name or item.short_name
                parts.append(name)
        if drive:
            # If there are path segments, compose them; otherwise return the root of
            # the drive
            return drive + ("\\" + "\\".join(parts) if parts else "\\")
        if root_guid:
            # KNOWN_FOLDER canonical shell path
            return f"::{{{root_guid.strip('{}')}}}" + ("\\" + "\\".join(parts) if parts else "")
        return "\\".join(parts) if parts else None


def _dos_datetime_to_utc(date_word: int, time_word: int) -> datetime:
    year = ((date_word >> 9) & 0x7F) + 1980
    month = (date_word >> 5) & 0x0F
    day = date_word & 0x1F
    hour = (time_word >> 11) & 0x1F
    minute = (time_word >> 5) & 0x3F
    second = (time_word & 0x1F) * 2
    return datetime(year, max(month, 1), max(day, 1), hour, minute, second, tzinfo=dt.UTC)


def _read_dos_datetime(br: BinReader) -> datetime:
    return _dos_datetime_to_utc(br.read_u16(), br.read_u16())


def _parse_root_or_raw(payload: bytes) -> RootEntry | RawIdListItem:
    try:
        return RootEntry.from_bytes(payload)
    except LnkFormatError:
        return RawIdListItem(payload)


def _parse_path_segment_or_raw(payload: bytes) -> PathSegmentEntry | RawIdListItem:
    try:
        pbr = BinReader(BytesIO(payload))
        et = EntryType(pbr.read_u16())
        if et in (EntryType.KNOWN_FOLDER, EntryType.ROOT_KNOWN_FOLDER):
            return RawIdListItem(payload)
        file_size = pbr.read_u32()
        modified = _read_dos_datetime(pbr)
        _attrs = pbr.read_u16()
        short_name = pbr.read_cstring(padding_even=True)
        _indicator = pbr.read_u16()
        _ver = pbr.read_u16()
        _s1 = pbr.read_u16()
        _s2 = pbr.read_u16()
        created = _read_dos_datetime(pbr)
        accessed = _read_dos_datetime(pbr)
        _off_u = pbr.read_u16()
        _off_a = pbr.read_u16()
        full_name = pbr.read_cunicode()
        _off_p2 = pbr.read_u16()
        return PathSegmentEntry(
            entry_type=et,
            file_size=file_size,
            modified=modified,
            created=created,
            accessed=accessed,
            short_name=short_name,
            full_name=full_name,
        )
    except LnkFormatError, ValueError, UnicodeDecodeError, StructError:
        return RawIdListItem(payload)


def _parse_id_item(
    payload: bytes,
) -> RootEntry | DriveEntry | UwpSegmentEntry | PathSegmentEntry | RawIdListItem:
    if payload.startswith(IDLIST_ROOT_PREFIX):
        return _parse_root_or_raw(payload)
    if payload.startswith(IDLIST_DRIVE_PREFIX):
        return DriveEntry.from_bytes(payload)
    if payload[4:8] == APPS_MAGIC:
        return UwpSegmentEntry.from_bytes(payload)
    return _parse_path_segment_or_raw(payload)


def parse_id_list(raw: bytes) -> LinkTargetIDList:
    r"""Parse ID list bytes into entries (Root/Drive/Path/UWP).
    >>> d = DriveEntry("C:")
    >>> p = PathSegmentEntry.for_path(r"C:\Temp")
    >>> data = LinkTargetIDList([d, p]).to_bytes()
    >>> out = parse_id_list(data)
    >>> isinstance(out, LinkTargetIDList)
    True
    """
    br = BinReader(BytesIO(raw))
    items: list[RootEntry | DriveEntry | UwpSegmentEntry | PathSegmentEntry | RawIdListItem] = []
    while True:
        size = br.read_u16()
        if size == 0:
            break
        payload = br.read_bytes(size - 2)
        if not payload:
            continue
        items.append(_parse_id_item(payload))
    return LinkTargetIDList(items)


# ---------------------------------------------------------------------------
# LinkInfo (+ optional header >= 0x24 with Unicode offsets)
# ---------------------------------------------------------------------------
