"""Parsers for the already-extracted ExeFS files: NSO executables and main.npdm.

Layouts follow the public Switchbrew documentation (NSO, NPDM pages).
Nothing here decrypts anything: these files are plaintext once extracted.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import lz4block

NSO_MAGIC = b"NSO0"
NSO_HEADER_SIZE = 0x100

FLAG_TEXT_COMPRESSED = 1 << 0
FLAG_RO_COMPRESSED = 1 << 1
FLAG_DATA_COMPRESSED = 1 << 2
FLAG_TEXT_HASH = 1 << 3
FLAG_RO_HASH = 1 << 4
FLAG_DATA_HASH = 1 << 5


class FormatError(ValueError):
    pass


@dataclass
class Segment:
    name: str
    file_offset: int
    memory_offset: int
    size: int  # decompressed size
    file_size: int  # stored size (compressed or not)
    compressed: bool
    check_hash: bool
    sha256: bytes


@dataclass
class Nso:
    path: Path
    version: int
    flags: int
    module_id: bytes  # 0x20 bytes; first 0x14 is the GNU build ID
    bss_size: int
    segments: dict[str, Segment] = field(default_factory=dict)

    @property
    def build_id(self) -> str:
        """Build ID as uppercase hex: trailing zero bytes dropped, but never shorter than
        the 0x14-byte GNU build ID. This is the form mod loaders use to name patches."""
        raw = self.module_id.rstrip(b"\0")
        if len(raw) < 0x14:
            raw = self.module_id[:0x14]
        return raw.hex().upper()

    def segment_bytes(self, name: str, verify: bool = True) -> bytes:
        seg = self.segments[name]
        with open(self.path, "rb") as f:
            f.seek(seg.file_offset)
            raw = f.read(seg.file_size)
        if len(raw) != seg.file_size:
            raise FormatError(f"{self.path.name}: {name} segment truncated")
        data = lz4block.decompress(raw, seg.size) if seg.compressed else raw
        if verify and seg.check_hash:
            if hashlib.sha256(data).digest() != seg.sha256:
                raise FormatError(f"{self.path.name}: {name} segment hash mismatch")
        return data


def parse_nso(path: Path) -> Nso:
    with open(path, "rb") as f:
        hdr = f.read(NSO_HEADER_SIZE)
    if len(hdr) < NSO_HEADER_SIZE or hdr[:4] != NSO_MAGIC:
        raise FormatError(f"{path.name}: not an NSO (missing NSO0 magic)")

    version, _reserved, flags = struct.unpack_from("<III", hdr, 0x4)

    def seg_hdr(off: int) -> tuple[int, int, int]:
        return struct.unpack_from("<III", hdr, off)

    text = seg_hdr(0x10)
    ro = seg_hdr(0x20)
    data = seg_hdr(0x30)
    (bss_size,) = struct.unpack_from("<I", hdr, 0x3C)
    module_id = hdr[0x40:0x60]
    text_fsz, ro_fsz, data_fsz = struct.unpack_from("<III", hdr, 0x60)
    hashes = [hdr[0xA0 + i * 0x20 : 0xC0 + i * 0x20] for i in range(3)]

    nso = Nso(path=path, version=version, flags=flags, module_id=module_id, bss_size=bss_size)
    for i, (name, sh, fsz) in enumerate(
        (("text", text, text_fsz), ("ro", ro, ro_fsz), ("data", data, data_fsz))
    ):
        nso.segments[name] = Segment(
            name=name,
            file_offset=sh[0],
            memory_offset=sh[1],
            size=sh[2],
            file_size=fsz,
            compressed=bool(flags & (1 << i)),
            check_hash=bool(flags & (1 << (i + 3))),
            sha256=hashes[i],
        )
    return nso


NPDM_MAGIC = b"META"
ACI0_MAGIC = b"ACI0"

ADDRESS_SPACES = {0: "32-bit", 1: "64-bit (old, 36-bit)", 2: "32-bit (no reserved)", 3: "64-bit (39-bit)"}


@dataclass
class Npdm:
    name: str
    product_code: str
    program_id: int
    is_64bit: bool
    address_space: str
    main_thread_priority: int
    main_thread_core: int
    main_thread_stack_size: int
    system_resource_size: int
    version: int

    @property
    def title_id(self) -> str:
        return f"{self.program_id:016X}"


def parse_npdm(path: Path) -> Npdm:
    blob = path.read_bytes()
    if len(blob) < 0x80 or blob[:4] != NPDM_MAGIC:
        raise FormatError(f"{path.name}: not an NPDM (missing META magic)")
    flags = blob[0xC]
    prio = blob[0xE]
    core = blob[0xF]
    (sys_res,) = struct.unpack_from("<I", blob, 0x14)
    (version,) = struct.unpack_from("<I", blob, 0x18)
    (stack,) = struct.unpack_from("<I", blob, 0x1C)
    name = blob[0x20:0x30].split(b"\0", 1)[0].decode("utf-8", "replace")
    product = blob[0x30:0x40].split(b"\0", 1)[0].decode("utf-8", "replace")
    aci_off, aci_size = struct.unpack_from("<II", blob, 0x70)
    if aci_off + 0x18 > len(blob) or blob[aci_off : aci_off + 4] != ACI0_MAGIC:
        raise FormatError(f"{path.name}: ACI0 section missing")
    (program_id,) = struct.unpack_from("<Q", blob, aci_off + 0x10)
    return Npdm(
        name=name,
        product_code=product,
        program_id=program_id,
        is_64bit=bool(flags & 1),
        address_space=ADDRESS_SPACES.get((flags >> 1) & 7, "unknown"),
        main_thread_priority=prio,
        main_thread_core=core,
        main_thread_stack_size=stack,
        system_resource_size=sys_res,
        version=version,
    )
