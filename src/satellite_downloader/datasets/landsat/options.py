# src/satellite_downloader/datasets/landsat/options.py
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class LandsatSearchOptions:
    """
    Landsat 特有的搜索参数（基于 STAC）
    """
    cloud_cover_max: Optional[float] = None
    """云量上限（百分比），如 50 表示只返回云量 <= 50% 的产品"""

    path: Optional[int] = None
    """WRS-2 Path（轨道编号）"""

    row: Optional[int] = None
    """WRS-2 Row（行编号）"""

    platform: Optional[str] = None
    """卫星平台：'landsat-8' 或 'landsat-9'，不指定则返回所有"""

    include_assets: Tuple[str, ...] = ("red", "green", "blue", "qa_pixel")
    """要下载的资产键列表，默认 RGB + QA"""