# pyright: reportPrivateUsage=false

"""UWP APPS segment parsing and serialization."""

import contextlib
from dataclasses import dataclass
from dataclasses import field
from io import BytesIO
from struct import pack
from typing import Final

from .core import APPS_FIXED_HEADER
from .core import APPS_FIXED_HEADER_LEN
from .core import APPS_HEADER_BASE_LEN
from .core import APPS_MAGIC
from .core import UWP_MAIN_BLOCK_MAGIC
from .core import UWP_SUBBLOCK_VT_TAG
from .core import UWP_SUBBLOCK_ZERO_PREFIX
from .core import BinReader
from .core import BinWriter
from .core import LnkFormatError
from .core import _bytes_from_guid
from .core import _guid_from_bytes


@dataclass
class UwpSubBlock:
    type_id: int
    value: str | bytes
    raw_payload: bytes | None = None

    @classmethod
    def from_bytes(cls, br: BinReader) -> "UwpSubBlock":
        t = br.read_u8()
        # Capture the payload after type byte so unknown layouts can still round-trip.
        tail = br.buf.read()
        tbr = BinReader(BytesIO(tail))
        # Common string variant:
        #   u32(0), u32(0x1f), u32(length), utf-16-le string (+ optional pad)
        if len(tail) >= 12:
            prefix0 = tbr.read_u32()
            vt = tbr.read_u32()
            if prefix0 == UWP_SUBBLOCK_ZERO_PREFIX and vt == UWP_SUBBLOCK_VT_TAG:
                length = tbr.read_u32()
                val = tbr.read_cunicode()
                if length % 2 == 1 and tbr.buf.tell() + 2 <= len(tail):
                    _ = tbr.read_u16()
                return cls(t, val, None)
        # Unknown layout: keep raw bytes for lossless write-back.
        return cls(t, tail, tail)

    def to_bytes(self) -> bytes:
        out = BytesIO()
        bw = BinWriter(out)
        if isinstance(self.value, str):
            bw.write_u8(self.type_id)
            bw.write_u32(UWP_SUBBLOCK_ZERO_PREFIX)
            bw.write_u32(UWP_SUBBLOCK_VT_TAG)
            bw.write_u32(len(self.value) + 1)
            bw.write_cunicode(self.value)
            if (len(self.value) + 1) % 2 == 1:
                bw.write_u16(0)
        else:
            # Raw non-string payload is serialized exactly as parsed.
            bw.write_u8(self.type_id)
            bw.write_bytes(self.value)
        return out.getvalue()


@dataclass
class UwpMainBlock:
    guid_str: str
    sub_blocks: list[UwpSubBlock] = field(default_factory=list)
    raw_payload: bytes | None = None

    @classmethod
    def from_bytes(cls, br: BinReader) -> "UwpMainBlock":
        raw_payload = br.buf.read()
        br = BinReader(BytesIO(raw_payload))
        # Validate magic header: expected b'\x31\x53\x50\x53' ("1SPS")
        magic = br.read_bytes(4)
        if magic != UWP_MAIN_BLOCK_MAGIC:
            msg = "Invalid UWP main block magic; expected b'1SPS'."
            raise LnkFormatError(msg)
        guid = _guid_from_bytes(br.read_bytes(16))
        subs: list[UwpSubBlock] = []
        while True:
            size = br.read_u32()
            if size == 0:
                break
            payload = br.read_bytes(size - 4)
            subs.append(UwpSubBlock.from_bytes(BinReader(BytesIO(payload))))
        return cls(guid, subs, raw_payload)

    def to_bytes(self) -> bytes:
        out = BytesIO()
        bw = BinWriter(out)
        bw.write_bytes(UWP_MAIN_BLOCK_MAGIC)
        bw.write_bytes(_bytes_from_guid(self.guid_str))
        for sb in self.sub_blocks:
            data = sb.to_bytes()
            bw.write_u32(len(data) + 4)
            bw.write_bytes(data)
        bw.write_u32(0)
        return out.getvalue()


