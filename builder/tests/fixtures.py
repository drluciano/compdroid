"""Synthetic ExeFS fixtures. They contain made-up instructions only, no game data."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from compdroid.lz4block import compress_literals_only


def make_nso(text: bytes, ro: bytes = b"\0" * 16, data: bytes = b"\0" * 16, *, compress: bool = True,
             module_id: bytes = bytes(range(1, 21)), ro_mem: int = 0x4000, data_mem: int = 0x8000) -> bytes:
    segs = [text, ro, data]
    stored = [compress_literals_only(s) if compress else s for s in segs]
    hdr = bytearray(0x100)
    hdr[0:4] = b"NSO0"
    flags = (0b111 if compress else 0) | 0b111000
    struct.pack_into("<III", hdr, 0x4, 0, 0, flags)
    off = 0x100
    mems = [0, ro_mem, data_mem]
    for i, (raw, st) in enumerate(zip(segs, stored)):
        struct.pack_into("<III", hdr, 0x10 + i * 0x10, off, mems[i], len(raw))
        struct.pack_into("<I", hdr, 0x60 + i * 4, len(st))
        hdr[0xA0 + i * 0x20 : 0xC0 + i * 0x20] = hashlib.sha256(raw).digest()
        off += len(st)
    struct.pack_into("<I", hdr, 0x3C, 0x1000)  # bss
    hdr[0x40 : 0x40 + len(module_id)] = module_id
    return bytes(hdr) + b"".join(stored)


def make_npdm(program_id: int = 0x0100000000ABC000, name: str = "Synthetic", flags: int = 0b111) -> bytes:
    blob = bytearray(0x100)
    blob[0:4] = b"META"
    blob[0xC] = flags  # 64-bit, 39-bit address space
    blob[0xE] = 44
    blob[0xF] = 0
    struct.pack_into("<I", blob, 0x1C, 0x100000)
    blob[0x20 : 0x20 + len(name)] = name.encode()
    aci = 0x80
    struct.pack_into("<II", blob, 0x70, aci, 0x40)
    blob[aci : aci + 4] = b"ACI0"
    struct.pack_into("<Q", blob, aci + 0x10, program_id)
    return bytes(blob)


def words(*ws: int) -> bytes:
    return struct.pack(f"<{len(ws)}I", *ws)


def write_dump(root: Path, text: bytes, **kw) -> Path:
    exefs = root / "exefs"
    exefs.mkdir(parents=True)
    (exefs / "main.npdm").write_bytes(make_npdm())
    (exefs / "main").write_bytes(make_nso(text, **kw))
    romfs = root / "romfs"
    (romfs / "Data").mkdir(parents=True)
    (romfs / "Data" / "file.bin").write_bytes(b"x" * 100)
    return root
