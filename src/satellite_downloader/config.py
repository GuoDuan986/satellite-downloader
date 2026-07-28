from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


APP_NAME = "卫星影像下载器"
DEFAULT_AOI_BOUNDS = (104.74993, 23.891659, 106.670617, 25.28654)


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppPaths:
    root: Path
    default_downloads: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        root = project_root()
        return cls(
            root=root,
            default_downloads=root / "downloads",
        )
