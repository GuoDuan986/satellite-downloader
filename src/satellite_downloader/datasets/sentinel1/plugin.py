# src/satellite_downloader/datasets/sentinel1/plugin.py
from satellite_downloader.core.contracts import (
    SatelliteProvider,
    AuthSpec,
    AuthMode,
    FieldSpec,
    ColumnSpec,
    DownloadSpec,
)
from satellite_downloader.datasets.sentinel1.provider import Sentinel1Provider


class Sentinel1Plugin:
    """
    Sentinel-1 插件实现（遵循 DatasetPlugin 协议）
    负责向 GUI 界面暴露搜索表单规格、结果表格列定义及 Provider 工厂方法
    """
    plugin_id = "sentinel1"
    display_name = "Sentinel-1 IW GRD"

    # 1. 认证规格：支持 Copernicus CDSE 账号密码认证
    auth_spec = AuthSpec(mode=AuthMode.USERNAME_PASSWORD)

    # 2. 搜索字段规格：定义 UI 动态渲染的搜索表单控件
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

    # 3. 结果列规格：定义 UI 表格展示的列
    result_columns = (
        ColumnSpec(key="name", label="产品名称", width=280),
        ColumnSpec(key="sensing_time", label="成像时间", width=160),
        ColumnSpec(key="platform", label="平台", width=70),
        ColumnSpec(key="polarisation", label="极化", width=80),
        ColumnSpec(key="orbit_direction", label="轨道方向", width=90),
        ColumnSpec(key="relative_orbit", label="相对轨道号", width=90),
        ColumnSpec(key="processing_level", label="处理级别", width=80),  # 替换雷达无意义的云量列
        ColumnSpec(key="size_mb", label="大小 (MB)", width=90),  # 使用 size_mb 提升可读性
    )

    # 4. 下载规格：声明为整包下载（不支持拆分波段/资产下载）
    download_spec = DownloadSpec(supports_assets=False)

    def create_provider(self) -> SatelliteProvider:
        """创建并返回 Sentinel-1 Provider 实例"""
        return Sentinel1Provider()


# ✅ 导出 PLUGIN 实例对象（用于 PluginRegistry 自动扫描加载）
PLUGIN = Sentinel1Plugin()