# src/satellite_downloader/core/registry.py
from __future__ import annotations
import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional, Union

from .contracts import DatasetPlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    插件注册表，自动发现 datasets/ 目录下的所有插件。

    使用方式：
        registry = PluginRegistry()
        registry.discover()
        plugins = registry.get_plugins()
        landsat_plugin = registry.get_plugin("landsat")
    """

    def __init__(self):
        self._plugins: Dict[str, DatasetPlugin] = {}
        self._discovered = False

    def discover(self, package_path: Optional[Union[Path, Sequence[str]]] = None) -> None:
        """
        扫描 datasets/ 目录，发现并加载所有插件。

        Args:
            package_path: 可选，指定扫描路径或包路径列表，默认为 'satellite_downloader.datasets'
        """
        if self._discovered:
            return

        target_paths = None
        package_name = "satellite_downloader.datasets"

        # 如果没有指定路径，使用默认的 datasets 包
        if package_path is None:
            try:
                import satellite_downloader.datasets as datasets_pkg
                target_paths = datasets_pkg.__path__
                package_name = datasets_pkg.__name__
            except ImportError:
                # datasets 包不存在，标记为已扫描后安全退出
                logger.warning("未找到 satellite_downloader.datasets 包，插件发现中止")
                self._discovered = True
                return
        else:
            # 路径兼容性保护：若传入 Path 对象，转为 [str(Path)]
            if isinstance(package_path, Path):
                target_paths = [str(package_path)]
            else:
                target_paths = package_path

        # 遍历 datasets 下的所有子目录模块
        for module_info in pkgutil.iter_modules(target_paths):
            if module_info.ispkg:
                module_name = module_info.name
                try:
                    # 动态导入：satellite_downloader.datasets.<submodule>.plugin
                    plugin_module = importlib.import_module(
                        f"{package_name}.{module_name}.plugin"
                    )
                    # 检查是否包含 PLUGIN 导出对象
                    if hasattr(plugin_module, "PLUGIN"):
                        plugin = plugin_module.PLUGIN
                        # 鸭子类型属性检查
                        if all(hasattr(plugin, attr) for attr in
                               ["plugin_id", "display_name", "create_provider"]):
                            self._plugins[plugin.plugin_id] = plugin
                            logger.info(f"✅ 已加载插件：{plugin.display_name} ({plugin.plugin_id})")
                        else:
                            logger.warning(f"⚠️ {module_name}/plugin.py 中的 PLUGIN 缺少必要属性，跳过加载")
                except ImportError:
                    # plugin.py 不存在或子包未完成，静默跳过（符合两人分工、渐进式开发原则）
                    pass
                except Exception as e:
                    logger.error(f"❌ 加载插件 {module_name} 失败: {e}", exc_info=True)

        self._discovered = True

    def get_plugins(self) -> List[DatasetPlugin]:
        """返回所有已发现的插件实例列表"""
        if not self._discovered:
            self.discover()
        return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> Optional[DatasetPlugin]:
        """根据 plugin_id 获取指定的插件，不存在时返回 None"""
        if not self._discovered:
            self.discover()
        return self._plugins.get(plugin_id)

    def get_plugin_ids(self) -> List[str]:
        """返回所有已发现插件的 ID 列表 (如 ['landsat', 'sentinel1'])"""
        if not self._discovered:
            self.discover()
        return list(self._plugins.keys())

    def clear(self) -> None:
        """清空注册表（主要用于单元测试隔离）"""
        self._plugins.clear()
        self._discovered = False

    def is_discovered(self) -> bool:
        """返回是否已经执行过发现操作"""
        return self._discovered