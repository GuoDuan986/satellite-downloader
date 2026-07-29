# src/satellite_downloader/datasets/landsat/provider.py
from __future__ import annotations
import logging
from datetime import datetime
from typing import List, Optional, Mapping, Any, Tuple
from shapely.geometry import shape, box, Polygon
import requests

from satellite_downloader.core.contracts import (
    SatelliteProvider, SearchRequest, SatelliteProduct, ProductAsset
)
from satellite_downloader.datasets.landsat.options import LandsatSearchOptions

# ✅ 尝试导入 planetary_computer SDK（做优雅降级保护）
try:
    import planetary_computer as pc
except ImportError:
    pc = None

logger = logging.getLogger(__name__)


class LandsatProvider(SatelliteProvider):
    """
    Landsat 8/9 Collection 2 Level-2 数据提供者
    基于 Microsoft Planetary Computer STAC API
    """
    # 默认固定 AOI：云南/广西/贵州交界（当 request 中未包含 AOI 时使用）
    DEFAULT_AOI_BOUNDS = (104.74993, 23.891659, 106.670617, 25.28654)
    STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "satellite-image-downloader/0.1"})

    def search(self, request: SearchRequest) -> List[SatelliteProduct]:
        """搜索 Landsat 8/9 Collection 2 Level-2 产品"""
        options = self._parse_options(request.options)
        params = self._build_stac_query(request, options)

        response = self.session.post(self.STAC_URL, json=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        products = []
        for feature in data.get("features", []):
            product = self._parse_item(feature, options.include_assets)
            if product:
                products.append(product)

        return self._filter_and_deduplicate(products)

    def _parse_options(self, options: Mapping[str, object]) -> LandsatSearchOptions:
        """从 SearchRequest.options 解析 Landsat 专属参数"""
        cloud_cover = options.get("cloud_cover_max")
        path = options.get("path")
        row = options.get("row")
        platform = options.get("platform")
        include_assets = options.get("include_assets", ("red", "green", "blue", "qa_pixel"))

        if isinstance(include_assets, (list, tuple)):
            include_assets = tuple(include_assets)
        else:
            include_assets = ("red", "green", "blue", "qa_pixel")

        return LandsatSearchOptions(
            cloud_cover_max=float(cloud_cover) if cloud_cover is not None else None,
            path=int(path) if path is not None else None,
            row=int(row) if row is not None else None,
            platform=str(platform) if platform is not None else None,
            include_assets=include_assets,
        )

    def _build_stac_query(self, request: SearchRequest, options: LandsatSearchOptions) -> dict:
        """构建 STAC API 查询参数"""
        # 优先使用 request 中传入的空间范围；若无，则退回使用默认固定矩形
        if hasattr(request, "bbox") and request.bbox:
            bbox = list(request.bbox)
        elif hasattr(request, "aoi") and request.aoi:
            bbox = list(request.aoi.bounds)
        else:
            bbox = list(self.DEFAULT_AOI_BOUNDS)

        start_str = request.start_date.strftime("%Y-%m-%dT00:00:00Z")
        end_str = request.end_date.strftime("%Y-%m-%dT23:59:59Z")

        params = {
            "collections": ["landsat-c2-l2"],
            "bbox": bbox,
            "datetime": f"{start_str}/{end_str}",
            "limit": getattr(request, "max_results", 50),
            "query": {}
        }

        if options.cloud_cover_max is not None:
            params["query"]["eo:cloud_cover"] = {"lte": options.cloud_cover_max}

        if options.path is not None:
            params["query"]["landsat:wrs_path"] = {"eq": str(options.path).zfill(3)}

        if options.row is not None:
            params["query"]["landsat:wrs_row"] = {"eq": str(options.row).zfill(3)}

        if options.platform is not None:
            params["query"]["platform"] = {"eq": options.platform.lower()}

        if not params["query"]:
            del params["query"]

        return params

    def _parse_item(self, feature: dict, include_assets: Tuple[str, ...]) -> Optional[SatelliteProduct]:
        """解析 STAC Feature 为 SatelliteProduct，并自动完成 SAS 签名"""
        properties = feature.get("properties", {})
        raw_assets = feature.get("assets", {})

        product_id = feature.get("id", "")
        if not product_id:
            return None

        # 核心：使用 planetary_computer 对整个 feature 签名
        signed_assets = raw_assets
        if pc is not None:
            try:
                signed_feature = pc.sign(feature)
                signed_assets = signed_feature.get("assets", {})
            except Exception as e:
                logger.warning(f"Landsat 资产签名失败: {e}，将使用原始 URL")

        platform = properties.get("platform", "unknown")
        datetime_str = properties.get("datetime")
        if datetime_str:
            sensing_time = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
        else:
            sensing_time = datetime.now()

        cloud_cover = properties.get("eo:cloud_cover")
        geometry = feature.get("geometry", {})
        footprint = self._parse_footprint(geometry)

        # 资产过滤与映射
        include_keys_set = {k.lower() for k in include_assets}
        asset_list = []

        for stac_key, asset_data in signed_assets.items():
            if not isinstance(asset_data, dict):
                continue

            if stac_key.lower() in include_keys_set:
                href = asset_data.get("href")
                if href:
                    size = asset_data.get("file:size") or asset_data.get("size")
                    if size is not None:
                        try:
                            size = int(size)
                        except (TypeError, ValueError):
                            size = None

                    asset_list.append(ProductAsset(
                        key=stac_key.lower(),
                        title=asset_data.get("title", stac_key),
                        url=href,
                        size_bytes=size,
                        roles=tuple(asset_data.get("roles", ["data"])),
                    ))

        if not asset_list:
            return None

        size_bytes = sum(a.size_bytes for a in asset_list if a.size_bytes is not None) or None

        return SatelliteProduct(
            provider_id="landsat",
            product_id=product_id,
            name=product_id,
            sensing_time=sensing_time,
            footprint=footprint,
            cloud_cover=cloud_cover,
            size_bytes=size_bytes,
            online=True,
            assets=tuple(asset_list),
            metadata={
                "platform": platform,
                "wrs_path": properties.get("landsat:wrs_path"),
                "wrs_row": properties.get("landsat:wrs_row"),
                "collection": properties.get("collection"),
            }
        )

    def _parse_footprint(self, geometry: dict) -> Polygon:
        """解析 GeoJSON 几何为 Shapely Polygon"""
        try:
            if geometry:
                geom = shape(geometry)
                if geom.is_valid:
                    if isinstance(geom, Polygon):
                        return geom
                    return box(*geom.bounds)
        except Exception:
            pass
        return box(*self.DEFAULT_AOI_BOUNDS)

    def _filter_and_deduplicate(self, products: List[SatelliteProduct]) -> List[SatelliteProduct]:
        """按 product_id 去重"""
        seen = set()
        filtered = []
        for product in products:
            if product.product_id not in seen:
                seen.add(product.product_id)
                filtered.append(product)
        return filtered