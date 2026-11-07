"""Finding and validating a user-supplied, already-extracted game dump.

Guardrail: CompDroid only reads plain extracted `exefs/` and `romfs/` data.
It refuses container files (NSP, XCI, NCA...) and never reads key files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .formats import FormatError, Npdm, Nso, parse_npdm, parse_nso

# Load order on the console: rtld first, then main, then the SDK and subsdks.
EXEFS_MODULES = ["rtld", "main"] + [f"subsdk{i}" for i in range(10)] + ["sdk"]

REFUSED_SUFFIXES = {".nsp", ".nsz", ".xci", ".xcz", ".nca", ".ncz", ".keys"}


class DumpError(ValueError):
    pass


@dataclass
class RomFs:
    path: Path
    kind: str  # "dir" or "image"
    file_count: int
    total_bytes: int


@dataclass
class Dump:
    root: Path
    exefs: Path
    npdm: Npdm
    modules: dict[str, Nso] = field(default_factory=dict)
    romfs: RomFs | None = None


def _refuse_containers(path: Path) -> None:
    if path.is_file() and path.suffix.lower() in REFUSED_SUFFIXES:
        raise DumpError(
            f"{path.name}: CompDroid does not open {path.suffix} files or keys. "
            "Point it at a folder with the extracted exefs/ and romfs/ of a game you own."
        )


def _find_exefs(root: Path) -> Path:
    for cand in (root / "exefs", root / "ExeFS", root):
        if (cand / "main.npdm").is_file() and (cand / "main").is_file():
            return cand
    raise DumpError(f"no exefs found under {root} (expected exefs/main and exefs/main.npdm)")


def _find_romfs(root: Path) -> RomFs | None:
    for cand in (root / "romfs", root / "RomFS"):
        if cand.is_dir():
            count = 0
            total = 0
            for dirpath, _dirs, files in os.walk(cand):
                for fn in files:
                    count += 1
                    try:
                        total += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass
            return RomFs(path=cand, kind="dir", file_count=count, total_bytes=total)
    img = root / "romfs.bin"
    if img.is_file():
        return RomFs(path=img, kind="image", file_count=0, total_bytes=img.stat().st_size)
    return None


def open_dump(path: str | os.PathLike) -> Dump:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise DumpError(f"{root} does not exist")
    _refuse_containers(root)
    if not root.is_dir():
        raise DumpError(f"{root} is not a folder")

    exefs = _find_exefs(root)
    # If the user pointed at exefs/ itself, look for romfs next to it.
    search_root = root if exefs != root else root.parent

    try:
        npdm = parse_npdm(exefs / "main.npdm")
    except FormatError as e:
        raise DumpError(str(e)) from e
    if not npdm.is_64bit:
        raise DumpError("32-bit titles are not supported: native mode needs AArch64 game code")

    dump = Dump(root=search_root, exefs=exefs, npdm=npdm, romfs=_find_romfs(search_root))
    for name in EXEFS_MODULES:
        p = exefs / name
        if p.is_file():
            try:
                dump.modules[name] = parse_nso(p)
            except FormatError as e:
                raise DumpError(str(e)) from e
    if "main" not in dump.modules:
        raise DumpError("exefs/main is missing or unreadable")
    return dump
