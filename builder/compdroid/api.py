"""Plain-data results shared by the CLI and the GUI."""

from __future__ import annotations

from pathlib import Path

from .dump import Dump, open_dump
from .profiles import find, load_all
from .scan import SVC_NAMES, SYSREG_PATTERNS, scan_module

SYSREG_NOTES = {name: note for name, note in SYSREG_PATTERNS.values()}


def inspect(dump: Dump | str | Path, profiles_dir: str | Path) -> dict:
    if not isinstance(dump, Dump):
        dump = open_dump(dump)
    profiles = load_all(Path(profiles_dir))
    main = dump.modules["main"]
    prof, ver = find(profiles, dump.npdm.title_id, main.build_id)
    return {
        "root": str(dump.root),
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
        else {
            "name": prof.name,
            "file": str(prof.path),
            "version": ver.version if ver else None,
            "status": ver.status if ver else "unknown build",
            "patches": len(ver.patches) if ver else 0,
        },
    }


def scan(dump: Dump | str | Path, include_rtld: bool = False) -> list[dict]:
    if not isinstance(dump, Dump):
        dump = open_dump(dump)
    out = []
    for name, nso in dump.modules.items():
        if name == "rtld" and not include_rtld:
            continue
        r = scan_module(name, nso)
        out.append(
            {
                "module": r.module,
                "text_size": r.text_size,
                "rewrite_sites": r.rewrite_sites,
                "svc": {f"0x{k:02X}": v for k, v in sorted(r.svc.items())},
                "sysreg": dict(r.sysreg.most_common()),
                "page16k_issues": r.page16k_issues,
            }
        )
    return out


def svc_name(hex_id: str) -> str:
    return SVC_NAMES.get(int(hex_id, 16), "?")


def human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"
