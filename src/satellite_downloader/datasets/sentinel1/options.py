# src/satellite_downloader/datasets/sentinel1/options.py
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Sentinel1SearchOptions:
    """
    Sentinel-1 特有的搜索参数。
    由 provider 从 SearchRequest.options 字典解析并验证。
    """
    polarisation: Optional[str] = None
    """
    极化方式，可选值：
    - "VV"
    - "VH"
    - "HH"
    - "HV"
    - "VV+VH"（双极化）
    - "HH+HV"（双极化）
    """
    orbit_direction: Optional[str] = None
    """
    轨道方向，可选值：
    - "ASCENDING"（升轨）
    - "DESCENDING"（降轨）
    """

    def __post_init__(self):
        """验证参数合法性"""
        if self.polarisation is not None:
            valid_pols = ["VV", "VH", "HH", "HV", "VV+VH", "HH+HV"]
            if self.polarisation not in valid_pols:
                raise ValueError(
                    f"无效的极化方式：{self.polarisation}，"
                    f"可选值：{valid_pols}"
                )
        if self.orbit_direction is not None:
            if self.orbit_direction not in ["ASCENDING", "DESCENDING"]:
                raise ValueError(
                    f"无效的轨道方向：{self.orbit_direction}，"
                    "可选值：ASCENDING, DESCENDING"
                )