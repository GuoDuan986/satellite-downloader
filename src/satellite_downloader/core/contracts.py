# src/satellite_downloader/core/contracts.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Tuple
from shapely.geometry.base import BaseGeometry

# 从 models 导入具体数据模型实现
from .models import ProductAsset, SatelliteProduct


# ==========================================
# 1. 认证模型 (Auth Models)
# ==========================================

class AuthMode(Enum):
    NONE = "none"
    USERNAME_PASSWORD = "username_password"
    TOKEN = "token"


@dataclass(frozen=True)
class Credentials:
    username: str = ""
    password: str = ""
    token: str = ""


# ==========================================
# 2. 检索请求模型 (Search Request)
# ==========================================

@dataclass(frozen=True)
class SearchRequest:
    """
    公共检索请求契约
    支持时间范围、最大结果数、空间范围 (bbox/aoi) 以及特定卫星的扩展选项
    """
    start_date: date
    end_date: date
    max_results: int = 50
    # 空间范围二选一：4元组(xmin, ymin, xmax, ymax) 或 Shapely 几何图形
    bbox: Optional[Tuple[float, float, float, float]] = None
    aoi: Optional[BaseGeometry] = None
    options: Mapping[str, object] = field(default_factory=dict)


# ==========================================
# 3. 下载模型 (Download Models)
# ==========================================

@dataclass(frozen=True)
class DownloadPlan:
    """下载计划，由 UI/Worker 构建"""
    product: SatelliteProduct
    destination: Path
    asset_keys: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DownloadResult:
    """下载完成结果"""
    files: Tuple[Path, ...]


@dataclass(frozen=True)
class DownloadProgressEvent:
    """
    下载进度事件
    用于向 UI/回调函数汇报实时进度，支持多资产 (asset_key) 分开汇报
    """
    product_id: str
    asset_key: str
    current_bytes: int
    total_bytes: Optional[int] = None


# ==========================================
# 4. 元数据驱动 UI 规格 (UI Dynamic Specs)
# ==========================================

@dataclass(frozen=True)
class AuthSpec:
    """认证规格定义"""
    mode: AuthMode = AuthMode.NONE


@dataclass(frozen=True)
class FieldSpec:
    """搜索字段规格：用于 UI 动态渲染检索表单组件"""
    key: str                      # 映射到 SearchRequest.options 中的键名
    label: str                    # UI 界面显示的文本标签
    field_type: str = "text"      # 控件类型：text, number, enum, boolean, date
    default: Any = None           # 默认值
    options: Tuple[str, ...] = () # 当 field_type="enum" 时的下拉菜单可选项
    min_value: Optional[float] = None
    max_value: Optional[float] = None


@dataclass(frozen=True)
class ColumnSpec:
    """结果列规格：用于 UI 动态渲染结果表格的列"""
    key: str                      # 从 SatelliteProduct 或其 metadata 中读取的键名
    label: str                    # 表格列标题
    width: int = 100              # 列宽（像素）
    format: str = ""              # 格式化模板


@dataclass(frozen=True)
class DownloadSpec:
    """下载规格定义"""
    supports_assets: bool = False # 是否支持分资产（如 RGB, QA_PIXEL）选择下载


# ==========================================
# 5. 核心接口协议 (Protocols)
# ==========================================

class SatelliteProvider(Protocol):
    """
    数据提供者核心接口协议
    LandsatProvider 和 Sentinel1Provider 均需遵循此协议
    """
    def search(self, request: SearchRequest) -> list[SatelliteProduct]:
        """根据标准检索请求，返回符合条件的产品列表"""
        ...


class DatasetPlugin(Protocol):
    """
    数据集插件核心接口协议
    用于向插件注册表 (PluginRegistry) 暴露自身的元数据规范与 Provider 工厂方法
    """
    plugin_id: str
    display_name: str
    auth_spec: AuthSpec
    search_fields: Tuple[FieldSpec, ...]
    result_columns: Tuple[ColumnSpec, ...]
    download_spec: DownloadSpec

    def create_provider(self) -> SatelliteProvider:
        """创建对应的 SatelliteProvider 实例"""
        ...