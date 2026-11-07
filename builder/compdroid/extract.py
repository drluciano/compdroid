"""Turn a game package you own (.nsp / .xci) into the exefs/ + romfs/ folders the builder reads.

CompDroid contains no decryption code and ships no keys or firmware. It orchestrates
hactoolnet (LibHac's command-line tool, which you install yourself) with the prod.keys
file you supply from your own console:

1. NSP: CompDroid unpacks the outer PFS0 container itself (it is not encrypted) and turns
   each .tik ticket into a title.keys entry. XCI: hactoolnet extracts the secure partition.
2. hactoolnet reports each NCA's content type; the Program NCA holds the game.
3. hactoolnet extracts its ExeFS and RomFS. With an update package, the update's Program
   NCA is extracted on top of the base one (--basenca), giving the patched game.

Compressed .nsz / .xcz packages are first turned back into .nsp / .xci with the `nsz`
tool (`py -m pip install nsz`), then handled as above.

Firmware is not needed: native mode answers system services itself.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

PACKAGE_SUFFIXES = {".nsp", ".xci"}
COMPRESSED_SUFFIXES = {".nsz": ".nsp", ".xcz": ".xci"}
ALL_SUFFIXES = PACKAGE_SUFFIXES | set(COMPRESSED_SUFFIXES)

Log = Callable[[str], None]


class ExtractError(RuntimeError):
    pass


# ---------- PFS0 (NSP outer container, plaintext) ----------

@dataclass
class Pfs0Entry:
    name: str
    offset: int  # absolute file offset
    size: int


def read_pfs0(path: Path) -> list[Pfs0Entry]:
    with open(path, "rb") as f:
        hdr = f.read(0x10)
        if len(hdr) < 0x10 or hdr[:4] != b"PFS0":
            raise ExtractError(f"{path.name}: not an NSP (missing PFS0 header)")
        count, strtab_size = struct.unpack_from("<II", hdr, 4)
        if count > 10000:
            raise ExtractError(f"{path.name}: implausible file count {count}")
        table = f.read(0x18 * count)
        strtab = f.read(strtab_size)
    data_start = 0x10 + 0x18 * count + strtab_size
    entries = []
    for i in range(count):
        off, size, name_off, _ = struct.unpack_from("<QQII", table, i * 0x18)
        end = strtab.find(b"\0", name_off)
        name = strtab[name_off : end if end >= 0 else None].decode("utf-8", "replace")
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            raise ExtractError(f"{path.name}: unsafe entry name {name!r}")
        entries.append(Pfs0Entry(name=name, offset=data_start + off, size=size))
    return entries


def extract_pfs0(path: Path, out_dir: Path, log: Log = print) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with open(path, "rb") as src:
        for e in read_pfs0(path):
            dst = out_dir / e.name
            src.seek(e.offset)
            remaining = e.size
            with open(dst, "wb") as out:
                while remaining:
                    chunk = src.read(min(remaining, 8 << 20))
                    if not chunk:
                        raise ExtractError(f"{path.name}: {e.name} is truncated")
                    out.write(chunk)
                    remaining -= len(chunk)
            log(f"  unpacked {e.name} ({e.size:,} bytes)")
            written.append(dst)
    return written


# ---------- tickets -> title.keys ----------

_SIG_SIZES = {  # signature type -> (signature size, padding)
    0x10000: (0x200, 0x3C), 0x10001: (0x100, 0x3C), 0x10002: (0x3C, 0x40),
    0x10003: (0x200, 0x3C), 0x10004: (0x100, 0x3C), 0x10005: (0x3C, 0x40),
}


def ticket_title_key(tik: bytes) -> tuple[str, str]:
    """Return (rights ID hex, encrypted title key hex) from a common ticket."""
    if len(tik) < 4:
        raise ExtractError("ticket too short")
    (sig_type,) = struct.unpack_from("<I", tik, 0)
    if sig_type not in _SIG_SIZES:
        raise ExtractError(f"unknown ticket signature type 0x{sig_type:X}")
    sig, pad = _SIG_SIZES[sig_type]
    base = 4 + sig + pad
    if len(tik) < base + 0x170:
        raise ExtractError("ticket truncated")
    title_key = tik[base + 0x40 : base + 0x50]
    rights_id = tik[base + 0x160 : base + 0x170]
    return rights_id.hex(), title_key.hex()


def write_title_keys(tickets: Sequence[Path], dst: Path) -> int:
    lines = []
    for t in tickets:
        rid, key = ticket_title_key(t.read_bytes())
        lines.append(f"{rid} = {key}")
    dst.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


# ---------- hactoolnet ----------

def find_hactoolnet(explicit: str | os.PathLike | None = None) -> list[str]:
    """Command prefix for hactoolnet. Order: explicit path, tools/ next to the repo, PATH."""
    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit))
    repo_tools = Path(__file__).resolve().parents[2] / "tools"
    cands += [repo_tools / "hactoolnet.exe", repo_tools / "hactoolnet"]
    for c in cands:
        if c.is_file():
            return [str(c)]
    for name in ("hactoolnet", "hactoolnet.exe"):
        w = shutil.which(name)
        if w:
            return [w]
    raise ExtractError(
        "hactoolnet not found. Download it from LibHac's releases "
        "(github.com/Thealexbarney/LibHac/releases) and put hactoolnet.exe in the repo's tools/ "
        "folder, or choose it in the window's Setup section."
    )


class Hactoolnet:
    def __init__(self, cmd: Sequence[str], keys: Path, title_keys: Path | None = None, log: Log = print):
        if not keys.is_file():
            raise ExtractError(f"keys file not found: {keys}")
        self.cmd = list(cmd)
        self.keys = keys
        self.title_keys = title_keys
        self.log = log

    def run(self, *args: str) -> str:
        argv = self.cmd + ["-k", str(self.keys)]
        if self.title_keys and self.title_keys.is_file() and self.title_keys.stat().st_size:
            argv += ["--titlekeys", str(self.title_keys)]
        argv += list(args)
        try:
            p = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            raise ExtractError(f"could not run hactoolnet: {e}") from e
        out = (p.stdout or "") + (p.stderr or "")
        if p.returncode != 0:
            tail = "\n".join(out.strip().splitlines()[-8:])
            raise ExtractError(f"hactoolnet failed ({' '.join(args[:2])}):\n{tail}")
        return out

    def content_type(self, nca: Path) -> str:
        out = self.run("-t", "nca", str(nca))
        m = re.search(r"Content\s*Type:\s*(\w+)", out, re.IGNORECASE)
        return m.group(1).lower() if m else "unknown"


def _ncas(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() == ".nca" and not p.name.endswith(".cnmt.nca"))


def _program_nca(tool: Hactoolnet, folder: Path) -> Path:
    found = []
    for nca in _ncas(folder):
        ctype = tool.content_type(nca)
        tool.log(f"  {nca.name}: {ctype}")
        if ctype == "program":
            found.append(nca)
    if not found:
        raise ExtractError(f"no Program NCA in {folder.name}: is this a game (not DLC) and are the keys current?")
    return max(found, key=lambda p: p.stat().st_size)


def find_nsz(explicit: str | os.PathLike | None = None) -> list[str]:
    if explicit and Path(explicit).is_file():
        return [str(explicit)]
    w = shutil.which("nsz")
    if w:
        return [w]
    import importlib.util

    if importlib.util.find_spec("nsz") is not None:
        return [sys.executable, "-m", "nsz"]
    raise ExtractError("compressed .nsz/.xcz needs the nsz tool: run  py -m pip install nsz  and try again")


def decompress_package(pkg: Path, keys: Path, work: Path, nsz_cmd: Sequence[str] | None = None,
                       log: Log = print) -> Path:
    """NSZ -> NSP / XCZ -> XCI using the nsz tool. nsz reads prod.keys from its working folder,
    so a temporary copy is placed there and deleted afterwards."""
    cmd = list(nsz_cmd) if nsz_cmd else find_nsz()
    out = work / "decompressed"
    out.mkdir(parents=True, exist_ok=True)
    tmp_keys = out / "prod.keys"
    shutil.copyfile(keys, tmp_keys)
    log(f"Decompressing {pkg.name} with nsz")
    try:
        p = subprocess.run(cmd + ["-D", str(pkg), "-o", str(out)], cwd=out, capture_output=True, text=True,
                           errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        raise ExtractError(f"could not run nsz: {e}") from e
    finally:
        tmp_keys.unlink(missing_ok=True)
    target = out / (pkg.stem + COMPRESSED_SUFFIXES[pkg.suffix.lower()])
    if p.returncode != 0 or not target.is_file():
        tail = "\n".join(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-8:])
        raise ExtractError(f"nsz could not decompress {pkg.name}:\n{tail}")
    return target


def _unpack_package(tool: Hactoolnet, pkg: Path, work: Path, log: Log,
                    nsz_cmd: Sequence[str] | None = None) -> Path:
    suffix = pkg.suffix.lower()
    if suffix in COMPRESSED_SUFFIXES:
        pkg = decompress_package(pkg, tool.keys, work, nsz_cmd, log)
        suffix = pkg.suffix.lower()
    if suffix not in PACKAGE_SUFFIXES:
        raise ExtractError(f"{pkg.name}: expected a .nsp, .nsz, .xci or .xcz file")
    out = work / pkg.stem
    if out.exists():
        shutil.rmtree(out)
    log(f"Unpacking {pkg.name}")
    if suffix == ".nsp":
        files = extract_pfs0(pkg, out, log)
        tickets = [p for p in files if p.suffix.lower() == ".tik"]
        if tickets:
            n = write_title_keys(tickets, out / "title.keys")
            log(f"  {n} ticket(s) read")
            tool.title_keys = out / "title.keys"
    else:
        tool.run("-t", "xci", str(pkg), "--securedir", str(out))
    return out


@dataclass
class ExtractResult:
    root: Path  # holds exefs/ and romfs/
    program_nca: Path
    update_nca: Path | None


def extract_package(package: str | os.PathLike, keys: str | os.PathLike, out_root: str | os.PathLike,
                    update: str | os.PathLike | None = None, hactoolnet: Sequence[str] | str | None = None,
                    nsz: Sequence[str] | None = None, keep_intermediate: bool = False,
                    log: Log = print) -> ExtractResult:
    package = Path(package)
    out_root = Path(out_root)
    cmd = list(hactoolnet) if isinstance(hactoolnet, (list, tuple)) else find_hactoolnet(hactoolnet)
    if not package.is_file():
        raise ExtractError(f"{package} not found")
    work = out_root / "_work"
    work.mkdir(parents=True, exist_ok=True)
    tool = Hactoolnet(cmd, Path(keys), log=log)

    base_dir = _unpack_package(tool, package, work, log, nsz)
    base_nca = _program_nca(tool, base_dir)
    upd_nca = None
    if update:
        base_keys = tool.title_keys
        upd_dir = _unpack_package(tool, Path(update), work, log, nsz)
        # Merge ticket keys so both NCAs can be opened in the same run.
        if base_keys and tool.title_keys and base_keys != tool.title_keys:
            merged = work / "title.keys"
            merged.write_text(base_keys.read_text() + tool.title_keys.read_text(), encoding="utf-8")
            tool.title_keys = merged
        elif base_keys and not tool.title_keys:
            tool.title_keys = base_keys
        upd_nca = _program_nca(tool, upd_dir)

    dest = out_root / "game"
    for sub in ("exefs", "romfs"):
        if (dest / sub).exists():
            shutil.rmtree(dest / sub)
    dest.mkdir(parents=True, exist_ok=True)
    log("Extracting ExeFS and RomFS (RomFS can take a few minutes)")
    args = ["-t", "nca"]
    if upd_nca:
        args += [str(upd_nca), "--basenca", str(base_nca)]
    else:
        args += [str(base_nca)]
    args += ["--exefsdir", str(dest / "exefs"), "--romfsdir", str(dest / "romfs")]
    tool.run(*args)
    if not (dest / "exefs" / "main").is_file():
        raise ExtractError("extraction finished but exefs/main is missing")

    if not keep_intermediate:
        shutil.rmtree(work, ignore_errors=True)
        base_nca = Path(base_nca.name)
        upd_nca = Path(upd_nca.name) if upd_nca else None
    log(f"Done: {dest}")
    return ExtractResult(root=dest, program_nca=base_nca, update_nca=upd_nca)
