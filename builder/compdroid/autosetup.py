"""Fetch helper tools automatically.

hactoolnet is downloaded from LibHac's official GitHub releases into the repo's tools/
folder the first time a package is opened. Keys are always chosen by the user.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

Log = Callable[[str], None]

LIBHAC_RELEASES = "https://api.github.com/repos/Thealexbarney/LibHac/releases?per_page=15"


def tools_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tools"


def _platform_words() -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        return ("win",)
    if sys.platform == "darwin":
        return ("mac", "osx")
    return ("linux",)


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "compdroid", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - fixed https URLs
        return r.read()


def pick_asset(releases: list[dict]) -> tuple[str, str] | None:
    """(asset name, download URL) of the newest hactoolnet build for this OS."""
    words = _platform_words()
    for rel in releases:
        if rel.get("draft"):
            continue
        for a in rel.get("assets", []):
            name = a.get("name", "").lower()
            if "hactoolnet" in name and any(w in name for w in words) and name.endswith((".zip", ".exe")):
                return a["name"], a["browser_download_url"]
    return None


def download_hactoolnet(dest: Path | None = None, log: Log = print, http_get=_http_get) -> Path:
    from .extract import ExtractError

    dest = dest or tools_dir()
    exe_name = "hactoolnet.exe" if sys.platform.startswith("win") else "hactoolnet"
    log("hactoolnet not found, downloading it from LibHac's GitHub releases")
    try:
        releases = json.loads(http_get(LIBHAC_RELEASES))
    except Exception as e:  # noqa: BLE001
        raise ExtractError(f"could not reach GitHub to download hactoolnet ({e}). Download it from "
                           "github.com/Thealexbarney/LibHac/releases into the tools folder.") from e
    asset = pick_asset(releases if isinstance(releases, list) else [])
    if not asset:
        raise ExtractError("no hactoolnet build for this system in LibHac's releases; download it manually "
                           "into the tools folder")
    name, url = asset
    log(f"  downloading {name}")
    blob = http_get(url)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / exe_name
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            members = [m for m in z.namelist() if Path(m).name.lower() in ("hactoolnet.exe", "hactoolnet")]
            if not members:
                raise ExtractError(f"{name} does not contain hactoolnet")
            target.write_bytes(z.read(members[0]))
    else:
        target.write_bytes(blob)
    if not sys.platform.startswith("win"):
        target.chmod(0o755)
    log(f"  saved {target}")
    return target
