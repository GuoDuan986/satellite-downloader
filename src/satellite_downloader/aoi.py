from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .exceptions import SatelliteDownloaderError


class AreaOfInterest:
    def __init__(self, source: Path | None, geometry: BaseGeometry) -> None:
        self.source = source
        self.geometry = geometry

    @classmethod
    def from_bounds(
        cls,
        bounds: tuple[float, float, float, float],
    ) -> "AreaOfInterest":
        min_x, min_y, max_x, max_y = bounds
        if not (-180 <= min_x < max_x <= 180):
            raise SatelliteDownloaderError("检索范围的经度边界无效")
        if not (-90 <= min_y < max_y <= 90):
            raise SatelliteDownloaderError("检索范围的纬度边界无效")
        return cls(source=None, geometry=box(min_x, min_y, max_x, max_y))

    @classmethod
    def load(cls, source: Path) -> "AreaOfInterest":
        if not source.is_file():
            raise SatelliteDownloaderError(f"找不到研究区文件：{source}")

        frame = gpd.read_file(source)
        if frame.empty:
            raise SatelliteDownloaderError("研究区文件不包含任何几何对象")
        if frame.crs is None:
            raise SatelliteDownloaderError("研究区文件缺少坐标系信息")

        frame = frame.to_crs("EPSG:4326")
        geometry = unary_union(frame.geometry.dropna().tolist())
        if geometry.is_empty:
            raise SatelliteDownloaderError("研究区几何为空")
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        if geometry.is_empty or not geometry.is_valid:
            raise SatelliteDownloaderError("研究区几何无效，无法用于检索")
        return cls(source=source, geometry=geometry)

    @property
    def bounds_text(self) -> str:
        min_x, min_y, max_x, max_y = self.geometry.bounds
        return f"{min_x:.3f}–{max_x:.3f}°E，{min_y:.3f}–{max_y:.3f}°N"

    def search_boxes(self, segment_width: float = 0.9) -> list[tuple[float, float, float, float]]:
        """Approximate the long corridor with narrow boxes for short OData URLs."""
        min_x, min_y, max_x, max_y = self.geometry.bounds
        result: list[tuple[float, float, float, float]] = []
        x = min_x
        while x < max_x:
            right = min(x + segment_width, max_x)
            clipped = self.geometry.intersection(box(x, min_y - 1, right, max_y + 1))
            if not clipped.is_empty:
                c_min_x, c_min_y, c_max_x, c_max_y = clipped.bounds
                pad = 0.002
                result.append((c_min_x - pad, c_min_y - pad, c_max_x + pad, c_max_y + pad))
            x = right
        return result
