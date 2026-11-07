from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

from compdroid.dump import open_dump
from compdroid.extract import ExtractError, extract_package, read_pfs0, ticket_title_key

FAKE = [sys.executable, str(Path(__file__).with_name("fake_hactoolnet.py"))]


def make_ticket(rights_id: bytes, key: bytes) -> bytes:
    tik = bytearray(0x2C0)
    struct.pack_into("<I", tik, 0, 0x10004)  # RSA-2048 SHA-256
    tik[0x180:0x190] = key
    tik[0x2A0:0x2B0] = rights_id
    return bytes(tik)


def make_nsp(path: Path, files: dict[str, bytes]) -> Path:
    names = b""
    entries = b""
    data = b""
    for name, blob in files.items():
        entries += struct.pack("<QQII", len(data), len(blob), len(names), 0)
        names += name.encode() + b"\0"
        data += blob
    names += b"\0" * (-len(names) % 0x10)
    path.write_bytes(b"PFS0" + struct.pack("<II", len(files), len(names)) + b"\0" * 4 + entries + names + data)
    return path


def nsp_with_ticket(path: Path, rid: bytes = b"\x01" * 16) -> Path:
    return make_nsp(path, {
        "1111.program.nca": b"P" * 100,
        "2222.control.nca": b"C" * 10,
        "3333.cnmt.nca": b"M" * 10,
        f"{rid.hex()}.tik": make_ticket(rid, b"\xAB" * 16),
    })


def test_pfs0_and_ticket(tmp_path):
    nsp = nsp_with_ticket(tmp_path / "g.nsp")
    names = [e.name for e in read_pfs0(nsp)]
    assert names[0] == "1111.program.nca" and len(names) == 4
    assert ticket_title_key(make_ticket(b"\x02" * 16, b"\xCD" * 16)) == ("02" * 16, "cd" * 16)


def test_pfs0_rejects_path_traversal(tmp_path):
    nsp = make_nsp(tmp_path / "bad.nsp", {"../evil": b"x"})
    with pytest.raises(ExtractError, match="unsafe"):
        read_pfs0(nsp)


def test_extract_nsp_end_to_end(tmp_path, monkeypatch):
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_HAC_LOG", str(log))
    keys = tmp_path / "prod.keys"
    keys.write_text("header_key = 00\n")
    res = extract_package(nsp_with_ticket(tmp_path / "g.nsp"), keys, tmp_path / "out", hactoolnet=FAKE,
                          log=lambda m: None)
    dump = open_dump(res.root)
    assert dump.npdm.title_id == "0100000000ABC000"
    assert (res.root / "romfs" / "base.txt").is_file()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert all("--titlekeys" in c for c in calls)  # ticket turned into title.keys
    assert not any("cnmt" in " ".join(c) for c in calls)  # metadata NCAs skipped
    assert not (tmp_path / "out" / "_work").exists()  # intermediates removed


def test_extract_with_update_uses_basenca(tmp_path, monkeypatch):
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_HAC_LOG", str(log))
    keys = tmp_path / "prod.keys"
    keys.write_text("x")
    base = nsp_with_ticket(tmp_path / "base.nsp", b"\x01" * 16)
    upd = nsp_with_ticket(tmp_path / "upd.nsp", b"\x02" * 16)
    res = extract_package(base, keys, tmp_path / "out", update=upd, hactoolnet=FAKE, log=lambda m: None)
    assert (res.root / "romfs" / "patched.txt").is_file()
    last = json.loads(log.read_text().splitlines()[-1])
    assert "--basenca" in last


def test_extract_xci(tmp_path):
    keys = tmp_path / "prod.keys"
    keys.write_text("x")
    xci = tmp_path / "g.xci"
    xci.write_bytes(b"\0" * 32)
    res = extract_package(xci, keys, tmp_path / "out", hactoolnet=FAKE, log=lambda m: None)
    assert (res.root / "exefs" / "main").is_file()


def test_missing_keys_and_tools(tmp_path):
    nsp = nsp_with_ticket(tmp_path / "g.nsp")
    with pytest.raises(ExtractError, match="keys file not found"):
        extract_package(nsp, tmp_path / "nope.keys", tmp_path / "out", hactoolnet=FAKE, log=lambda m: None)


def test_hactoolnet_missing_explains(tmp_path, monkeypatch):
    import compdroid.extract as ex

    monkeypatch.setattr(ex.shutil, "which", lambda name: None)
    with pytest.raises(ExtractError, match="hactoolnet not found"):
        ex.find_hactoolnet(tmp_path / "missing.exe")


def test_nsz_without_tool_explains(tmp_path, monkeypatch):
    import compdroid.extract as ex

    monkeypatch.setattr(ex.shutil, "which", lambda name: None)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    keys = tmp_path / "prod.keys"
    keys.write_text("x")
    nsz = tmp_path / "g.nsz"
    nsz.write_bytes(b"\0")
    with pytest.raises(ExtractError, match="pip install nsz"):
        extract_package(nsz, keys, tmp_path / "out", hactoolnet=FAKE, log=lambda m: None)


def test_download_hactoolnet_from_release_zip(tmp_path, monkeypatch):
    import io
    import zipfile

    from compdroid import autosetup

    monkeypatch.setattr(autosetup.sys, "platform", "win32")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hactoolnet.exe", b"MZfake")
    releases = [
        {"draft": False, "assets": [{"name": "LibHac.nupkg", "browser_download_url": "u0"}]},
        {"draft": False, "assets": [
            {"name": "hactoolnet-0.19.0-linux.zip", "browser_download_url": "u1"},
            {"name": "hactoolnet-0.19.0-win.zip", "browser_download_url": "u2"},
        ]},
    ]
    calls = []

    def fake_get(url):
        calls.append(url)
        return json.dumps(releases).encode() if url == autosetup.LIBHAC_RELEASES else buf.getvalue()

    exe = autosetup.download_hactoolnet(tmp_path, log=lambda m: None, http_get=fake_get)
    assert exe == tmp_path / "hactoolnet.exe" and exe.read_bytes() == b"MZfake"
    assert calls == [autosetup.LIBHAC_RELEASES, "u2"]


def test_download_failure_explains(tmp_path):
    from compdroid import autosetup

    def offline(url):
        raise OSError("no network")

    with pytest.raises(ExtractError, match="could not reach GitHub"):
        autosetup.download_hactoolnet(tmp_path, log=lambda m: None, http_get=offline)
