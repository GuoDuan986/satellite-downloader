# src/satellite_downloader/core/workers.py
"""
通用搜索和下载 Worker

职责：
- 连接 UI/插件 和 具体 Provider
- 从应用配置中读取认证信息
- 支持搜索和下载，进度反馈和取消
"""
from typing import List, Optional, Callable, Dict, Any
from pathlib import Path
import os

from .contracts import SearchRequest, SatelliteProduct, DownloadPlan, DownloadProgressEvent
from .registry import PluginRegistry
from ..shared.cdse import CDSEClient


class WorkerContext:
    """
    Worker 上下文：存储全局配置，如 CDSE 账号、下载目录等。
    由应用启动时初始化，供所有 Worker 使用。
    """
    cdse_username: str = ""
    cdse_password: str = ""
    download_dir: Path = Path("./downloads")
    _cdse_client_cache: Dict[str, CDSEClient] = {}

    @classmethod
    def init(cls, username: str = "", password: str = "", download_dir: Optional[Path] = None):
        cls.cdse_username = username
        cls.cdse_password = password
        if download_dir:
            cls.download_dir = download_dir
        cls.download_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_cdse_client(cls, provider_id: str) -> Optional[CDSEClient]:
        """获取 CDSE 客户端（缓存）"""
        if not cls.cdse_username or not cls.cdse_password:
            return None
        key = f"{cls.cdse_username}_{provider_id}"
        if key not in cls._cdse_client_cache:
            cls._cdse_client_cache[key] = CDSEClient(cls.cdse_username, cls.cdse_password)
        return cls._cdse_client_cache[key]


def search_products(
        plugin_id: str,
        request: SearchRequest,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
) -> List[SatelliteProduct]:
    """
    通用搜索 Worker

    Args:
        plugin_id: 插件 ID（如 'sentinel1', 'sentinel2', 'landsat'）
        request: 搜索请求（包含日期、选项等）
        progress_callback: 进度回调 (current, total)
        cancel_check: 取消检查函数，返回 True 表示取消

    Returns:
        产品列表
    """
    registry = PluginRegistry()
    plugin = registry.get_plugin(plugin_id)
    if plugin is None:
        raise ValueError(f"未找到插件: {plugin_id}")

    provider = plugin.create_provider()

    # 如果 Provider 需要 CDSE 客户端，注入
    if hasattr(provider, "cdse_client"):
        client = WorkerContext.get_cdse_client(plugin_id)
        if client:
            provider.cdse_client = client

    if progress_callback:
        progress_callback(0, 1)

    if cancel_check and cancel_check():
        return []

    products = provider.search(request)

    if progress_callback:
        progress_callback(1, 1)

    return products


def download_product(
        plan: DownloadPlan,
        progress_callback: Optional[Callable[[DownloadProgressEvent], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
) -> List[Path]:
    """
    通用下载 Worker

    Args:
        plan: 下载计划（包含产品、目标路径、资产键）
        progress_callback: 进度回调，接收 DownloadProgressEvent
        cancel_check: 取消检查函数

    Returns:
        下载完成的文件路径列表

    Raises:
        ValueError: 插件不存在或 Provider 不支持下载
        RuntimeError: 下载失败
    """
    registry = PluginRegistry()
    plugin = registry.get_plugin(plan.product.provider_id)
    if plugin is None:
        raise ValueError(f"未找到插件: {plan.product.provider_id}")

    provider = plugin.create_provider()

    # 注入 CDSE 客户端
    client = WorkerContext.get_cdse_client(plan.product.provider_id)
    if hasattr(provider, "cdse_client") and client:
        provider.cdse_client = client

    # 根据 Provider 类型分发下载逻辑
    provider_id = plan.product.provider_id
    if provider_id == "sentinel1":
        return _download_sentinel1(plan, provider, progress_callback, cancel_check)
    elif provider_id == "sentinel2":
        return _download_sentinel2(plan, provider, progress_callback, cancel_check)
    elif provider_id == "landsat":
        return _download_landsat(plan, provider, progress_callback, cancel_check)
    else:
        raise ValueError(f"不支持的 Provider: {provider_id}")


def _download_sentinel1(
        plan: DownloadPlan,
        provider,
        progress_callback: Optional[Callable[[DownloadProgressEvent], None]],
        cancel_check: Optional[Callable[[], bool]],
) -> List[Path]:
    """S1 整包 ZIP 下载"""
    if not hasattr(provider, "cdse_client") or provider.cdse_client is None:
        raise RuntimeError("S1 Provider 未初始化 CDSE 客户端，请先登录")

    downloaded = []
    for asset in plan.product.assets:
        if asset.key == "zip":
            local_path = plan.destination / f"{plan.product.name}.zip"

            def _progress(c, t):
                if progress_callback:
                    progress_callback(DownloadProgressEvent(
                        product_id=plan.product.product_id,
                        asset_key=asset.key,
                        current_bytes=c,
                        total_bytes=t
                    ))

            provider.cdse_client.download(
                asset.url,
                local_path,
                expected_md5=asset.checksum,
                progress_callback=_progress,
                cancel_check=cancel_check,
            )
            downloaded.append(local_path)
            break
    return downloaded


def _download_sentinel2(
        plan: DownloadPlan,
        provider,
        progress_callback: Optional[Callable[[DownloadProgressEvent], None]],
        cancel_check: Optional[Callable[[], bool]],
) -> List[Path]:
    """S2 整包 ZIP 下载（同 S1）"""
    # S2 和 S1 的下载逻辑相同，都是整包 ZIP
    return _download_sentinel1(plan, provider, progress_callback, cancel_check)


def _download_landsat(
        plan: DownloadPlan,
        provider,
        progress_callback: Optional[Callable[[DownloadProgressEvent], None]],
        cancel_check: Optional[Callable[[], bool]],
) -> List[Path]:
    """
    Landsat 多资产下载（RGB + QA_PIXEL）
    每个资产独立下载，支持断点续传
    """
    if not hasattr(provider, "cdse_client") or provider.cdse_client is None:
        # Landsat 可能不需要 CDSE（STAC 源），但如果有 CDSE 客户端则使用
        pass

    downloaded = []
    product_dir = plan.destination / plan.product.product_id
    product_dir.mkdir(parents=True, exist_ok=True)

    for asset in plan.product.assets:
        if plan.asset_keys and asset.key not in plan.asset_keys:
            continue

        local_path = product_dir / f"{asset.key}.tif"

        # 如果有 CDSE 客户端，使用它下载
        if hasattr(provider, "cdse_client") and provider.cdse_client:
            def _progress(c, t):
                if progress_callback:
                    progress_callback(DownloadProgressEvent(
                        product_id=plan.product.product_id,
                        asset_key=asset.key,
                        current_bytes=c,
                        total_bytes=t
                    ))

            provider.cdse_client.download(
                asset.url,
                local_path,
                expected_md5=asset.checksum,
                progress_callback=_progress,
                cancel_check=cancel_check,
            )
        else:
            # 降级方案：使用 requests 直接下载
            import requests
            response = requests.get(asset.url, stream=True)
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            downloaded_bytes = 0
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if cancel_check and cancel_check():
                        raise RuntimeError("下载已取消")
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)
                        if progress_callback:
                            progress_callback(DownloadProgressEvent(
                                product_id=plan.product.product_id,
                                asset_key=asset.key,
                                current_bytes=downloaded_bytes,
                                total_bytes=total
                            ))
        downloaded.append(local_path)

    return downloaded