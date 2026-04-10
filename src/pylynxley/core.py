"""Core primitives for lnk parsing/writing."""

import datetime as dt
import ntpath
import os
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from enum import IntFlag
from io import BufferedIOBase
from struct import pack
from struct import unpack
from typing import Final

# ---------------------------------------------------------------------------
# Constants (centralized magic values)
# ---------------------------------------------------------------------------
# Top-level .lnk file header signature and CLSID
LNK_SIGNATURE: Final[bytes] = b"L\x00\x00\x00"
SHELL_LINK_CLSID_LE: Final[bytes] = b"\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00F"
# Time/Epoch
FILETIME_UNIX_EPOCH_DIFF_SECONDS: Final[int] = 11_644_473_600  # seconds 1601->1970
# Encoding
ANSI_POLICY_ENV: Final[str] = "PYLNK_ANSI_CODEC"  # optional override, e.g., 'cp1251'
# IDList entry tags & UWP/APPS markers
IDLIST_ROOT_PREFIX: Final[bytes] = b"\x1f\x50"
IDLIST_DRIVE_PREFIX: Final[bytes] = b"\x2f"
APPS_MAGIC: Final[bytes] = b"APPS"
UWP_MAIN_BLOCK_MAGIC: Final[bytes] = b"\x31\x53\x50\x53"  # "1SPS"
APPS_FIXED_HEADER: Final[bytes] = b"\x08\x00\x03\x00\x00\x00\x00\x00\x00\x00"
APPS_FIXED_HEADER_LEN: Final[int] = 10
APPS_HEADER_BASE_LEN: Final[int] = (
    2 + 2 + 4 + 2 + APPS_FIXED_HEADER_LEN
)  # unknown + size + "APPS" + blocks_size + fixed
# DriveEntry binary layout helpers
DRIVE_ENTRY_PADDING_LEN: Final[int] = 19
DRIVE_ENTRY_MIN_LEN: Final[int] = 23  # minimal length expected for a drive entry block
# UWP sub-block string convention
UWP_SUBBLOCK_ZERO_PREFIX: Final[int] = 0
UWP_SUBBLOCK_VT_TAG: Final[int] = 0x1F  # VT_LPWSTR marker in sub-block pattern
# Known GUIDs used for UWP IDList composition
UWP_ROOT_APPS_GUID: Final[str] = "{4234D49B-0245-4DF3-B780-3893943456E1}"
UWP_METADATA_EXEC_GUID: Final[str] = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
UWP_LOGO_RESOURCE_GUID: Final[str] = "{86D40B4D-9069-443C-819A-2A54090DCCEC}"
# Common shell KNOWN_FOLDER GUIDs for pragmatic path resolution
KNOWN_FOLDER_GUID_DESKTOP: Final[str] = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
KNOWN_FOLDER_GUID_DOCUMENTS: Final[str] = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"
KNOWN_FOLDER_GUID_DOWNLOADS: Final[str] = "{374DE290-123F-4565-9164-39C4925E467B}"
KNOWN_FOLDER_GUID_MUSIC: Final[str] = "{4BD8D571-6D19-48D3-BE97-422220080E43}"
KNOWN_FOLDER_GUID_PICTURES: Final[str] = "{33E28130-4E1E-4676-835A-98395C3BC3BB}"
KNOWN_FOLDER_GUID_PROFILE: Final[str] = "{5E6C858F-0E22-4760-9AFE-EA3317B67173}"
KNOWN_FOLDER_GUID_VIDEOS: Final[str] = "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}"
# PathSegmentEntry constants
PATHSEG_ATTR_LEGACY: Final[int] = 0x10
PATHSEG_VER_FIELD_1: Final[int] = 0x03
PATHSEG_VER_FIELD_2: Final[int] = 0x04
PATHSEG_MARKER_BEEF: Final[int] = 0xBEEF
PATHSEG_UNICODE_BLOCK_TAG: Final[int] = 0x14
PATHSEG_INDICATOR_BASE: Final[int] = 24
PATHSEG_OFFSET_PART2_BASE: Final[int] = 0x0E  # used to compute offset_part2
# LinkInfo constants
LINKINFO_HEADER_LEGACY: Final[int] = 0x1C
LINKINFO_HEADER_UNICODE: Final[int] = 0x24
LOCAL_VOLUME_LABEL_OFFSET: Final[int] = 16
REMOTE_SHARE_NAME_OFFSET: Final[int] = 20
REMOTE_PROVIDER_TYPE_SMB: Final[int] = 131_072
# ExtraData constants
EXTRADATA_TERMINATOR: Final[bytes] = b"\x00\x00\x00\x00"
ICON_ENV_ANSI_SIZE: Final[int] = 260
ICON_ENV_UNICODE_SIZE: Final[int] = 520
ENVVAR_ANSI_SIZE: Final[int] = 260
ENVVAR_UNICODE_SIZE: Final[int] = 520
# PropertyStore constants
PROPERTY_STORE_VERSION_SPS1: Final[int] = 0x53505331  # "SPS1"
PROPERTY_STORE_STRING_FORMAT_ID: Final[bytes] = b"\xd5\xcd\xd5\x05\x2e\x9c\x10\x1b\x93\x97\x08\x00\x2b\x2c\xf9\xae"
# Variant types (VT_)
VT_LPWSTR: Final[int] = 0x1F
VT_UI4: Final[int] = 0x13
VT_UI8: Final[int] = 0x15
VT_FILETIME: Final[int] = 0x40
# Hotkey helpers (ranges)
HOTKEY_DIGIT_START: Final[int] = 0x30
HOTKEY_DIGIT_END: Final[int] = 0x3A  # one past '9'
HOTKEY_ALPHA_START: Final[int] = 0x41
HOTKEY_ALPHA_END: Final[int] = 0x5B  # one past 'Z'
HOTKEY_FKEY_BASE: Final[int] = 0x70
HOTKEY_FKEY_COUNT: Final[int] = 24
HOTKEY_NUMLOCK: Final[int] = 0x90
HOTKEY_SCROLLLOCK: Final[int] = 0x91


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class LnkError(Exception):
    """Base class for .lnk errors."""


