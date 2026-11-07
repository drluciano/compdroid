from __future__ import annotations

import json
import os
import random

import pytest

from compdroid import lz4block
from compdroid.cli import main
from compdroid.dump import DumpError, open_dump
from compdroid.profiles import find, load_all
from compdroid.scan import scan_module

from fixtures import words, write_dump

NOP = 0xD503201F
SVC_SLEEP = 0xD4000001 | (0x0B << 5)
SVC_GETINFO = 0xD4000001 | (0x29 << 5)
MRS_X3_TPIDRRO = 0xD53BD060 | 3
MRS_X0_CNTPCT = 0xD53BE020
MSR_TPIDR_X9 = 0xD51BD040 | 9


def sample_text() -> bytes:
    return words(NOP, SVC_SLEEP, MRS_X3_TPIDRRO, NOP, SVC_GETINFO, SVC_GETINFO, MRS_X0_CNTPCT, MSR_TPIDR_X9)


def test_lz4_roundtrip_with_matches():
    # literals "abcd", then a 12-byte match at offset 4 (overlapping), then 5 literal tail bytes
    block = bytes([0x48]) + b"abcd" + bytes([4, 0]) + bytes([0x50]) + b"tail!"
    assert lz4block.decompress(block, 4 + 12 + 5) == b"abcd" * 4 + b"tail!"


def test_lz4_literals_only_long():
    data = bytes(random.Random(1).randrange(256) for _ in range(1000))
    assert lz4block.decompress(lz4block.compress_literals_only(data), len(data)) == data


def test_inspect_reads_title_and_build(tmp_path):
    dump = open_dump(write_dump(tmp_path / "g", sample_text()))
    assert dump.npdm.title_id == "0100000000ABC000"
    assert dump.modules["main"].build_id == bytes(range(1, 21)).hex().upper()
    assert dump.romfs.kind == "dir" and dump.romfs.file_count == 1


def test_accepts_exefs_folder_directly(tmp_path):
    root = write_dump(tmp_path / "g", sample_text())
    dump = open_dump(root / "exefs")
    assert dump.romfs is not None


@pytest.mark.parametrize("compress", [True, False])
def test_scan_finds_rewrite_sites(tmp_path, compress):
    dump = open_dump(write_dump(tmp_path / "g", sample_text(), compress=compress))
    r = scan_module("main", dump.modules["main"])
    assert r.svc == {0x0B: 1, 0x29: 2}
    assert r.sysreg == {"mrs TPIDRRO_EL0": 1, "mrs CNTPCT_EL0": 1, "msr TPIDR_EL0": 1}
    assert r.rewrite_sites == 6
    assert r.page16k_issues == []


def test_scan_flags_16k_page_sharing(tmp_path):
    dump = open_dump(write_dump(tmp_path / "g", sample_text(), ro_mem=0x1000, data_mem=0x2000))
    issues = scan_module("main", dump.modules["main"]).page16k_issues
    assert len(issues) == 2


def test_refuses_containers_and_keys(tmp_path):
    for name in ("game.nsp", "game.xci", "prod.keys"):
        p = tmp_path / name
        p.write_bytes(b"\0")
        with pytest.raises(DumpError, match="does not open"):
            open_dump(p)


def test_missing_exefs(tmp_path):
    with pytest.raises(DumpError, match="no exefs"):
        open_dump(tmp_path)


def test_profile_match(tmp_path):
    pdir = tmp_path / "profiles" / "0100000000ABC000"
    pdir.mkdir(parents=True)
    bid = bytes(range(1, 21)).hex().upper()
    (pdir / "game.toml").write_text(
        f'''
[game]
title_id = "0100000000ABC000"
name = "Synthetic"

[[versions]]
version = "1.0.0"
main_build_id = "{bid[:16]}"
status = "boots"

[[versions.patches]]
id = "fps60"
module = "main"
offset = 0x10
bytes = "1F 20 03 D5"
setting = "target_fps"
'''
    )
    profiles = load_all(tmp_path / "profiles")
    prof, ver = find(profiles, "0100000000abc000", bid)
    assert prof.name == "Synthetic" and ver.version == "1.0.0"
    assert ver.patches[0].bytes == bytes.fromhex("1F2003D5")


def test_repo_profiles_load():
    from compdroid.profiles import default_profiles_dir

    load_all(default_profiles_dir())  # must not raise


def test_cli_json(tmp_path, capsys):
    root = write_dump(tmp_path / "g", sample_text())
    assert main(["inspect", str(root), "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["title_id"] == "0100000000ABC000"
    assert main(["scan", str(root), "--json"]) == 0
    scan = json.loads(capsys.readouterr().out)
    assert scan[0]["svc"] == {"0x0B": 1, "0x29": 2}


def test_cli_error_exit(tmp_path, capsys):
    assert main(["inspect", os.fspath(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err


def test_settings_roundtrip_and_validation(tmp_path):
    from compdroid.settings import GameSettings, settings_path

    s = GameSettings(target_fps="60", upscaler="Snapdragon GSR 1", frame_generation="60 to 120",
                     resolution_scale=75)
    assert s.validate() == []
    p = settings_path(tmp_path, "0100000000ABC000")
    s.save(p)
    assert GameSettings.load(p) == s
    assert GameSettings.load(tmp_path / "missing.json") == GameSettings()
    bad = GameSettings(driver="Custom driver (zip)", resolution_scale=500, target_fps="144")
    assert len(bad.validate()) == 3
