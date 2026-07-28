# src/satellite_downloader/datasets/sentinel1/plugin.py
from satellite_downloader.core.contracts import (
    SatelliteProvider,
    AuthSpec,
    FieldSpec,
    ColumnSpec,
    DownloadSpec,
)
from satellite_downloader.datasets.sentinel1.provider import Sentinel1Provider


class Sentinel1Plugin:
    """Sentinel-1 插件实现（满足 DatasetPlugin 协议）"""
    plugin_id = "sentinel1"
    display_name = "Sentinel-1 IW GRD"
    auth_spec = AuthSpec(mode="username_password")

    # 搜索字段：定义界面上显示的搜索控件
    search_fields = (
        FieldSpec(
            key="polarisation",
            label="极化方式",
            field_type="enum",
            default="VV+VH",
            options=("VV", "VH", "HH", "HV", "VV+VH", "HH+HV"),
        ),
        FieldSpec(
            key="orbit_direction",
            label="轨道方向",
            field_type="enum",
            default="DESCENDING",
            options=("ASCENDING", "DESCENDING"),
        ),
    )

    # 结果列：定义结果表格中显示的列
    result_columns = (
        ColumnSpec(key="name", label="产品名称", width=300),
        ColumnSpec(key="sensing_time", label="成像时间", width=180),
        ColumnSpec(key="platform", label="平台", width=80),
        ColumnSpec(key="polarisation", label="极化", width=80),
        ColumnSpec(key="orbit_direction", label="轨道方向", width=100),
        ColumnSpec(key="relative_orbit", label="相对轨道号", width=100),
        ColumnSpec(key="cloud_cover", label="云量 (%)", width=80),
        ColumnSpec(key="size_bytes", label="大小 (MB)", width=100),
    )

    download_spec = DownloadSpec(supports_assets=False)

    def create_provider(self) -> SatelliteProvider:
        """返回 Sentinel-1 Provider 实例"""
        return Sentinel1Provider()


# ✅ 导出 PLUGIN 对象（registry 通过此名称发现）
PLUGIN = Sentinel1Plugin()