class LnkFormatError(LnkError):
    """Raised when a file isn't a valid .lnk or contains malformed data."""


class LnkUnsupportedError(LnkError):
    """Raised when encountering a format element not supported."""


class LnkMissingInfoError(LnkError):
    """Raised when required fields are missing to write or interpret."""


# ---------------------------------------------------------------------------
# Constants & Enums
# ---------------------------------------------------------------------------
# Back-compat aliases (retain original private names for minimal code churn)
_SIGNATURE = LNK_SIGNATURE
_GUID = SHELL_LINK_CLSID_LE
FILETIME_EPOCH_DIFF_SECONDS = FILETIME_UNIX_EPOCH_DIFF_SECONDS


class ShowCommand(IntEnum):
    NORMAL = 1
    MAXIMIZED = 3
    MINIMIZED = 7


class DriveType(IntEnum):
    UNKNOWN = 0
    NO_ROOT_DIR = 1
    REMOVABLE = 2
    FIXED = 3
    REMOTE = 4
    CDROM = 5
    RAMDISK = 6


class LinkFlags(IntFlag):
    HasLinkTargetIDList = 1 << 0
    HasLinkInfo = 1 << 1
    HasName = 1 << 2
    HasRelativePath = 1 << 3
    HasWorkingDir = 1 << 4
    HasArguments = 1 << 5
    HasIconLocation = 1 << 6
    IsUnicode = 1 << 7
    ForceNoLinkInfo = 1 << 8
    HasExpString = 1 << 9
    RunInSeparateProcess = 1 << 10
    Unused1 = 1 << 11
    HasDarwinID = 1 << 12
    RunAsUser = 1 << 13
    HasExpIcon = 1 << 14
    NoPidlAlias = 1 << 15
    Unused2 = 1 << 16
    RunWithShimLayer = 1 << 17
    ForceNoLinkTrack = 1 << 18
    EnableTargetMetadata = 1 << 19
    DisableLinkPathTracking = 1 << 20
    DisableKnownFolderTracking = 1 << 21
    DisableKnownFolderAlias = 1 << 22
    AllowLinkToLink = 1 << 23
    UnaliasOnSave = 1 << 24
    PreferEnvironmentPath = 1 << 25
    KeepLocalIDListForUNCTarget = 1 << 26


