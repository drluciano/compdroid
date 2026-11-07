"""Default in-game settings the builder bakes into each APK.

Every value can still be changed on the phone from the in-game overlay; these
are only what a fresh install starts with.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

DRIVERS = ["System driver", "Custom driver (zip)"]
FPS_TARGETS = ["30", "40", "45", "60", "Auto"]
UPSCALERS = ["Bilinear", "FSR 1", "Snapdragon GSR 1"]
FRAME_GEN = ["Off", "30 to 60", "60 to 120"]
ANTI_ALIASING = ["Off", "FXAA", "SMAA"]
ASPECT = ["16:9", "Unlocked"]


@dataclass
class GameSettings:
    driver: str = "System driver"
    driver_zip: str = ""  # path to a Turnip or other driver package the user picked
    target_fps: str = "30"
    resolution_scale: int = 100  # percent of the Switch's docked resolution
    dynamic_resolution: bool = False
    upscaler: str = "FSR 1"
    frame_generation: str = "Off"
    anti_aliasing: str = "SMAA"
    aspect_ratio: str = "16:9"
    show_overlay: bool = False

    def validate(self) -> list[str]:
        errs = []
        for name, allowed in (("driver", DRIVERS), ("target_fps", FPS_TARGETS), ("upscaler", UPSCALERS),
                              ("frame_generation", FRAME_GEN), ("anti_aliasing", ANTI_ALIASING),
                              ("aspect_ratio", ASPECT)):
            if getattr(self, name) not in allowed:
                errs.append(f"{name} must be one of {allowed}")
        if not 25 <= self.resolution_scale <= 200:
            errs.append("resolution_scale must be 25 to 200")
        if self.driver == "Custom driver (zip)" and not self.driver_zip:
            errs.append("pick a driver zip or choose the system driver")
        return errs

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "GameSettings":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


def default_output_dir() -> Path:
    return Path.home() / "CompDroid" / "out"


def settings_path(output_dir: Path, title_id: str) -> Path:
    return output_dir / title_id / "default_settings.json"
