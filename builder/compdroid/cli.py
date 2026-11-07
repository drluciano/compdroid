"""compdroid command line.

    compdroid gui              open the desktop window
    compdroid inspect <dump>   identify the game, version and profile match
    compdroid scan <dump>      list what native mode must rewrite in the game code
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, api
from .dump import DumpError, open_dump
from .profiles import ProfileError, default_profiles_dir


def cmd_inspect(args: argparse.Namespace) -> int:
    info = api.inspect(args.dump, args.profiles)
    if args.json:
        print(json.dumps(info, indent=2))
        return 0

    print(f"Title ID      {info['title_id']}  ({info['npdm_name']})")
    print(f"Address space {info['address_space']}")
    print("Modules")
    for name, m in info["modules"].items():
        print(f"  {name:<9} build {m['build_id']}  text {api.human(m['text'])}")
    rf = info["romfs"]
    if rf is None:
        print("RomFS         not found (expected romfs/ or romfs.bin next to exefs/)")
    else:
        print(f"RomFS         {rf['kind']}, {rf['files']} files, {api.human(rf['bytes'])}")
    prof = info["profile"]
    if prof is None:
        print("Profile       none for this title: generic best effort only")
    elif prof["version"] is None:
        print(f"Profile       {prof['name']}, but this build is not listed (add it to {prof['file']})")
    else:
        print(f"Profile       {prof['name']} {prof['version']} [{prof['status']}], {prof['patches']} patch(es)")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    results = api.scan(open_dump(args.dump), include_rtld=args.all)
    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    total = 0
    for r in results:
        total += r["rewrite_sites"]
        print(f"{r['module']}  (.text {api.human(r['text_size'])}): {r['rewrite_sites']} rewrite site(s)")
        for num, count in r["svc"].items():
            print(f"    svc {num} {api.svc_name(num):<28} x{count}")
        for reg, count in r["sysreg"].items():
            print(f"    {reg:<32} x{count}   {api.SYSREG_NOTES[reg]}")
        for issue in r["page16k_issues"]:
            print(f"    16K: {issue}")
    print(f"Total: {total} candidate rewrite site(s). Everything else runs unchanged on the phone's CPU.")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui import run

    run(initial_dump=args.dump, profiles_dir=args.profiles)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="compdroid", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"compdroid {__version__}")
    ap.add_argument("--profiles", default=str(default_profiles_dir()), help="profiles folder")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("gui", help="open the desktop window")
    p.add_argument("dump", nargs="?", help="optional dump folder to open")
    p.set_defaults(func=cmd_gui)

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