class FileAttributes(IntFlag):
    READONLY = 1 << 0
    HIDDEN = 1 << 1
    SYSTEM = 1 << 2
    DIRECTORY = 1 << 4
    ARCHIVE = 1 << 5
    NORMAL = 1 << 7
    TEMPORARY = 1 << 8
    SPARSE_FILE = 1 << 9
    REPARSE_POINT = 1 << 10
    COMPRESSED = 1 << 11
    OFFLINE = 1 << 12
    NOT_CONTENT_INDEXED = 1 << 13
    ENCRYPTED = 1 << 14


class ExtraDataType(IntEnum):
    ConsoleDataBlock = 0xA0000002
    ConsoleFEDataBlock = 0xA0000004
    DarwinDataBlock = 0xA0000006
    EnvironmentVariableDataBlock = 0xA0000001
    IconEnvironmentDataBlock = 0xA0000007
    KnownFolderDataBlock = 0xA000000B
    PropertyStoreDataBlock = 0xA0000009
    ShimDataBlock = 0xA0000008
    SpecialFolderDataBlock = 0xA0000005
    VistaAndAboveIDListDataBlock = 0xA0000003
    VistaIDListDataBlock = 0xA000000C


class EntryType(IntEnum):
    KNOWN_FOLDER = 0x00
    FOLDER = 0x31
    FILE = 0x32
    FOLDER_UNICODE = 0x35
    FILE_UNICODE = 0x36
    ROOT_KNOWN_FOLDER = 0x802E


# ---------------------------------------------------------------------------
# Encoding helpers (prefer 'mbcs' first, fallback 'cp1252')
# ---------------------------------------------------------------------------
def decode_ansi(data: bytes) -> str:
    """Decode ANSI-like bytes, preferring 'mbcs' (Windows code page), then 'cp1252'.
    allowing override via env PYLNK_ANSI_CODEC.
    >>> decode_ansi(b"Hello")
    'Hello'
    """
    override = os.getenv(ANSI_POLICY_ENV)
    codecs = [override] if override else ["mbcs", "cp1252"]
    for codec in codecs:
        try:
            return data.decode(codec, errors="replace")
        except LookupError:
            continue
    return data.decode("cp1252", errors="replace")


def encode_ansi(text: str) -> bytes:
    """Encode text as ANSI-like bytes, preferring 'mbcs', then 'cp1252'.
    allowing override via env PYLNK_ANSI_CODEC.
    >>> encode_ansi("Hello").startswith(b"H")
    True
    """
    override = os.getenv(ANSI_POLICY_ENV)
    codecs = [override] if override else ["mbcs", "cp1252"]
    for codec in codecs:
        try:
            return text.encode(codec, errors="replace")
        except LookupError:
            continue
    return text.encode("cp1252", errors="replace")


