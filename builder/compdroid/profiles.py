"""Per-game profiles: everything game-specific lives here, never in the runtime.

A profile holds only facts about the game (title ID, build IDs, offsets) and
patch logic written by us. It never holds game code, assets or shaders.
See profiles/SCHEMA.md.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

VALID_STATUS = {"untested", "boots", "ingame", "playable", "broken"}


class ProfileError(ValueError):
    pass


@dataclass
class Patch:
    id: str
    description: str
    module: str
    offset: int  # offset into the decompressed .text of `module`
    bytes: bytes
    setting: str | None = None  # name of the in-game setting that toggles it


@dataclass
class Version:
    version: str
    main_build_id: str
    status: str
    patches: list[Patch] = field(default_factory=list)


@dataclass
class Profile:
    path: Path
    title_id: str
    name: str
    versions: list[Version]
    notes: str = ""

    def match(self, main_build_id: str) -> Version | None:
        bid = main_build_id.upper()
        for v in self.versions:
            if v.main_build_id and bid.startswith(v.main_build_id.upper()):
                return v
        return None


def _hexbytes(s: str, where: str) -> bytes:
    try:
        return bytes.fromhex(s.replace(" ", ""))
    except ValueError as e:
        raise ProfileError(f"{where}: bytes must be hex") from e


def load_profile(path: Path) -> Profile:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ProfileError(f"{path}: {e}") from e

    game = data.get("game") or {}
    tid = str(game.get("title_id", "")).upper()
    if len(tid) != 16 or any(c not in "0123456789ABCDEF" for c in tid):
        raise ProfileError(f"{path}: game.title_id must be 16 hex digits")
    versions = []
    for i, v in enumerate(data.get("versions", [])):
        where = f"{path}: versions[{i}]"
        status = v.get("status", "untested")
        if status not in VALID_STATUS:
            raise ProfileError(f"{where}: status must be one of {sorted(VALID_STATUS)}")
        patches = []
        for j, p in enumerate(v.get("patches", [])):
            pw = f"{where}.patches[{j}]"
            for key in ("id", "module", "offset", "bytes"):
                if key not in p:
                    raise ProfileError(f"{pw}: missing {key}")
            patches.append(
                Patch(
                    id=p["id"],
                    description=p.get("description", ""),
                    module=p["module"],
                    offset=int(p["offset"]),
                    bytes=_hexbytes(p["bytes"], pw),
                    setting=p.get("setting"),
                )
            )
        versions.append(
            Version(
                version=str(v.get("version", "?")),
                main_build_id=str(v.get("main_build_id", "")).upper(),
                status=status,
                patches=patches,
            )
        )
    return Profile(path=path, title_id=tid, name=game.get("name", tid), versions=versions, notes=data.get("notes", ""))


def load_all(profiles_dir: Path) -> list[Profile]:
    out = []
    if not profiles_dir.is_dir():
        return out
    for p in sorted(profiles_dir.glob("*/*.toml")):
        out.append(load_profile(p))
    return out


def find(profiles: list[Profile], title_id: str, main_build_id: str) -> tuple[Profile | None, Version | None]:
    for prof in profiles:
        if prof.title_id == title_id.upper():
            return prof, prof.match(main_build_id)
    return None, None


def default_profiles_dir() -> Path:
    # builder/compdroid/profiles.py -> repo root / profiles
    return Path(__file__).resolve().parents[2] / "profiles"
