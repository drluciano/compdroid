"""compdroid command line.

    compdroid inspect <dump>   identify the game, version and profile match
    compdroid scan <dump>      list what native mode must rewrite in the game code
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .dump import DumpError, open_dump
from .profiles import ProfileError, default_profiles_dir, find, load_all
from .scan import SVC_NAMES, SYSREG_PATTERNS, scan_module


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{n} B"


def cmd_inspect(args: argparse.Namespace) -> int:
    dump = open_dump(args.dump)
    profiles = load_all(Path(args.profiles))
    main = dump.modules["main"]
    prof, ver = find(profiles, dump.npdm.title_id, main.build_id)

    info = {
        "title_id": dump.npdm.title_id,
        "npdm_name": dump.npdm.name,
        "address_space": dump.npdm.address_space,
        "main_thread": {
            "priority": dump.npdm.main_thread_priority,
            "core": dump.npdm.main_thread_core,
            "stack_size": dump.npdm.main_thread_stack_size,
        },
        "modules": {
            name: {
                "build_id": nso.build_id,
                "text": nso.segments["text"].size,
                "ro": nso.segments["ro"].size,
                "data": nso.segments["data"].size,
                "bss": nso.bss_size,
            }
            for name, nso in dump.modules.items()
        },
        "romfs": None
        if dump.romfs is None
        else {"kind": dump.romfs.kind, "files": dump.romfs.file_count, "bytes": dump.romfs.total_bytes},
        "profile": None
        if prof is None
        else {"name": prof.name, "file": str(prof.path), "version": ver.version if ver else None,
              "status": ver.status if ver else "unknown build"},
    }
    if args.json:
        print(json.dumps(info, indent=2))
        return 0

    print(f"Title ID      {info['title_id']}  ({info['npdm_name']})")
    print(f"Address space {info['address_space']}")
    print("Modules")
    for name, m in info["modules"].items():
        print(f"  {name:<9} build {m['build_id']}  text {_human(m['text'])}")
    if dump.romfs is None:
        print("RomFS         not found (expected romfs/ or romfs.bin next to exefs/)")
    else:
        print(f"RomFS         {dump.romfs.kind}, {dump.romfs.file_count} files, {_human(dump.romfs.total_bytes)}")
    if prof is None:
        print("Profile       none for this title: generic best effort only")
    elif ver is None:
        print(f"Profile       {prof.name}, but this build is not listed (add it to {prof.path.name})")
    else:
        print(f"Profile       {prof.name} {ver.version} [{ver.status}], {len(ver.patches)} patch(es)")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    dump = open_dump(args.dump)
    results = [scan_module(name, nso) for name, nso in dump.modules.items() if name != "rtld" or args.all]

    if args.json:
        print(json.dumps(
            [
                {
                    "module": r.module,
                    "text_size": r.text_size,
                    "svc": {f"0x{k:02X}": v for k, v in sorted(r.svc.items())},
                    "sysreg": dict(r.sysreg),
                    "page16k_issues": r.page16k_issues,
                }
                for r in results
            ],
            indent=2,
        ))
        return 0

    total = 0
    for r in results:
        total += r.rewrite_sites
        print(f"{r.module}  (.text {_human(r.text_size)}): {r.rewrite_sites} rewrite site(s)")
        for num, count in sorted(r.svc.items()):
            print(f"    svc 0x{num:02X} {SVC_NAMES.get(num, '?'):<28} x{count}")
        notes = {v[0]: v[1] for v in SYSREG_PATTERNS.values()}
        for reg, count in r.sysreg.most_common():
            print(f"    {reg:<32} x{count}   {notes[reg]}")
        for issue in r.page16k_issues:
            print(f"    16K: {issue}")
    print(f"Total: {total} candidate rewrite site(s). Everything else runs unchanged on the phone's CPU.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="compdroid", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"compdroid {__version__}")
    ap.add_argument("--profiles", default=str(default_profiles_dir()), help="profiles folder")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect", help="identify a dump and match it to a profile")
    p.add_argument("dump", help="folder containing exefs/ and romfs/ (extracted, from a game you own)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("scan", help="find instructions native mode must rewrite")
    p.add_argument("dump")
    p.add_argument("--all", action="store_true", help="include rtld")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (DumpError, ProfileError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
