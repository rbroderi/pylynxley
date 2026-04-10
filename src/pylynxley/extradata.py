"""ExtraData blocks and PropertyStore support."""

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from io import BytesIO
from struct import pack
from struct import unpack
from typing import ClassVar
from typing import Protocol
from typing import TypeAlias
from typing import override
from typing import runtime_checkable

from .core import ENVVAR_ANSI_SIZE
from .core import ENVVAR_UNICODE_SIZE
from .core import EXTRADATA_TERMINATOR
from .core import ICON_ENV_ANSI_SIZE
from .core import ICON_ENV_UNICODE_SIZE
from .core import PROPERTY_STORE_STRING_FORMAT_ID
from .core import PROPERTY_STORE_VERSION_SPS1
from .core import VT_FILETIME
from .core import VT_LPWSTR
from .core import VT_UI4
from .core import VT_UI8
from .core import BinReader
from .core import BinWriter
from .core import ExtraDataType
from .core import LnkFormatError
from .core import decode_ansi
from .core import encode_ansi
from .core import filetime_to_datetime


@dataclass
class TypedPropertyValue:
    vt_type: int
    raw: bytes

    @classmethod
    def read(cls, br: BinReader) -> "TypedPropertyValue":
        vt = br.read_u16()
        _pad = br.read_u16()
        if vt == VT_LPWSTR:
            size = br.read_u32()
            val = br.read_bytes(size - 2)  # includes terminator
            return cls(vt, pack("<I", size) + val)
        # other types: fallback
        return cls(vt, b"")

    @staticmethod
    def parse(vt_type: int, blob: bytes) -> str | int | datetime:
        """Convert VT blob to Python type for common variants.
        >>> TypedPropertyValue.parse(0x13, pack("<I", 42))
        42
        """
        if vt_type == VT_LPWSTR:
            return blob[4:].decode("utf-16-le", errors="replace").rstrip("\x00")
        if vt_type == VT_UI4:
            return unpack("<I", blob)[0]
        if vt_type == VT_UI8:
            return unpack("<Q", blob)[0]
        if vt_type == VT_FILETIME:
            low = unpack("<I", blob[:4])[0]
            high = unpack("<I", blob[4:8])[0]
            num = (high << 32) | low
            return filetime_to_datetime(num)
        # Default, return hex blob
        return blob.hex()


@dataclass
class PropertyStore:
    format_id: bytes
    is_strings: bool
    properties: list[tuple[str | int, TypedPropertyValue]] = field(default_factory=list)

    @classmethod
    def read(cls, br: BinReader) -> "PropertyStore | None":
        size = br.read_u32()
        if size == 0:
            return None
        version = br.read_u32()
        if version != PROPERTY_STORE_VERSION_SPS1:
            msg = "Invalid PropertyStore version."
            raise LnkFormatError(msg)
        fmt_id = br.read_bytes(16)
        # String format ID
        is_strings = fmt_id == PROPERTY_STORE_STRING_FORMAT_ID
        props: list[tuple[str | int, TypedPropertyValue]] = []
        consumed = 8 + 16
        while True:
            value_size = br.read_u32()
            consumed += 4
            if value_size == 0:
                break
            if is_strings:
                name_size = br.read_u32()
                _reserved = br.read_u8()
                name = br.read_bytes(name_size).decode("utf-16-le", errors="replace")
                blob = br.read_bytes(value_size - 9)
                vt = unpack("<H", blob[:2])[0]
                val = TypedPropertyValue(vt_type=vt, raw=blob[4:])
                props.append((name, val))
            else:
                value_id = br.read_u32()
                _reserved = br.read_u8()
                blob = br.read_bytes(value_size - 9)
                vt = unpack("<H", blob[:2])[0]
                val = TypedPropertyValue(vt_type=vt, raw=blob[4:])
                props.append((value_id, val))
            consumed += value_size
        return cls(fmt_id, is_strings, props)

    def to_bytes(self) -> bytes:
        out = BytesIO()
        bw = BinWriter(out)
        size_buf = BytesIO()
        sbw = BinWriter(size_buf)
        for name, val in self.properties:
            if self.is_strings:
                name_bytes = str(name).encode("utf-16-le")
                payload = pack("<H", val.vt_type) + b"\x00\x00" + val.raw
                value_size = 9 + len(name_bytes) + len(payload)
                sbw.write_u32(value_size)
                sbw.write_u32(len(name_bytes))
                sbw.write_u8(0)
                sbw.write_bytes(name_bytes)
                sbw.write_bytes(payload)
            else:
                payload = pack("<H", val.vt_type) + b"\x00\x00" + val.raw
                value_size = 9 + len(payload)
                sbw.write_u32(value_size)
                sbw.write_u32(int(name))
                sbw.write_u8(0)
                sbw.write_bytes(payload)
        sbw.write_u32(0)  # end
        total_size = 8 + 16 + len(size_buf.getvalue())
        bw.write_u32(total_size)
        bw.write_u32(PROPERTY_STORE_VERSION_SPS1)
        bw.write_bytes(self.format_id)
        bw.write_bytes(size_buf.getvalue())
        return out.getvalue()


