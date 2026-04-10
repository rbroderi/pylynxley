from pathlib import Path
from typing import Any
from typing import Protocol
from typing import runtime_checkable


@runtime_checkable
class _LinkInfoLike(Protocol):
    local: bool
    remote: bool
    local_base_path: str | None
    local_base_path_unicode: str | None
    network_share_name: str | None
    base_name: str | None
    base_name_unicode: str | None


@runtime_checkable
class _ExtraDataLike(Protocol):
    def first_env_path(self) -> str | None: ...


@runtime_checkable
class _IdListLike(Protocol):
    items: list[Any]

    def get_path(self) -> str | None: ...


@runtime_checkable
class _LnkInstanceLike(Protocol):
    link_flags: int
    show_command: int
    file_size: int
    path: str | None
    description: str | None
    working_dir: str | None
    arguments: str | None
    link_info: _LinkInfoLike | None
    id_list: _IdListLike | None
    extra_data: _ExtraDataLike

    def save(self, path: Path) -> None: ...


@runtime_checkable
class _LnkClassLike(Protocol):
    @classmethod
    def from_file(cls, path: Path) -> _LnkInstanceLike: ...

    @classmethod
    def create_local(
        cls,
        target: str,
        description: str | None = None,
        args: str | None = None,
        icon: str | None = None,
        working_dir: str | None = None,
        window: int = 1,
    ) -> _LnkInstanceLike: ...

    @classmethod
    def create_remote(
        cls,
        unc_path: str,
        description: str | None = None,
        args: str | None = None,
        icon: str | None = None,
        window: int = 1,
    ) -> _LnkInstanceLike: ...

    @classmethod
    def create_uwp(
        cls,
        package_family_name: str,
        target: str,
        location: str | None = None,
        logo44x44: str | None = None,
        description: str | None = None,
    ) -> _LnkInstanceLike: ...


@runtime_checkable
class _LinkFlagsLike(Protocol):
    HasLinkTargetIDList: int
    HasLinkInfo: int
    ForceNoLinkInfo: int
    IsUnicode: int
    HasExpString: int
    HasRelativePath: int


@runtime_checkable
class _ShowCommandLike(Protocol):
    NORMAL: int
    MAXIMIZED: int
    MINIMIZED: int


def run_cli(
    lnk_cls: _LnkClassLike,
    link_flags_cls: _LinkFlagsLike,
    show_command_cls: _ShowCommandLike,
) -> int:  # noqa: PLR0915
    import argparse

    p = argparse.ArgumentParser(description="Parse or create .lnk files (modern API).")
    sub = p.add_subparsers(dest="cmd")
    pa = sub.add_parser("parse", help="Parse an existing .lnk and print details.")
    pa.add_argument("file", type=Path)
    pc = sub.add_parser("create-local", help="Create a local .lnk.")
    pc.add_argument("target", type=str)
    pc.add_argument("out", type=Path)
    pc.add_argument("--desc", type=str, default=None)
    pc.add_argument("--args", type=str, default=None)
    pc.add_argument("--icon", type=str, default=None)
    pc.add_argument("--workdir", type=str, default=None)
    pc.add_argument("--window", type=str, choices=["normal", "max", "min"], default="normal")
    pr = sub.add_parser("create-remote", help="Create a remote (UNC) .lnk.")
    pr.add_argument("unc", type=str)
    pr.add_argument("out", type=Path)
    pr.add_argument("--desc", type=str, default=None)
    pu = sub.add_parser("create-uwp", help="Create a UWP .lnk.")
    pu.add_argument("pfamily", type=str)
    pu.add_argument("target", type=str)
    pu.add_argument("out", type=Path)
    pu.add_argument("--location", type=str, default=None)
    pu.add_argument("--logo44", type=str, default=None)
    pu.add_argument("--desc", type=str, default=None)
    args = p.parse_args()

    if args.cmd == "parse":
        lnk = lnk_cls.from_file(args.file)
        print("Flags:", lnk.link_flags)
        print("Show:", lnk.show_command)
        print("Size:", lnk.file_size)
        print("Path:", lnk.path)
        print("Description:", lnk.description)
        print("WorkingDir:", lnk.working_dir)
        print("Arguments:", lnk.arguments)
        print("\n-- Diagnostics --")
        print(
            "HasLinkTargetIDList:",
            bool(lnk.link_flags & link_flags_cls.HasLinkTargetIDList),
        )
        print("HasLinkInfo:", bool(lnk.link_flags & link_flags_cls.HasLinkInfo))
        print("ForceNoLinkInfo:", bool(lnk.link_flags & link_flags_cls.ForceNoLinkInfo))
        print("IsUnicode:", bool(lnk.link_flags & link_flags_cls.IsUnicode))
        print("HasExpString:", bool(lnk.link_flags & link_flags_cls.HasExpString))
        print("HasRelativePath:", bool(lnk.link_flags & link_flags_cls.HasRelativePath))
        if lnk.link_info:
            li = lnk.link_info
            print("LinkInfo.local:", li.local, "LinkInfo.remote:", li.remote)
            print("LocalBasePath:", li.local_base_path)
            print("LocalBasePathUnicode:", li.local_base_path_unicode)
            print("NetworkShareName:", li.network_share_name)
            print("BaseName:", li.base_name, "BaseNameUnicode:", li.base_name_unicode)
        if lnk.id_list:
            print("IDList items:", [type(i).__name__ for i in lnk.id_list.items])
            print("IDList composite path:", lnk.id_list.get_path())
        print("ExtraData env path:", lnk.extra_data.first_env_path())
        return 0

    if args.cmd == "create-local":
        sc = {
            "normal": show_command_cls.NORMAL,
            "max": show_command_cls.MAXIMIZED,
            "min": show_command_cls.MINIMIZED,
        }[args.window]
        lnk = lnk_cls.create_local(
            args.target,
            description=args.desc,
            args=args.args,
            icon=args.icon,
            working_dir=args.workdir,
            window=sc,
        )
        lnk.save(args.out)
        print("Saved:", args.out)
        return 0

    if args.cmd == "create-remote":
        lnk = lnk_cls.create_remote(args.unc, description=args.desc)
        lnk.save(args.out)
        print("Saved:", args.out)
        return 0

    if args.cmd == "create-uwp":
        lnk = lnk_cls.create_uwp(
            args.pfamily,
            args.target,
            location=args.location,
            logo44x44=args.logo44,
            description=args.desc,
        )
        lnk.save(args.out)
        print("Saved:", args.out)
        return 0

    p.print_help()
    return 2
