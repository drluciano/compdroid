"""compdroid command line.

    compdroid gui                         open the desktop window
    compdroid extract <game.nsp> --keys K  unpack an .nsp/.nsz/.xci/.xcz with your own prod.keys
    compdroid inspect <dump or package>   identify the game, version and profile match
    compdroid scan <dump or package>      list what native mode must rewrite in the game code
"""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from . import __version__, api
from .dump import DumpError, open_dump
from .extract import ALL_SUFFIXES, ExtractError, extract_package
from .profiles import ProfileError, default_profiles_dir
from .settings import AppConfig, default_output_dir


def _out_dir(args: argparse.Namespace, cfg: AppConfig) -> Path:
    return Path(args.out or cfg.output_dir or default_output_dir())


def resolve_dump(args: argparse.Namespace) -> str:
    """Return a dump folder, extracting first when given a package."""
    p = Path(args.dump)
    if p.is_file() and p.suffix.lower() in ALL_SUFFIXES:
        cfg = AppConfig.load()
        keys = args.keys or cfg.keys_path
        if not keys:
            raise ExtractError(f"{p.name} is a package: pass --keys <your prod.keys> to extract it")
        res = extract_package(p, keys, _out_dir(args, cfg) / p.stem, update=getattr(args, "update", None),
                              hactoolnet=args.hactoolnet or cfg.hactoolnet_path or None,
                              log=lambda m: print(m, file=sys.stderr))
        return str(res.root)
    return args.dump


def cmd_extract(args: argparse.Namespace) -> int:
    cfg = AppConfig.load()
    keys = args.keys or cfg.keys_path
    if not keys:
        raise ExtractError("pass --keys <your prod.keys>")
    res = extract_package(args.package, keys, _out_dir(args, cfg) / Path(args.package).stem, update=args.update,
                          hactoolnet=args.hactoolnet or cfg.hactoolnet_path or None)
    if args.remember:
        if keys:
            cfg.keys_path = str(Path(keys).resolve())
        if args.hactoolnet:
            cfg.hactoolnet_path = str(Path(args.hactoolnet).resolve())
        cfg.save()
    print(res.root)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    info = api.inspect(resolve_dump(args), args.profiles)
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
    results = api.scan(open_dump(resolve_dump(args)), include_rtld=args.all)
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

    def pkg_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--keys", help="your prod.keys (remembered with extract --remember)")
        p.add_argument("--update", help="optional update package (.nsp/.nsz) to apply")
        p.add_argument("--hactoolnet", help="path to hactoolnet(.exe) if not in tools/ or on PATH")
        p.add_argument("--out", help="output folder (default %%USERPROFILE%%/CompDroid/out)")

    p = sub.add_parser("extract", help="unpack a game package with your own keys")
    p.add_argument("package", help=".nsp, .nsz, .xci or .xcz of a game you own")
    pkg_opts(p)
    p.add_argument("--remember", action="store_true", help="remember the keys and hactoolnet paths")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("inspect", help="identify a game and match it to a profile")
    p.add_argument("dump", help="game package, or a folder containing exefs/ and romfs/")
    pkg_opts(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("scan", help="find instructions native mode must rewrite")
    p.add_argument("dump", help="game package, or a folder containing exefs/ and romfs/")
    pkg_opts(p)
    p.add_argument("--all", action="store_true", help="include rtld")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (DumpError, ProfileError, ExtractError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