@runtime_checkable
class ExtraBlockFactory(Protocol):
    signature: ExtraDataType

    @classmethod
    def from_bytes(cls, payload: bytes) -> "ExtraDataBlock": ...


@dataclass
class ExtraDataBlock(ABC):
    """Abstract base for known ExtraData blocks.
    Subclasses must provide a class-level 'signature' and implement from_bytes/to_bytes.
    """

    signature: ClassVar[ExtraDataType]  # class-level constant per subclass

    @classmethod
    @abstractmethod
    def from_bytes(cls, payload: bytes) -> "ExtraDataBlock":
        """Parse an ExtraData block of this type from bytes."""

    @abstractmethod
    def to_bytes(self) -> bytes:
        """Serialize this ExtraData block to bytes."""


@dataclass
class UnknownExtraDataBlock:
    """Holder for unimplemented/unknown ExtraData blocks.
    Has a raw signature (int) and raw data.
    """

    signature: int
    data: bytes

    def to_bytes(self) -> bytes:
        out = BytesIO()
        bw = BinWriter(out)
        bw.write_u32(len(self.data) + 8)
        bw.write_u32(int(self.signature))
        bw.write_bytes(self.data)
        return out.getvalue()


@dataclass
class IconEnvironmentDataBlock(ExtraDataBlock):
    signature: ClassVar[ExtraDataType] = ExtraDataType.IconEnvironmentDataBlock
    target_ansi: str = ""
    target_unicode: str = ""

    @classmethod
    @override
    def from_bytes(cls, payload: bytes) -> "IconEnvironmentDataBlock":
        br = BinReader(BytesIO(payload))
        ansi = decode_ansi(br.read_bytes(ICON_ENV_ANSI_SIZE)).replace("\x00", "")
        uni = br.read_bytes(ICON_ENV_UNICODE_SIZE).decode("utf-16-le", errors="replace").replace("\x00", "")
        return cls(target_ansi=ansi, target_unicode=uni)

    @override
    def to_bytes(self) -> bytes:
        ansi = encode_ansi(self.target_ansi or "").ljust(ICON_ENV_ANSI_SIZE, b"\x00")
        uni = (self.target_unicode or "").encode("utf-16-le").ljust(ICON_ENV_UNICODE_SIZE, b"\x00")
        out = BytesIO()
        bw = BinWriter(out)
        bw.write_u32(8 + len(ansi) + len(uni))
        bw.write_u32(int(self.signature))
        bw.write_bytes(ansi + uni)
        return out.getvalue()


