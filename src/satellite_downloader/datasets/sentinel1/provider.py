# src/satellite_downloader/datasets/sentinel1/provider.py
from __future__ import annotations
import logging
from datetime import datetime, date
from typing import List, Optional, Mapping
from shapely.geometry import box, Polygon

from satellite_downloader.core.contracts import SatelliteProvider, SearchRequest, SatelliteProduct, ProductAsset
from satellite_downloader.shared.cdse import CDSEClient
from satellite_downloader.datasets.sentinel1.options import Sentinel1SearchOptions

logger = logging.getLogger(__name__)


class Sentinel1Provider(SatelliteProvider):
    """Sentinel-1 IW GRD 数据提供者 (CDSE OData)"""

    # 默认固定 AOI（当 request 未显式传入空间范围时使用）
    DEFAULT_AOI_BOUNDS = (104.74993, 23.891659, 106.670617, 25.28654)

    def __init__(self, cdse_client: Optional[CDSEClient] = None):
        self.cdse_client = cdse_client

    def search(self, request: SearchRequest) -> List[SatelliteProduct]:
        """搜索 Sentinel-1 IW GRD 产品"""
        s1_options = self._parse_options(request.options)
        query_url = self._build_odata_query(request, s1_options)

        if self.cdse_client is None:
            raise RuntimeError("CDSE 客户端未初始化，请先在 Worker 中注入或登录 cdse_client")

        response = self.cdse_client.get(query_url)
        data = response.json()

        products = []
        for item in data.get("value", []):
            product = self._parse_item(item)
            if product:
                products.append(product)

        # 本地足迹精确相交过滤 + 去重
        return self._filter_and_deduplicate(products, request)

    def _parse_options(self, options: Mapping[str, object]) -> Sentinel1SearchOptions:
        """从 SearchRequest.options 解析 Sentinel-1 专属参数"""
        return Sentinel1SearchOptions(
            polarisation=options.get("polarisation"),
            orbit_direction=options.get("orbit_direction"),
        )

    def _get_request_bounds(self, request: SearchRequest) -> tuple[float, float, float, float]:
        """解析检索请求中的空间范围，若无则退回默认 AOI"""
        if hasattr(request, "bbox") and request.bbox:
            return request.bbox
        elif hasattr(request, "aoi") and request.aoi:
            return request.aoi.bounds
        return self.DEFAULT_AOI_BOUNDS

    def _build_odata_query(
            self,
            request: SearchRequest,
            s1_options: Sentinel1SearchOptions
    ) -> str:
        # ✅ 动态提取空间范围
        xmin, ymin, xmax, ymax = self._get_request_bounds(request)
        wkt_polygon = f"POLYGON(({xmin} {ymin}, {xmax} {ymin}, {xmax} {ymax}, {xmin} {ymax}, {xmin} {ymin}))"

        filters = [
            "Collection/Name eq 'SENTINEL-1'",
            "contains(Name, 'IW_GRDH')",
            f"OData.CSC.Intersects(area=geography'SRID=4326;{wkt_polygon}')",
        ]

        if s1_options.polarisation:
            filters.append(f"polarisationMode eq '{s1_options.polarisation}'")
        if s1_options.orbit_direction:
            filters.append(f"orbitDirection eq '{s1_options.orbit_direction}'")

        # 安全格式化日期
        start_str = request.start_date.strftime("%Y-%m-%d") if isinstance(request.start_date, (date, datetime)) else str(request.start_date)
        end_str = request.end_date.strftime("%Y-%m-%d") if isinstance(request.end_date, (date, datetime)) else str(request.end_date)

        filters.append(f"ContentDate/Start ge {start_str}T00:00:00.000Z")
        filters.append(f"ContentDate/Start le {end_str}T23:59:59.999Z")

        base_url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
        filter_str = " and ".join(filters)
        return f"{base_url}?$filter={filter_str}&$top={request.max_results}&$orderby=ContentDate/Start desc&$expand=Attributes"

    def _parse_item(self, item: dict) -> Optional[SatelliteProduct]:
        name = item.get("Name", "")
        if not name:
            return None

        parts = name.split("_")

        platform = parts[0] if len(parts) > 0 else "Unknown"
        mode = parts[1] if len(parts) > 1 else "IW"
        product_type = parts[2] if len(parts) > 2 else "GRDH"
        processing_level = parts[3] if len(parts) > 3 else ""

        # 默认从文件名解析极化
        polarisation = ""
        if processing_level.startswith("1S"):
            pol_code = processing_level[2:]
            pol_map = {"DV": "VV+VH", "DH": "HH+HV", "SV": "VV", "SH": "HH"}
            polarisation = pol_map.get(pol_code, pol_code)

        relative_orbit = parts[6] if len(parts) > 6 else None

        # 从 Attributes 数组提取元数据
        attributes_list = item.get("Attributes", [])
        attr_dict = {}
        if isinstance(attributes_list, list):
            for attr in attributes_list:
                if isinstance(attr, dict) and "Name" in attr and "Value" in attr:
                    attr_dict[attr["Name"]] = attr["Value"]

        orbit_direction = (
                attr_dict.get("orbitDirection") or
                item.get("orbitDirection") or
                ""
        )

        if "polarizationChannels" in attr_dict:
            pol_channels = attr_dict.get("polarizationChannels", "")
            if pol_channels and "," in pol_channels:
                polarisation = pol_channels.replace(",", "+")
            elif pol_channels:
                polarisation = pol_channels

        geometry_json = item.get("Geometry", {})
        footprint = self._parse_footprint(geometry_json)

        # 构造整包 ZIP 资产
        assets = []
        online = item.get("Online", False)
        if online:
            product_id = item.get("Id")
            if product_id:
                download_url = f"https://download.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"
                size = item.get("Size", 0)
                checksum_dict = item.get("Checksum", {})
                checksum = checksum_dict.get("MD5") if isinstance(checksum_dict, dict) else None
                assets.append(ProductAsset(
                    key="zip",
                    title="完整产品包 (.SAFE)",
                    url=download_url,
                    size_bytes=size,
                    checksum=checksum,
                    roles=("data", "archive"),
                ))

        content_date = item.get("ContentDate", {})
        sensing_time_str = content_date.get("Start", "")
        if sensing_time_str:
            sensing_time = datetime.fromisoformat(sensing_time_str.replace("Z", "+00:00"))
        else:
            sensing_time = datetime.now()

        return SatelliteProduct(
            provider_id="sentinel1",
            product_id=str(item.get("Id", "")),
            name=name,
            sensing_time=sensing_time,
            footprint=footprint,
            cloud_cover=None,
            size_bytes=item.get("Size", 0),
            online=online,
            assets=tuple(assets),
            metadata={
                "platform": platform,
                "mode": mode,
                "product_type": product_type,
                "polarisation": polarisation,
                "orbit_direction": orbit_direction,
                "relative_orbit": relative_orbit,
                "processing_level": processing_level,
            }
        )

    def _parse_footprint(self, geometry_json: dict) -> Polygon:
        """从 CDSE 返回的 Geometry 字段解析足迹多边形"""
        try:
            if geometry_json.get("type") == "Polygon":
                coordinates = geometry_json.get("coordinates", [])
                if coordinates and len(coordinates) > 0:
                    ring = [(lon, lat) for lon, lat in coordinates[0]]
                    return Polygon(ring)
        except Exception as e:
            logger.debug(f"解析 Sentinel-1 足迹 Geometry 失败: {e}")

        xmin, ymin, xmax, ymax = self.DEFAULT_AOI_BOUNDS
        return box(xmin, ymin, xmax, ymax)

    def _filter_and_deduplicate(self, products: List[SatelliteProduct], request: SearchRequest) -> List[SatelliteProduct]:
        """本地足迹精确相交过滤 + 去重"""
        bounds = self._get_request_bounds(request)
        aoi_polygon = box(*bounds)
        seen = set()
        filtered = []
        for product in products:
            if product.footprint.intersects(aoi_polygon):
                if product.product_id not in seen:
                    seen.add(product.product_id)
                    filtered.append(product)
        return filtered