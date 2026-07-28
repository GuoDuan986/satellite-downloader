# src/satellite_downloader/core/registry.py
from __future__ import annotations
import importlib
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional

from .contracts import DatasetPlugin


class PluginRegistry:
    """
    插件注册表，自动发现 datasets/ 目录下的所有插件。

    使用方式：
        registry = PluginRegistry()
        registry.discover()
        plugins = registry.get_plugins()
        s1_plugin = registry.get_plugin("sentinel1")
    """

    def __init__(self):
        self._plugins: Dict[str, DatasetPlugin] = {}
        self._discovered = False

    def discover(self, package_path: Optional[Path] = None) -> None:
        """
        扫描 datasets/ 目录，发现并加载所有插件。

        Args:
            package_path: 可选，指定扫描路径，默认为 'satellite_downloader.datasets'
        """
        if self._discovered:
            return

        # 如果没有指定路径，使用默认的 datasets 包
        if package_path is None:
            try:
                import satellite_downloader.datasets as datasets_pkg
                package_path = datasets_pkg.__path__
                package_name = datasets_pkg.__name__
            except ImportError:
                # datasets 包还不存在，直接返回
                self._discovered = True
                return
        else:
            # 如果指定了路径，需要获取包名
            package_name = "satellite_downloader.datasets"

        # 遍历 datasets 下的所有子目录
        for module_info in pkgutil.iter_modules(package_path):
            if module_info.ispkg:
                module_name = module_info.name
                try:
                    # 动态导入：satellite_downloader.datasets.sentinel1.plugin
                    plugin_module = importlib.import_module(
                        f"{package_name}.{module_name}.plugin"
                    )
                    # 检查是否包含 PLUGIN 对象
                    if hasattr(plugin_module, "PLUGIN"):
                        plugin = plugin_module.PLUGIN
                        # 验证是否是 DatasetPlugin 类型（鸭子类型检查）
                        if all(hasattr(plugin, attr) for attr in
                               ["plugin_id", "display_name", "create_provider"]):
                            self._plugins[plugin.plugin_id] = plugin
                            print(f" 已加载插件：{plugin.display_name} ({plugin.plugin_id})")
                        else:
                            print(f" {module_name}/plugin.py 中的 PLUGIN 缺少必要属性")
                except ImportError as e:
                    # plugin.py 不存在或导入失败，静默跳过
                    pass
                except Exception as e:
                    print(f"❌ 加载插件 {module_name} 失败：{e}")

        self._discovered = True

    def get_plugins(self) -> List[DatasetPlugin]:
        """返回所有已发现的插件列表"""
        if not self._discovered:
            self.discover()
        return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> Optional[DatasetPlugin]:
        """根据 plugin_id 获取指定的插件，不存在时返回 None"""
        if not self._discovered:
            self.discover()
        return self._plugins.get(plugin_id)

    def clear(self) -> None:
        """清空注册表（主要用于测试）"""
        self._plugins.clear()
        self._discovered = False

    def is_discovered(self) -> bool:
        """返回是否已经执行过发现操作"""
        return self._discovered

    def get_plugin_ids(self) -> List[str]:
        """返回所有已发现插件的 ID 列表"""
        return list(self.get_plugins())