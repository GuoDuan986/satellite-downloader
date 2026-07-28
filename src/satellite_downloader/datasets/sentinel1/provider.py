# src/satellite_downloader/datasets/sentinel1/provider.py
from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Mapping
from shapely.geometry import box, Polygon

from satellite_downloader.core.contracts import SatelliteProvider, SearchRequest, SatelliteProduct, ProductAsset
from satellite_downloader.shared.cdse import CDSEClient
from satellite_downloader.datasets.sentinel1.options import Sentinel1SearchOptions


class Sentinel1Provider(SatelliteProvider):
    """Sentinel-1 IW GRD 数据提供者"""

    # 固定 AOI（从项目配置读取）
    AOI_BOUNDS = (104.74993, 23.891659, 106.670617, 25.28654)

    def __init__(self, cdse_client: Optional[CDSEClient] = None):
        self.cdse_client = cdse_client

    def search(self, request: SearchRequest) -> List[SatelliteProduct]:
        """
        搜索 Sentinel-1 IW GRD 产品。
        """
        # 1. 解析专属参数
        s1_options = self._parse_options(request.options)

        # 2. 构建 OData 查询 URL
        query_url = self._build_odata_query(request, s1_options)

        # 3. 执行查询
        if self.cdse_client is None:
            raise RuntimeError("CDSE 客户端未初始化，请先设置 cdse_client")

        response = self.cdse_client.get(query_url)
        data = response.json()

        # 4. 解析响应，构建 SatelliteProduct 列表
        products = []
        for item in data.get("value", []):
            product = self._parse_item(item)
            if product:
                products.append(product)

        # 5. 本地足迹精确相交过滤 + 去重
        return self._filter_and_deduplicate(products)

    def _parse_options(self, options: Mapping[str, object]) -> Sentinel1SearchOptions:
        """从 SearchRequest.options 解析 Sentinel-1 专属参数"""
        return Sentinel1SearchOptions(
            polarisation=options.get("polarisation"),
            orbit_direction=options.get("orbit_direction"),
        )

    def _build_odata_query(
            self,
            request: SearchRequest,
            s1_options: Sentinel1SearchOptions
    ) -> str:
        xmin, ymin, xmax, ymax = self.AOI_BOUNDS
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

        filters.append(
            f"ContentDate/Start ge {request.start_date.isoformat()}T00:00:00.000Z"
        )
        filters.append(
            f"ContentDate/Start le {request.end_date.isoformat()}T23:59:59.999Z"
        )

        base_url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
        filter_str = " and ".join(filters)
        # ✅ 关键修复：添加 $expand=Attributes
        return f"{base_url}?$filter={filter_str}&$top={request.max_results}&$orderby=ContentDate/Start desc&$expand=Attributes"

    def _parse_item(self, item: dict) -> Optional[SatelliteProduct]:
        name = item.get("Name", "")
        if not name:
            return None

        parts = name.split("_")

        # 从文件名提取基础元数据
        platform = parts[0] if len(parts) > 0 else "Unknown"
        mode = parts[1] if len(parts) > 1 else "IW"
        product_type = parts[2] if len(parts) > 2 else "GRDH"
        processing_level = parts[3] if len(parts) > 3 else ""

        # 极化方式：从处理级别中提取（如 1SDV → DV → VV+VH）
        polarisation = ""
        if processing_level.startswith("1S"):
            pol_code = processing_level[2:]
            if pol_code == "DV":
                polarisation = "VV+VH"
            elif pol_code == "DH":
                polarisation = "HH+HV"
            elif pol_code == "SV":
                polarisation = "VV"
            elif pol_code == "SH":
                polarisation = "HH"
            else:
                polarisation = pol_code

        # 相对轨道号：从文件名第7段提取
        relative_orbit = parts[6] if len(parts) > 6 else None

        # ========== ✅ 关键修复：从 Attributes 数组中提取轨道方向 ==========
        attributes_list = item.get("Attributes", [])
        attr_dict = {}
        if isinstance(attributes_list, list):
            for attr in attributes_list:
                if isinstance(attr, dict) and "Name" in attr and "Value" in attr:
                    attr_dict[attr["Name"]] = attr["Value"]

        # 优先从 Attributes 获取，如果没有则回退到根节点（兼容性）
        orbit_direction = (
                attr_dict.get("orbitDirection") or
                item.get("orbitDirection") or
                ""
        )

        # 如果 Attributes 中有 polarizationChannels，优先使用（比从文件名解析更准确）
        if "polarizationChannels" in attr_dict:
            pol_channels = attr_dict.get("polarizationChannels", "")
            # 例如 "VV,VH" -> "VV+VH"
            if pol_channels and "," in pol_channels:
                polarisation = pol_channels.replace(",", "+")
            elif pol_channels:
                polarisation = pol_channels
        # ================================================================

        # 几何足迹
        geometry_json = item.get("Geometry", {})
        footprint = self._parse_footprint(geometry_json)

        # 资产（整包 ZIP）
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

        # 成像时间
        content_date = item.get("ContentDate", {})
        sensing_time_str = content_date.get("Start", "")
        if sensing_time_str:
            sensing_time = datetime.fromisoformat(sensing_time_str.replace("Z", "+00:00"))
        else:
            sensing_time = datetime.now()

        return SatelliteProduct(
            provider_id="sentinel1",
            product_id=item.get("Id", ""),
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
                "orbit_direction": orbit_direction,  # ✅ 现在能正确获取了
                "relative_orbit": relative_orbit,
                "processing_level": processing_level,
                "_attr_dict": attr_dict,  # 调试用，可保留
            }
        )

    def _parse_footprint(self, geometry_json: dict) -> Polygon:
        """从 CDSE 返回的 Geometry 字段解析足迹多边形"""
        if geometry_json.get("type") == "Polygon":
            coordinates = geometry_json.get("coordinates", [])
            if coordinates and len(coordinates) > 0:
                ring = [(lon, lat) for lon, lat in coordinates[0]]
                return Polygon(ring)
        # 无法解析则返回默认 AOI 矩形
        xmin, ymin, xmax, ymax = self.AOI_BOUNDS
        return box(xmin, ymin, xmax, ymax)

    def _filter_and_deduplicate(self, products: List[SatelliteProduct]) -> List[SatelliteProduct]:
        """本地足迹精确相交过滤 + 按 product_id 去重"""
        aoi_polygon = box(*self.AOI_BOUNDS)
        seen = set()
        filtered = []
        for product in products:
            if product.footprint.intersects(aoi_polygon):
                if product.product_id not in seen:
                    seen.add(product.product_id)
                    filtered.append(product)
        return filtered