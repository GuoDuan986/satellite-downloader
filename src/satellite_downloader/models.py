from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from shapely.geometry.base import BaseGeometry


class ProductOrder(str, Enum):
    TIME_DESC = "time_desc"
    TILE_THEN_TIME_DESC = "tile_then_time_desc"


@dataclass(frozen=True)
class SearchCriteria:
    start_date: date
    end_date: date
    max_cloud_cover: float
    max_results: int = 500
    product_order: ProductOrder = ProductOrder.TIME_DESC

    def validate(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if not 0 <= self.max_cloud_cover <= 100:
            raise ValueError("最大云量必须在 0 到 100 之间")
        if self.max_results < 1:
            raise ValueError("最大结果数必须大于 0")


@dataclass(frozen=True)
class SatelliteProduct:
    provider: str
    product_id: str
    name: str
    sensing_time: datetime
    cloud_cover: float | None
    tile_id: str | None
    size_bytes: int
    online: bool
    footprint: BaseGeometry
    checksum_md5: str | None = None
    metadata: dict[str, Any] | None = None

    @property
    def archive_name(self) -> str:
        base = self.name[:-5] if self.name.upper().endswith(".SAFE") else self.name
        return f"{base}.zip"

    @property
    def size_text(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{size:.1f} TB"


def order_products(
    products: Iterable[SatelliteProduct],
    order: ProductOrder,
    tile_order: Sequence[str] = (),
) -> list[SatelliteProduct]:
    ordered = sorted(products, key=lambda item: item.sensing_time, reverse=True)
    if order == ProductOrder.TIME_DESC:
        return ordered

    tile_ranks = {tile_id: index for index, tile_id in enumerate(tile_order)}
    fallback_rank = len(tile_ranks)
    return sorted(
        ordered,
        key=lambda item: (
            tile_ranks.get(item.tile_id or "", fallback_rank),
            item.tile_id or "",
        ),
    )
