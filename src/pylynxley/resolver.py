"""Path resolution policy for parsed shell links."""

import ntpath
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import runtime_checkable

from .core import KNOWN_FOLDER_GUID_DESKTOP
from .core import KNOWN_FOLDER_GUID_DOCUMENTS
from .core import KNOWN_FOLDER_GUID_DOWNLOADS
from .core import KNOWN_FOLDER_GUID_MUSIC
from .core import KNOWN_FOLDER_GUID_PICTURES
from .core import KNOWN_FOLDER_GUID_PROFILE
from .core import KNOWN_FOLDER_GUID_VIDEOS


@runtime_checkable
class _DriveEntryLike(Protocol):
    drive: str


@runtime_checkable
class _PathSegmentEntryLike(Protocol):
    full_name: str
    short_name: str


@runtime_checkable
class _LinkInfoLike(Protocol):
    local: bool
    base_name_unicode: str | None
    base_name: str | None

    def path(self) -> str | None: ...


@runtime_checkable
class _ExtraDataLike(Protocol):
    def first_env_path(self) -> str | None: ...


@runtime_checkable
class _IdListLike(Protocol):
    @property
    def items(self) -> Sequence[Any]: ...

    def get_path(self) -> str | None: ...


@runtime_checkable
class LnkLike(Protocol):
    @property
    def link_info(self) -> _LinkInfoLike | None: ...

    @property
    def extra_data(self) -> _ExtraDataLike: ...

    @property
    def id_list(self) -> _IdListLike | None: ...

    @property
    def source_path(self) -> Path | None: ...

    @property
    def working_dir(self) -> str | None: ...


def _known_folder_base_map() -> dict[str, str | None]:
    user_profile = os.getenv("USERPROFILE")
    return {
        KNOWN_FOLDER_GUID_DESKTOP: (ntpath.join(user_profile, "Desktop") if user_profile else None),
        KNOWN_FOLDER_GUID_DOCUMENTS: (ntpath.join(user_profile, "Documents") if user_profile else None),
        KNOWN_FOLDER_GUID_DOWNLOADS: (ntpath.join(user_profile, "Downloads") if user_profile else None),
        KNOWN_FOLDER_GUID_MUSIC: ntpath.join(user_profile, "Music") if user_profile else None,
        KNOWN_FOLDER_GUID_PICTURES: (ntpath.join(user_profile, "Pictures") if user_profile else None),
        KNOWN_FOLDER_GUID_PROFILE: user_profile,
        KNOWN_FOLDER_GUID_VIDEOS: ntpath.join(user_profile, "Videos") if user_profile else None,
    }


def resolve_known_folder_canonical(path: str) -> str | None:
    if not path.startswith("::{"):
        return None
    end = path.find("}")
    if end < 0:
        return None
    guid = path[2 : end + 1].upper()
    tail = path[end + 1 :].lstrip("\\")
    base = _known_folder_base_map().get(guid)
    if not base:
        return None
    return ntpath.normpath(ntpath.join(base, tail)) if tail else ntpath.normpath(base)


def _normalize_drive_only_idlist(lnk: LnkLike, idp: str | None) -> tuple[str | None, str | None]:
    id_drive, _ = ntpath.splitdrive(idp or "")
    id_list = lnk.id_list
    if not id_list:
        return idp, id_drive
    has_drive = False
    has_segments = False
    drive_letter = None
    for itm in id_list.items:
        if isinstance(itm, _DriveEntryLike):
            has_drive = True
            drive_letter = itm.drive
        elif isinstance(itm, _PathSegmentEntryLike):
            has_segments = True
    if has_drive and not has_segments and drive_letter:
        return drive_letter + "\\", drive_letter
    return idp, id_drive


def _choose_primary_target(
    lnk: LnkLike,
    li: str | None,
    env: str | None,
    idp: str | None,
    id_drive: str | None,
) -> str | None:
    li_is_unc = bool(li and li.startswith("\\\\"))
    if id_drive and li_is_unc:
        tail = ""
        link_info = lnk.link_info
        if link_info:
            tail = link_info.base_name_unicode or link_info.base_name or ""
        return id_drive + ("\\" + tail if tail else "\\")
    link_info = lnk.link_info
    if link_info and link_info.local and li:
        return li
    if idp and idp.startswith("::{"):
        return resolve_known_folder_canonical(idp) or idp
    if idp and idp.startswith("%MY_COMPUTER%\\"):
        return idp[len("%MY_COMPUTER%\\") :]
    if idp and idp.startswith("%USERPROFILE%\\::"):
        return idp[len("%USERPROFILE%\\::") :]
    return li or env or idp


def resolve_lnk_path(lnk: LnkLike) -> str | None:
    link_info = lnk.link_info
    extra_data = lnk.extra_data
    id_list = lnk.id_list
    li = link_info.path() if link_info else None
    env = extra_data.first_env_path()
    idp = id_list.get_path() if id_list else None
    idp, id_drive = _normalize_drive_only_idlist(lnk, idp)
    result = _choose_primary_target(lnk, li, env, idp, id_drive)
    if not result:
        return None
    result = os.path.expandvars(result)
    drive, _ = ntpath.splitdrive(result)
    if drive:
        return result
    base = lnk.working_dir or (str(lnk.source_path.parent) if lnk.source_path else None)
    if not base:
        return result
    return ntpath.normpath(ntpath.join(base, result))