# ---------------------------------------------------------------------------
# Binary Reader/Writer
# ---------------------------------------------------------------------------
@dataclass
class BinReader:
    """Little-endian binary reader."""

    buf: BufferedIOBase

    def read_u8(self) -> int:
        return unpack("<B", self.buf.read(1))[0]

    def read_u16(self) -> int:
        return unpack("<H", self.buf.read(2))[0]

    def read_u32(self) -> int:
        return unpack("<I", self.buf.read(4))[0]

    def read_u64(self) -> int:
        return unpack("<Q", self.buf.read(8))[0]

    def read_bytes(self, n: int) -> bytes:
        """Read exactly n bytes."""
        data = self.buf.read(n)
        if len(data) != n:
            msg = f"Expected {n} bytes, got {len(data)}"
            raise LnkFormatError(msg)
        return data

    def read_cstring(self, padding_even: bool = False) -> str:
        r"""Read a zero-terminated ANSI-like string.
        >>> import io
        >>> br = BinReader(io.BytesIO(b"A\x00"))
        >>> br.read_cstring()
        'A'
        """
        out = bytearray()
        while True:
            b = self.buf.read(1)
            if not b or b == b"\x00":
                break
            out.extend(b)
        # Pad one extra byte iff (len + NUL) is odd to align to 2-byte boundary
        if padding_even and ((len(out) + 1) % 2 == 1):
            _ = self.buf.read(1)
        return decode_ansi(bytes(out))

    def read_cunicode(self) -> str:
        r"""Read a zero-terminated UTF-16-LE string.
        >>> import io
        >>> br = BinReader(io.BytesIO("X\x00\x00\x00".encode("utf-16-le")))
        >>> br.read_cunicode()
        'X'
        """
        out = bytearray()
        while True:
            chunk = self.buf.read(2)
            if chunk == b"\x00\x00" or not chunk:
                break
            out.extend(chunk)
        return out.decode("utf-16-le", errors="replace")

    def read_sized_string(self, is_unicode: bool) -> str:
        """Read a sized string (size includes terminator per spec).
        For Unicode, size is in *characters* (code units), including the
        terminating null. For ANSI, size is in bytes, including the terminating null.
        >>> import io
        >>> s = "Hi"
        >>> data = pack("<H", len(s) + 1) + s.encode("utf-16-le") + bytes(2)
        >>> br = BinReader(io.BytesIO(data))
        >>> br.read_sized_string(is_unicode=True)
        'Hi'
        """
        size = self.read_u16()
        if is_unicode:
            raw = self.read_bytes(size * 2)
            text = raw.decode("utf-16-le", errors="replace")
            return text.removesuffix("\x00")
        raw = self.read_bytes(size)
        text = decode_ansi(raw)
        return text.removesuffix("\x00")


@dataclass
class BinWriter:
    """Little-endian binary writer."""

    buf: BufferedIOBase

    def write_u8(self, v: int) -> None:
        self.buf.write(pack("<B", v))

    def write_u16(self, v: int) -> None:
        self.buf.write(pack("<H", v))

    def write_u32(self, v: int) -> None:
        self.buf.write(pack("<I", v))

    def write_u64(self, v: int) -> None:
        self.buf.write(pack("<Q", v))

    def write_bytes(self, b: bytes) -> None:
        self.buf.write(b)

    def write_cstring(self, s: str, padding_even: bool = False) -> None:
        """Write zero-terminated ANSI-like string."""
        b = encode_ansi(s)
        self.buf.write(b + b"\x00")
        # Pad one extra byte iff (len + NUL) is odd to align to 2-byte boundary
        if padding_even and ((len(b) + 1) % 2 == 1):
            self.buf.write(b"\x00")

    def write_cunicode(self, s: str) -> None:
        """Write zero-terminated UTF-16-LE string."""
        self.buf.write(s.encode("utf-16-le") + b"\x00\x00")

    def write_sized_string(self, s: str, is_unicode: bool) -> None:
        """Write sized string with length including terminator per spec."""
        if is_unicode:
            size_chars = len(s) + 1
            self.write_u16(size_chars)
            self.buf.write(s.encode("utf-16-le"))
            self.buf.write(b"\x00\x00")
        else:
            b = encode_ansi(s)
            size_bytes = len(b) + 1
            self.write_u16(size_bytes)
            self.buf.write(b + b"\x00")


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def filetime_to_datetime(filetime: int) -> datetime:
    """Convert Windows FILETIME ticks to local datetime.
    >>> isinstance(filetime_to_datetime(0), datetime)
    True
    """
    unix_seconds = filetime / 10_000_000 - FILETIME_EPOCH_DIFF_SECONDS
    # Use epoch + timedelta to avoid Windows fromtimestamp() range issues
    return datetime(1970, 1, 1, tzinfo=dt.UTC) + dt.timedelta(seconds=unix_seconds)


