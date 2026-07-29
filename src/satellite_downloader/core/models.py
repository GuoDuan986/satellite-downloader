# src/satellite_downloader/core/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Tuple, Any, Optional

from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class ProductAsset:
    """
    产品内的单个文件资产（如一个 GeoTIFF 波段或整个 ZIP 包）
    """
    key: str                          # 资产唯一标识，如 "red", "zip", "qa_pixel"
    title: str                        # 显示名称，如 "Red Band", "Full Package"
    url: str                          # 下载链接
    size_bytes: Optional[int] = None  # 文件大小（字节），可能未知
    checksum: Optional[str] = None    # MD5 或 SHA 校验值
    roles: Tuple[str, ...] = ()       # 角色标签，如 ("data", "metadata")
    metadata: Mapping[str, Any] = field(default_factory=dict)  # 额外元数据

    @property
    def size_mb(self) -> Optional[float]:
        """便捷只读属性：将字节转换为 MB，保留 2 位小数，供 UI 动态表格展示"""
        if self.size_bytes is not None:
            return round(self.size_bytes / (1024 * 1024), 2)
        return None


@dataclass(frozen=True)
class SatelliteProduct:
    """
    卫星产品（一景影像），可包含多个资产文件
    """
    provider_id: str                  # 插件 ID，如 "sentinel1", "landsat"
    product_id: str                   # 产品唯一标识（CDSE 的 Id 或 STAC 的 id）
    name: str                         # 产品名称（如 S1A_IW_GRDH_... 或 LC09_L2SP_...）
    sensing_time: datetime            # 成像时间
    footprint: BaseGeometry           # 地理足迹（多边形）
    cloud_cover: Optional[float] = None  # 云量百分比（S1 为 None）
    size_bytes: Optional[int] = None  # 产品总大小（可选）
    online: bool = True               # 是否在线可下载
    assets: Tuple[ProductAsset, ...] = ()  # 该产品包含的文件列表
    metadata: Mapping[str, Any] = field(default_factory=dict)  # 其他元数据

    @property
    def size_mb(self) -> Optional[float]:
        """便捷只读属性：产品总大小 MB"""
        if self.size_bytes is not None:
            return round(self.size_bytes / (1024 * 1024), 2)
        return None

    def get_asset(self, key: str) -> Optional[ProductAsset]:
        """
        根据 key 快速获取特定的 ProductAsset 对象（如获取 'red' 或 'qa_pixel'）
        若未找到则返回 None
        """
        for asset in self.assets:
            if asset.key.lower() == key.lower():
                return asset
        return None