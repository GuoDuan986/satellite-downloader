# src/satellite_downloader/core/workers.py
"""
通用搜索和下载 Worker

职责：
- 连接 UI/插件 和 具体 Provider
- 从应用配置中读取认证信息
- 支持通用搜索和资产级顺序/断点下载，进度反馈和取消
"""
from typing import List, Optional, Callable, Dict, Any
from pathlib import Path
import logging
import requests

from .contracts import SearchRequest, SatelliteProduct, DownloadPlan, DownloadProgressEvent
from .registry import PluginRegistry
from ..shared.cdse import CDSEClient

logger = logging.getLogger(__name__)


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
    """通用搜索 Worker"""
    registry = PluginRegistry()
    plugin = registry.get_plugin(plugin_id)
    if plugin is None:
        raise ValueError(f"未找到插件: {plugin_id}")

    provider = plugin.create_provider()

    # 依赖注入 CDSE Client
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
    通用下载 Worker（无分支多资产流式下载引擎）
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

    # ✅ 架构解耦：若 Provider 自身提供了自定义下载方法，优先调用 Provider 原生方法
    if hasattr(provider, "download"):
        return provider.download(plan, progress_callback, cancel_check)

    # 默认通用多资产下载器（适用于 Landsat 等 STAC 资产或通用 HTTP URL）
    return _generic_download_assets(plan, provider, progress_callback, cancel_check)


def _generic_download_assets(
        plan: DownloadPlan,
        provider: Any,
        progress_callback: Optional[Callable[[DownloadProgressEvent], None]],
        cancel_check: Optional[Callable[[], bool]],
) -> List[Path]:
    """
    通用多资产顺序下载器（支持 Range 续传、防高频刷屏、错误隔离）
    """
    downloaded_files = []

    # 判别整包与多资产目标路径格式
    if len(plan.product.assets) == 1 and plan.product.assets[0].key in ("zip", "download"):
        product_dir = plan.destination
    else:
        product_dir = plan.destination / plan.product.product_id
        product_dir.mkdir(parents=True, exist_ok=True)

    # 资产过滤
    asset_keys = plan.asset_keys if plan.asset_keys else [a.key for a in plan.product.assets]
    assets_to_download = [a for a in plan.product.assets if a.key in asset_keys]

    for asset in assets_to_download:
        # 1. 如果 Provider 拥有 CDSE Client，优先使用 CDSE Client 下载
        if hasattr(provider, "cdse_client") and provider.cdse_client is not None:
            local_path = product_dir / f"{plan.product.name}.zip"

            def _cdse_prog(c, t):
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
                progress_callback=_cdse_prog,
                cancel_check=cancel_check,
            )
            downloaded_files.append(local_path)
            continue

        # 2. 通用 HTTP GET 资产下载逻辑
        suffix = Path(asset.url.split("?")[0]).suffix or ".tif"
        local_path = product_dir / f"{asset.key}{suffix}"
        part_path = local_path.with_suffix(local_path.suffix + ".part")

        if local_path.exists():
            downloaded_files.append(local_path)
            if progress_callback:
                progress_callback(DownloadProgressEvent(
                    product_id=plan.product.product_id,
                    asset_key=asset.key,
                    current_bytes=local_path.stat().st_size,
                    total_bytes=local_path.stat().st_size
                ))
            continue

        downloaded_bytes = 0
        total_size = asset.size_bytes

        try:
            existing_size = part_path.stat().st_size if part_path.exists() else 0
            headers = {"Range": f"bytes={existing_size}-"} if existing_size > 0 else {}

            response = requests.get(asset.url, headers=headers, stream=True, timeout=60)
            response.raise_for_status()

            if response.status_code == 206:
                mode = "ab"
            else:
                if existing_size > 0:
                    part_path.unlink(missing_ok=True)
                    existing_size = 0
                mode = "wb"

            content_length = response.headers.get("content-length")
            if content_length:
                total_size = int(content_length) + existing_size

            downloaded_bytes = existing_size

            # 防频刷屏：控制回调触发阈值（每 256KB 或传输结束触发）
            CHUNK_SIZE = 64 * 1024  # 64KB
            NOTIFY_EVERY = 256 * 1024  # 256KB
            last_notified_bytes = downloaded_bytes

            with open(part_path, mode) as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if cancel_check and cancel_check():
                        response.close()
                        raise InterruptedError(f"用户取消了下载: {asset.key}")

                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)

                        if progress_callback and (downloaded_bytes - last_notified_bytes >= NOTIFY_EVERY):
                            last_notified_bytes = downloaded_bytes
                            progress_callback(DownloadProgressEvent(
                                product_id=plan.product.product_id,
                                asset_key=asset.key,
                                current_bytes=downloaded_bytes,
                                total_bytes=total_size
                            ))

            # 下载完成发送最后 100% 状态通知
            if progress_callback:
                progress_callback(DownloadProgressEvent(
                    product_id=plan.product.product_id,
                    asset_key=asset.key,
                    current_bytes=downloaded_bytes,
                    total_bytes=total_size
                ))

            part_path.rename(local_path)
            downloaded_files.append(local_path)

        except InterruptedError:
            logger.info(f"🛑 下载任务已取消，停止剩余资产下载: {asset.key}")
            break

        except Exception as e:
            logger.warning(f"⚠️ 下载资产 {asset.key} 失败: {e}，跳过并继续")
            if progress_callback:
                progress_callback(DownloadProgressEvent(
                    product_id=plan.product.product_id,
                    asset_key=asset.key,
                    current_bytes=downloaded_bytes,
                    total_bytes=total_size
                ))

    return downloaded_files