@dataclass
class EnvironmentVariableDataBlock(ExtraDataBlock):
    signature: ClassVar[ExtraDataType] = ExtraDataType.EnvironmentVariableDataBlock
    target_ansi: str = ""
    target_unicode: str = ""

    @classmethod
    @override
    def from_bytes(cls, payload: bytes) -> "EnvironmentVariableDataBlock":
        br = BinReader(BytesIO(payload))
        ansi = decode_ansi(br.read_bytes(ENVVAR_ANSI_SIZE)).replace("\x00", "")
        uni = br.read_bytes(ENVVAR_UNICODE_SIZE).decode("utf-16-le", errors="replace").replace("\x00", "")
        return cls(target_ansi=ansi, target_unicode=uni)

    @override
    def to_bytes(self) -> bytes:
        ansi = encode_ansi(self.target_ansi or "").ljust(ENVVAR_ANSI_SIZE, b"\x00")
        uni = (self.target_unicode or "").encode("utf-16-le").ljust(ENVVAR_UNICODE_SIZE, b"\x00")
        out = BytesIO()
        bw = BinWriter(out)
        bw.write_u32(8 + len(ansi) + len(uni))
        bw.write_u32(int(self.signature))
        bw.write_bytes(ansi + uni)
        return out.getvalue()


@dataclass
class PropertyStoreDataBlock(ExtraDataBlock):
    signature: ClassVar[ExtraDataType] = ExtraDataType.PropertyStoreDataBlock
    stores: list[PropertyStore] = field(default_factory=list)

    @classmethod
    @override
    def from_bytes(cls, payload: bytes) -> "PropertyStoreDataBlock":
        br = BinReader(BytesIO(payload))
        stores: list[PropertyStore] = []
        while True:
            ps = PropertyStore.read(br)
            if ps is None:
                break
            stores.append(ps)
        return cls(stores=stores)

    @override
    def to_bytes(self) -> bytes:
        out = BytesIO()
        for ps in self.stores:
            out.write(ps.to_bytes())
        out.write(EXTRADATA_TERMINATOR)
        size = out.tell()
        wrapper = BytesIO()
        bw = BinWriter(wrapper)
        bw.write_u32(size + 8)
        bw.write_u32(int(self.signature))
        bw.write_bytes(out.getvalue())
        return wrapper.getvalue()


ExtraBlock: TypeAlias = ExtraDataBlock | UnknownExtraDataBlock


@dataclass
class ExtraData:
    blocks: list[ExtraBlock] = field(default_factory=list)
    REGISTRY: ClassVar[dict[int, ExtraBlockFactory]] = {
        int(ExtraDataType.IconEnvironmentDataBlock): IconEnvironmentDataBlock,
        int(ExtraDataType.EnvironmentVariableDataBlock): EnvironmentVariableDataBlock,
        int(ExtraDataType.PropertyStoreDataBlock): PropertyStoreDataBlock,
    }

    @classmethod
    def read(cls, br: BinReader) -> "ExtraData":
        blocks: list[ExtraBlock] = []
        while True:
            size = br.read_u32()
            if size < 4:  # terminator or malformed
                break
            sig = br.read_u32()
            payload = br.read_bytes(size - 8)
            factory = cls.REGISTRY.get(sig)
            if factory is not None:
                blocks.append(factory.from_bytes(payload))
            else:
                blocks.append(UnknownExtraDataBlock(signature=sig, data=payload))
        return cls(blocks)

    def to_bytes(self) -> bytes:
        out = BytesIO()
        for b in self.blocks:
            out.write(b.to_bytes())
        out.write(EXTRADATA_TERMINATOR)
        return out.getvalue()

    def first_env_path(self) -> str | None:
        """Find environment-based target path in extra blocks."""
        for b in self.blocks:
            if isinstance(b, (EnvironmentVariableDataBlock, IconEnvironmentDataBlock)):
                return (b.target_unicode or b.target_ansi).strip("\x00")
        return None