@dataclass
class UwpSegmentEntry:
    main_blocks: list[UwpMainBlock] = field(default_factory=list)

    @classmethod
    def from_bytes(cls, data: bytes) -> "UwpSegmentEntry":
        r"""Parse a UWP APPS segment with sanity checks on header and blocks region.
        Layout (minimum):
          - 2 bytes: unknown
          - 2 bytes: seg size(header-level, not always strictly enforced by creators)
          - 4 bytes: magic "APPS"
          - 2 bytes: blocks_size (size of blocks region incl. 4-byte terminator)
          - 10 bytes: fixed header bytes
          - blocks region: sequence of [u32 size][payload] ... [u32 0]
          - optional trailing u16 0x0000
        Sanity checks ensure header size and blocks_size are consistent with the buffer.
        >>> # Minimal sanity doctest: construct an empty APPS segment
        >>> import io
        >>> from struct import pack
        >>> hdr = (
        ...     pack("<H", 0)
        ...     + pack("<H", 20)
        ...     + b"APPS"
        ...     + pack("<H", 4)
        ...     + b"\x08\x00\x03\x00\x00\x00\x00\x00\x00\x00"
        ... )
        >>> blocks = pack("<I", 0)
        >>> seg_bytes = hdr + blocks
        >>> UwpSegmentEntry.from_bytes(seg_bytes)  # should parse with no blocks
        UwpSegmentEntry(main_blocks=[])
        """
        br = BinReader(BytesIO(data))
        _unknown = br.read_u16()
        _size = br.read_u16()
        magic = br.read_bytes(4)
        if magic != APPS_MAGIC:
            msg = "Not a UWP APPS segment (magic mismatch)."
            raise LnkFormatError(msg)
        _blocks_size = br.read_u16()
        _hdr = br.read_bytes(APPS_FIXED_HEADER_LEN)
        total_len = len(data)
        min_header_len = APPS_HEADER_BASE_LEN
        # --- Sanity checks on header/size fields ---
        if _size < min_header_len:
            msg_0 = f"APPS segment too small: header size={_size}, expected >= {min_header_len}"
            raise LnkFormatError(msg_0)
        if _size > total_len:
            msg_1 = f"APPS segment size ({_size}) exceeds buffer length ({total_len})"
            raise LnkFormatError(msg_1)
        # Remaining bytes after fixed header
        remaining = total_len - min_header_len
        if _blocks_size > remaining:
            msg_2 = f"Blocks region size ({_blocks_size}) exceeds available bytes({remaining}) after header"
            raise LnkFormatError(msg_2)
        # Read exactly blocks_size bytes for block parsing
        blocks_region = br.read_bytes(_blocks_size)
        bbr = BinReader(BytesIO(blocks_region))
        blocks: list[UwpMainBlock] = []
        consumed = 0
        apps_block_header_size: Final[int] = 4  # u32 length field (includes itself)
        while True:
            # Ensure we can read the next block header (u32 size)
            if consumed + 4 > _blocks_size:
                msg_3 = "UWP APPS block header overruns blocks_size"
                raise LnkFormatError(msg_3)
            bsize = bbr.read_u32()
            consumed += 4
            if bsize == 0:
                # Proper terminator found
                break
            if bsize < apps_block_header_size:
                msg_4 = f"Invalid UWP sub-block size ({bsize}); must be >= 4"
                raise LnkFormatError(msg_4)
            payload_len = bsize - 4
            if consumed + payload_len > _blocks_size:
                msg_5 = (
                    f"UWP sub-block payload overruns blocks_size: "
                    f"bsize={bsize}, consumed={consumed}, blocks_size={_blocks_size}"
                )
                raise LnkFormatError(msg_5)
            payload = bbr.read_bytes(payload_len)
            consumed += payload_len
            # Parse the main block inside this sub-block payload
            blocks.append(UwpMainBlock.from_bytes(BinReader(BytesIO(payload))))
        # Optional trailing u16 (often 0x0000) after terminator: ignore if present
        # Only attempt to read if there are at least 2 bytes left.
        remaining = _blocks_size - consumed
        if remaining >= 2:  # noqa: PLR2004
            with contextlib.suppress(LnkFormatError):
                _tail = bbr.read_u16()
        return cls(blocks)

    def to_bytes(self) -> bytes:
        out = BytesIO()
        bw = BinWriter(out)
        # header
        bw.write_u16(0)
        # blocks region = encoded blocks + u32 terminator
        blocks_bytes: list[bytes] = []
        for mb in self.main_blocks:
            data = mb.to_bytes()
            blocks_bytes.append(pack("<I", len(data) + 4) + data)
        blocks_size = sum(len(b) for b in blocks_bytes) + 4
        total_size = APPS_HEADER_BASE_LEN + blocks_size
        bw.write_u16(total_size)
        bw.write_bytes(APPS_MAGIC)
        bw.write_u16(blocks_size)
        bw.write_bytes(APPS_FIXED_HEADER)
        for b in blocks_bytes:
            bw.write_bytes(b)
        bw.write_u32(0)  # blocks terminator
        return out.getvalue()
