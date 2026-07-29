# src/satellite_downloader/datasets/landsat/plugin.py
from satellite_downloader.core.contracts import (
    SatelliteProvider,
    AuthSpec,
    FieldSpec,
    ColumnSpec,
    DownloadSpec,
)
from .provider import LandsatProvider


class LandsatPlugin:
    plugin_id = "landsat"
    display_name = "Landsat 8/9 Collection 2 Level-2"

    # STAC 检索不需要用户登录（签名在 Provider 内部通过 API 完成）
    auth_spec = AuthSpec(mode="none")

    # 动态 UI 查询表单定义
    search_fields = (
        FieldSpec(
            key="cloud_cover_max",
            label="云量上限 (%)",
            field_type="number",
            default=50,
            min_value=0,
            max_value=100,
        ),
        FieldSpec(
            key="path",
            label="WRS Path",
            field_type="number",
            default=None,
            min_value=1,
            max_value=233,
        ),
        FieldSpec(
            key="row",
            label="WRS Row",
            field_type="number",
            default=None,
            min_value=1,
            max_value=248,
        ),
        FieldSpec(
            key="platform",
            label="卫星平台",
            field_type="enum",
            default=None,
            options=("landsat-8", "landsat-9"),
        ),
    )

    # 动态 UI 表格列定义（修正了与 SatelliteProduct.metadata 匹配的 key）
    result_columns = (
        ColumnSpec(key="name", label="产品 ID", width=250),
        ColumnSpec(key="sensing_time", label="成像时间", width=180),
        ColumnSpec(key="cloud_cover", label="云量 (%)", width=80),
        ColumnSpec(key="metadata.platform", label="平台", width=90),
        ColumnSpec(key="metadata.wrs_path", label="Path", width=60),
        ColumnSpec(key="metadata.wrs_row", label="Row", width=60),
        ColumnSpec(key="size_bytes", label="大小 (MB)", width=100),
    )

    # 显式声明支持多资产选择与独立/顺序下载
    download_spec = DownloadSpec(supports_assets=True)

    def create_provider(self) -> SatelliteProvider:
        return LandsatProvider()


PLUGIN = LandsatPlugin()