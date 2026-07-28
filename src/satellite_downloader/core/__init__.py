# src/satellite_downloader/core/__init__.py
from .contracts import (
    SearchRequest,
    Credentials,
    AuthMode,
    DownloadPlan,
    DownloadResult,
    DownloadProgressEvent,
    DatasetPlugin,
    SatelliteProvider,
    AuthSpec,
    FieldSpec,
    ColumnSpec,
    DownloadSpec,
)
from .models import ProductAsset, SatelliteProduct
from .registry import PluginRegistry

__all__ = [
    # contracts
    "SearchRequest",
    "Credentials",
    "AuthMode",
    "DownloadPlan",
    "DownloadResult",
    "DownloadProgressEvent",
    "DatasetPlugin",
    "SatelliteProvider",
    "AuthSpec",
    "FieldSpec",
    "ColumnSpec",
    "DownloadSpec",
    # models
    "ProductAsset",
    "SatelliteProduct",
    # registry
    "PluginRegistry",
]