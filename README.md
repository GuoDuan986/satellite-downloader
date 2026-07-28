# 卫星影像下载器

系统功能、架构和 Sentinel-1/Landsat 扩展方案见
[`docs/system-design.md`](docs/system-design.md)。

交给后续开发成员前，请先阅读[开发交接指南](docs/developer-handoff.md)。

用于检索和下载与固定矩形范围相交的 Sentinel-2 L2A 产品。检索范围在程序配置中定义，
界面不展示位置或提供区域编辑功能，运行时也不依赖外部矢量文件。

## 当前功能

- 按日期和最大云量检索 Sentinel-2 L2A。
- 检索结果可选择全部按时间倒序，或按瓦片聚合并在各组内按时间倒序。
- 使用固定矩形生成空间检索窗口，再按矩形几何精确过滤和去重。
- 显示成像时间、MGRS 瓦片号、云量、产品大小及在线状态。
- 使用 Copernicus Data Space 账号批量下载完整 `.SAFE` 产品压缩包。
- 支持 `.part` 断点续传、失败后继续队列及下载完成 MD5 校验。
- 用户名和下载目录保存到系统设置；密码不写入设置或磁盘，仅保留在应用进程内存中。

## 运行

使用指定的 Conda 环境：

```powershell
D:\Acode\anaconda\envs\anshuIndex\python.exe run.py
```

检索无需登录。下载需要免费的 Copernicus Data Space Ecosystem 账号：
<https://dataspace.copernicus.eu/>。

也可以把项目安装为可编辑包：

```powershell
D:\Acode\anaconda\envs\anshuIndex\python.exe -m pip install -e .
satellite-downloader
```

## 测试

```powershell
D:\Acode\anaconda\envs\anshuIndex\python.exe -m pytest
```

## 扩展数据源

新数据源实现 `src/satellite_downloader/providers/base.py` 中的
`SatelliteProvider` 接口，并将返回值转换为统一的 `SatelliteProduct`。界面和后台
任务不依赖 CDSE 的具体字段，因此可以继续接入 Sentinel-1、Landsat 或其他 STAC
目录。
