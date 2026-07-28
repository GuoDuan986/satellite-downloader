# src/satellite_downloader/core/contracts.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Tuple

# 从 models 导入具体实现
from .models import ProductAsset, SatelliteProduct

#  检索请求
@dataclass(frozen=True)
class SearchRequest:
    start_date: date
    end_date: date
    max_results: int
    options: Mapping[str, object] = field(default_factory=dict)



# 认证模型
class AuthMode(Enum):
    NONE = "none"
    USERNAME_PASSWORD = "username_password"
    TOKEN = "token"

@dataclass(frozen=True)
class Credentials:
    username: str = ""
    password: str = ""
    token: str = ""

# 下载模型
@dataclass(frozen=True)
class DownloadPlan:
    product: SatelliteProduct
    destination: Path
    asset_keys: tuple[str, ...] = ()

@dataclass(frozen=True)
class DownloadResult:
    files: tuple[Path, ...]

@dataclass(frozen=True)
class DownloadProgressEvent:
    product_id: str
    asset_key: str
    current_bytes: int
    total_bytes: int | None


# ------------------ 占位符定义（消除标红，后续会完善） ------------------
# 因为 SatelliteProvider 和 Spec 类还没写，先用空壳占位

class SatelliteProvider(Protocol):
    """数据提供者接口（占位），后续在 providers 里实现"""
    pass

@dataclass(frozen=True)
class AuthSpec:
    """认证规格（占位）"""
    mode: str = "none"

@dataclass(frozen=True)
class FieldSpec:
    """搜索字段规格，定义 UI 上的输入控件"""
    key: str                      # 字段名，对应 options 字典中的键
    label: str                    # 显示标签
    field_type: str = "text"      # 控件类型：text, number, enum, boolean, date
    default: Any = None           # 默认值
    options: tuple[str, ...] = () # 当 field_type="enum" 时的可选值列表
    min_value: Optional[float] = None
    max_value: Optional[float] = None


@dataclass(frozen=True)
class ColumnSpec:
    """结果列规格，定义 UI 表格中的列"""
    key: str                      # 从 SatelliteProduct 或 metadata 中取值的键
    label: str                    # 列标题
    width: int = 100              # 列宽（像素）
    format: str = ""              # 格式化字符串


@dataclass(frozen=True)
class DownloadSpec:
    """下载规格"""
    supports_assets: bool = False   # 是否支持分资产下载（Landsat 为 True）

# 插件声明
class DatasetPlugin(Protocol):
    plugin_id: str
    display_name: str
    auth_spec: AuthSpec
    search_fields: tuple[FieldSpec, ...]
    result_columns: tuple[ColumnSpec, ...]
    download_spec: DownloadSpec

    def create_provider(self) -> SatelliteProvider:
        ...