def datetime_to_filetime(dt_or_seconds: float | datetime) -> int:
    """Convert local naive datetime or UNIX seconds to Windows FILETIME ticks.
    >>> dtv = datetime(2020, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
    >>> isinstance(datetime_to_filetime(dtv), int)
    True
    """
    seconds = dt_or_seconds.timestamp() if isinstance(dt_or_seconds, datetime) else float(dt_or_seconds)
    return int((seconds + FILETIME_EPOCH_DIFF_SECONDS) * 10_000_000)


# ---------------------------------------------------------------------------
# ID List entries & parsing (Root/Drive/Path/UWP)
# ---------------------------------------------------------------------------
def _guid_from_bytes(bs: bytes) -> str:
    """Convert 16-byte GUID to canonical string."""
    if len(bs) != 16:  # noqa: PLR2004
        msg = "Invalid GUID length."
        raise LnkFormatError(msg)
    ordered = [
        bs[3],
        bs[2],
        bs[1],
        bs[0],
        bs[5],
        bs[4],
        bs[7],
        bs[6],
        bs[8],
        bs[9],
        bs[10],
        bs[11],
        bs[12],
        bs[13],
        bs[14],
        bs[15],
    ]
    return "{{{:02X}{:02X}{:02X}{:02X}-{:02X}{:02X}-{:02X}{:02X}-{:02X}{:02X}-{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}}}".format(  # noqa: E501
        *tuple(ordered)
    )


def _bytes_from_guid(guid: str) -> bytes:
    """Convert canonical GUID str to 16 bytes in little-endian on first three fields."""
    hexs = guid[1:-1].replace("-", "")
    if len(hexs) != 32:
        msg = "Invalid GUID format."
        raise LnkFormatError(msg)
    raw = bytes(int(hexs[i : i + 2], 16) for i in range(0, 32, 2))
    return raw[3::-1] + raw[5:3:-1] + raw[7:5:-1] + raw[8:]


def _extract_first_guid_from_bytes(bs: bytes) -> str | None:
    """Scan bytes for a 16-byte GUID in mixed-endian format and return canonical '{GUID}'."""
    # We attempt every 16-byte window; if parsing succeeds we return the found GUID.
    for i in range(max(0, len(bs) - 16) + 1):
        chunk = bs[i : i + 16]
        if len(chunk) != 16:  # noqa: PLR2004  # pragma: no cover
            continue
        try:
            return _guid_from_bytes(chunk)
        except LnkFormatError:
            continue
    return None


def _resolve_known_folder_canonical(path: str) -> str | None:
    """Resolve canonical KNOWN_FOLDER path (e.g. '::{GUID}\\...') to filesystem path.

    Falls back to None for unknown GUIDs or if required env vars are unavailable.
    """
    if not path.startswith("::{"):
        return None
    end = path.find("}")
    if end < 0:
        return None
    guid = path[2 : end + 1].upper()
    tail = path[end + 1 :].lstrip("\\")
    user_profile = os.getenv("USERPROFILE")
    base_map = {
        KNOWN_FOLDER_GUID_DESKTOP: (ntpath.join(user_profile, "Desktop") if user_profile else None),
        KNOWN_FOLDER_GUID_DOCUMENTS: (ntpath.join(user_profile, "Documents") if user_profile else None),
        KNOWN_FOLDER_GUID_DOWNLOADS: (ntpath.join(user_profile, "Downloads") if user_profile else None),
        KNOWN_FOLDER_GUID_MUSIC: (ntpath.join(user_profile, "Music") if user_profile else None),
        KNOWN_FOLDER_GUID_PICTURES: (ntpath.join(user_profile, "Pictures") if user_profile else None),
        KNOWN_FOLDER_GUID_PROFILE: user_profile,
        KNOWN_FOLDER_GUID_VIDEOS: (ntpath.join(user_profile, "Videos") if user_profile else None),
    }
    base = base_map.get(guid)
    if not base:
        return None
    return ntpath.normpath(ntpath.join(base, tail)) if tail else ntpath.normpath(base)
