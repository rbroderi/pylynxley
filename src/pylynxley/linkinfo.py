"""LinkInfo structure parsing and writing."""

from dataclasses import dataclass
from struct import unpack

from .core import LINKINFO_HEADER_LEGACY
from .core import LINKINFO_HEADER_UNICODE
from .core import LOCAL_VOLUME_LABEL_OFFSET
from .core import REMOTE_PROVIDER_TYPE_SMB
from .core import REMOTE_SHARE_NAME_OFFSET
from .core import BinReader
from .core import BinWriter
from .core import DriveType
from .core import decode_ansi


@dataclass
class LinkInfo:
    local: bool = False
    remote: bool = False
    drive_type: DriveType | None = None
    drive_serial: int | None = None
    volume_label: str | None = None
    local_base_path: str | None = None
    local_base_path_unicode: str | None = None
    network_share_name: str | None = None
    base_name: str | None = None
    base_name_unicode: str | None = None

    def path(self) -> str | None:
        # Prefer a concrete local base path if present
        if self.local_base_path_unicode or self.local_base_path:
            return self.local_base_path_unicode or self.local_base_path
        # If we have a network share name, return UNC even if BaseName is empty
        if self.network_share_name:
            tail = self.base_name or self.base_name_unicode
            return f"{self.network_share_name}\\{tail}" if tail else self.network_share_name
        return None

    @staticmethod
    def _read_header(
        br: BinReader,
    ) -> tuple[int, int, int, int, int, int, int, int, int]:
        size = br.read_u32()
        header_size = br.read_u32()
        flags = br.read_u32()
        offs_local_volume = br.read_u32()
        offs_local_base = br.read_u32()
        offs_network_vol = br.read_u32()
        offs_base_name = br.read_u32()
        offs_local_base_unicode = offs_base_name_unicode = 0
        if header_size >= LINKINFO_HEADER_UNICODE:
            offs_local_base_unicode = br.read_u32()
            offs_base_name_unicode = br.read_u32()
        return (
            size,
            header_size,
            flags,
            offs_local_volume,
            offs_local_base,
            offs_network_vol,
            offs_base_name,
            offs_local_base_unicode,
            offs_base_name_unicode,
        )

    @staticmethod
    def _read_cstr_at(payload: bytes, base: int, offset: int) -> str:
        rel = offset - base
        if rel < 0 or rel >= len(payload):
            return ""
        end = payload.find(b"\x00", rel)
        if end < 0:
            end = len(payload)
        return decode_ansi(payload[rel:end])

    @staticmethod
    def _read_cuni_at(payload: bytes, base: int, offset: int) -> str:
        rel = offset - base
        if rel < 0 or rel >= len(payload):
            return ""
        out = bytearray()
        i = rel
        while i + 1 < len(payload):
            chunk = payload[i : i + 2]
            if chunk == b"\x00\x00":
                break
            out.extend(chunk)
            i += 2
        return out.decode("utf-16-le", errors="replace")

    @classmethod
    def _populate_local_fields(
        cls,
        li: LinkInfo,
        payload: bytes,
        base: int,
        offs_local_volume: int,
        offs_local_base: int,
        offs_local_base_unicode: int,
    ) -> None:
        if offs_local_base:
            li.local_base_path = cls._read_cstr_at(payload, base, offs_local_base)
        if offs_local_base_unicode:
            li.local_base_path_unicode = cls._read_cuni_at(payload, base, offs_local_base_unicode)
        if not offs_local_volume:
            return
        rel = offs_local_volume - base
        if rel + 16 > len(payload):
            return
        dt_val = unpack("<I", payload[rel + 4 : rel + 8])[0]
        li.drive_type = DriveType(dt_val) if dt_val in DriveType._value2member_map_ else DriveType.UNKNOWN
        li.drive_serial = unpack("<I", payload[rel + 8 : rel + 12])[0]
        label_rel_offs = unpack("<I", payload[rel + 12 : rel + 16])[0]
        li.volume_label = cls._read_cstr_at(payload, base, offs_local_volume + label_rel_offs)

    @classmethod
    def _populate_remote_fields(
        cls,
        li: LinkInfo,
        payload: bytes,
        base: int,
        offs_network_vol: int,
        offs_base_name: int,
        offs_base_name_unicode: int,
    ) -> None:
        if offs_network_vol:
            li.network_share_name = cls._read_cstr_at(payload, base, offs_network_vol + REMOTE_SHARE_NAME_OFFSET)
        if offs_base_name:
            li.base_name = cls._read_cstr_at(payload, base, offs_base_name)
        if offs_base_name_unicode:
            li.base_name_unicode = cls._read_cuni_at(payload, base, offs_base_name_unicode)

    @classmethod
    def read(cls, br: BinReader) -> LinkInfo:
        """Read LinkInfo; offsets are relative to start of the LinkInfo structure."""
        (
            size,
            header_size,
            flags,
            offs_local_volume,
            offs_local_base,
            offs_network_vol,
            offs_base_name,
            offs_local_base_unicode,
            offs_base_name_unicode,
        ) = cls._read_header(br)
        payload = br.read_bytes(size - header_size)
        li = cls(local=bool(flags & 1), remote=bool(flags & 2))
        if li.local:
            cls._populate_local_fields(
                li,
                payload,
                header_size,
                offs_local_volume,
                offs_local_base,
                offs_local_base_unicode,
            )
        if li.remote:
            cls._populate_remote_fields(
                li,
                payload,
                header_size,
                offs_network_vol,
                offs_base_name,
                offs_base_name_unicode,
            )
        return li

    @staticmethod
    def _write_header_placeholders(
        bw: BinWriter, header_size: int, flags: int, include_unicode: bool
    ) -> tuple[int, int, int, int, int, int, int | None, int | None]:
        start_pos = bw.buf.tell()
        size_pos = bw.buf.tell()
        bw.write_u32(0)
        bw.write_u32(header_size)
        bw.write_u32(flags)
        off_local_vol_pos = bw.buf.tell()
        bw.write_u32(0)
        off_local_base_pos = bw.buf.tell()
        bw.write_u32(0)
        off_network_vol_pos = bw.buf.tell()
        bw.write_u32(0)
        off_base_name_pos = bw.buf.tell()
        bw.write_u32(0)
        off_local_base_u_pos = off_base_name_u_pos = None
        if include_unicode:
            off_local_base_u_pos = bw.buf.tell()
            bw.write_u32(0)
            off_base_name_u_pos = bw.buf.tell()
            bw.write_u32(0)
        return (
            start_pos,
            size_pos,
            off_local_vol_pos,
            off_local_base_pos,
            off_network_vol_pos,
            off_base_name_pos,
            off_local_base_u_pos,
            off_base_name_u_pos,
        )

    def _write_local_payload(self, bw: BinWriter, start_pos: int, include_unicode: bool) -> tuple[int, int, int]:
        if not self.local:
            return 0, 0, 0
        off_local_vol = bw.buf.tell() - start_pos
        vol_start = bw.buf.tell()
        bw.write_u32(0)
        bw.write_u32(int(self.drive_type or DriveType.UNKNOWN))
        bw.write_u32(self.drive_serial or 0)
        bw.write_u32(LOCAL_VOLUME_LABEL_OFFSET)
        bw.write_cstring(self.volume_label or "", padding_even=False)
        vol_end = bw.buf.tell()
        cur = bw.buf.tell()
        bw.buf.seek(vol_start)
        BinWriter(bw.buf).write_u32(vol_end - vol_start)
        bw.buf.seek(cur)
        off_local_base = bw.buf.tell() - start_pos
        bw.write_cstring(self.local_base_path or "", padding_even=False)
        off_local_base_u = 0
        if include_unicode:
            off_local_base_u = bw.buf.tell() - start_pos
            bw.write_cunicode(self.local_base_path_unicode or (self.local_base_path or ""))
        return off_local_vol, off_local_base, off_local_base_u

    def _write_remote_payload(self, bw: BinWriter, start_pos: int, include_unicode: bool) -> tuple[int, int, int]:
        if not self.remote:
            return 0, 0, 0
        off_network_vol = bw.buf.tell() - start_pos
        share = self.network_share_name or ""
        cnrl_size = REMOTE_SHARE_NAME_OFFSET + len(share) + 1
        bw.write_u32(cnrl_size)
        bw.write_u32(2)
        bw.write_u32(REMOTE_SHARE_NAME_OFFSET)
        bw.write_u32(0)
        bw.write_u32(REMOTE_PROVIDER_TYPE_SMB)
        bw.write_cstring(share, padding_even=False)
        off_base_name = bw.buf.tell() - start_pos
        base = self.base_name or ""
        bw.write_cstring(base, padding_even=False)
        off_base_name_u = 0
        if include_unicode:
            off_base_name_u = bw.buf.tell() - start_pos
            bw.write_cunicode(self.base_name_unicode or base)
        return off_network_vol, off_base_name, off_base_name_u

    @staticmethod
    def _patch_header_offsets(
        bw: BinWriter,
        positions: tuple[int, int, int, int, int, int, int | None, int | None],
        off_local_vol: int,
        off_local_base: int,
        off_network_vol: int,
        off_base_name: int,
        off_local_base_u: int,
        off_base_name_u: int,
        include_unicode: bool,
    ) -> None:
        (
            _,
            _,
            off_local_vol_pos,
            off_local_base_pos,
            off_network_vol_pos,
            off_base_name_pos,
            off_local_base_u_pos,
            off_base_name_u_pos,
        ) = positions
        bw.buf.seek(off_local_vol_pos)
        BinWriter(bw.buf).write_u32(off_local_vol)
        bw.buf.seek(off_local_base_pos)
        BinWriter(bw.buf).write_u32(off_local_base)
        bw.buf.seek(off_network_vol_pos)
        BinWriter(bw.buf).write_u32(off_network_vol)
        bw.buf.seek(off_base_name_pos)
        BinWriter(bw.buf).write_u32(off_base_name)
        if not include_unicode:
            return
        if off_local_base_u_pos is None or off_base_name_u_pos is None:
            msg = "Unicode offset placeholder missing."
            raise RuntimeError(msg)
        bw.buf.seek(off_local_base_u_pos)
        BinWriter(bw.buf).write_u32(off_local_base_u)
        bw.buf.seek(off_base_name_u_pos)
        BinWriter(bw.buf).write_u32(off_base_name_u)

    def write(self, bw: BinWriter, include_unicode: bool = True) -> None:
        """Write LinkInfo with correct header/payload layout and offsets.
        Offsets are measured from the start of the LinkInfo structure.
        """
        header_size = LINKINFO_HEADER_UNICODE if include_unicode else LINKINFO_HEADER_LEGACY
        flags = (1 if self.local else 0) | (2 if self.remote else 0)
        positions = self._write_header_placeholders(bw, header_size, flags, include_unicode)
        start_pos, size_pos, *_ = positions
        payload_start = bw.buf.tell()
        assert payload_start - start_pos == header_size
        off_local_vol, off_local_base, off_local_base_u = self._write_local_payload(bw, start_pos, include_unicode)
        off_network_vol, off_base_name, off_base_name_u = self._write_remote_payload(bw, start_pos, include_unicode)
        cur = bw.buf.tell()
        self._patch_header_offsets(
            bw,
            positions,
            off_local_vol,
            off_local_base,
            off_network_vol,
            off_base_name,
            off_local_base_u,
            off_base_name_u,
            include_unicode,
        )
        end_pos = cur
        total_size = end_pos - start_pos
        bw.buf.seek(size_pos)
        BinWriter(bw.buf).write_u32(total_size)
        bw.buf.seek(end_pos)


# ---------------------------------------------------------------------------
# Extra Data blocks (PropertyStore, IconEnvironment, EnvironmentVariable)
# ---------------------------------------------------------------------------
