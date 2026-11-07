"""Minimal LZ4 *block* decompressor (no frame format), as used by NSO segments.

Pure Python so the builder has no native dependencies. Speed is fine for
inspection and scanning; a C implementation can replace it later if needed.
"""

from __future__ import annotations


class LZ4Error(ValueError):
    pass


def decompress(src: bytes, uncompressed_size: int) -> bytes:
    dst = bytearray()
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1

        # Literals
        lit_len = token >> 4
        if lit_len == 15:
            while True:
                if i >= n:
                    raise LZ4Error("truncated literal length")
                b = src[i]
                i += 1
                lit_len += b
                if b != 255:
                    break
        if i + lit_len > n:
            raise LZ4Error("literal run past end of input")
        dst += src[i : i + lit_len]
        i += lit_len

        if i >= n:
            break  # last sequence has literals only

        # Match
        if i + 2 > n:
            raise LZ4Error("truncated match offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(dst):
            raise LZ4Error(f"bad match offset {offset}")
        match_len = token & 0x0F
        if match_len == 15:
            while True:
                if i >= n:
                    raise LZ4Error("truncated match length")
                b = src[i]
                i += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4

        start = len(dst) - offset
        if match_len <= offset:
            dst += dst[start : start + match_len]
        else:  # overlapping copy
            for k in range(match_len):
                dst.append(dst[start + k])

    if len(dst) != uncompressed_size:
        raise LZ4Error(f"decompressed {len(dst)} bytes, expected {uncompressed_size}")
    return bytes(dst)


def compress_literals_only(data: bytes) -> bytes:
    """Encode `data` as a valid LZ4 block with no matches.

    Only used by tests to build synthetic NSO fixtures.
    """
    out = bytearray()
    n = len(data)
    if n >= 15:
        out.append(0xF0)
        rest = n - 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    else:
        out.append(n << 4)
    out += data
    return bytes(out)
