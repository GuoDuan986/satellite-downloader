# 开发交接指南

本文档面向收到项目副本后继续开发 Sentinel-1、Landsat 和多数据源界面的成员。当前项目
使用固定矩形 AOI，不依赖或提供外部矢量文件。

## 1. 发送前检查

发送方不能直接压缩当前工作目录：本机仍保留未跟踪的 `data/` 矢量文件，`.gitignore` 不会
阻止压缩软件将它们打进压缩包。请先复制一份干净的交接目录，再发送该目录。

在 PowerShell 中执行以下命令，并将路径替换为实际位置：

```powershell
$source = "D:\Aqita\datasets\satelliteImageDownload"
$target = "D:\handoff\satellite-image-downloader"

if (Test-Path -LiteralPath $target) { throw "交接目标目录必须是全新的空目录：$target" }
robocopy $source $target /E /XD data .git .venv venv downloads build dist .pytest_cache __pycache__ /XF *.pyc *.part
if ($LASTEXITCODE -ge 8) { throw "交接目录复制失败，robocopy exit code: $LASTEXITCODE" }
```

复制后检查交接目录中不存在 `data/`、`downloads/`、`.git/`、`.venv/` 或任何账号、密码、
token、签名 URL 和下载影像文件。应发送 `$target` 的压缩包，而不是原始项目目录。

## 2. 环境要求

- Windows 10/11；
- Python 3.10 或更新版本，推荐 Python 3.10；
- 可访问 PyPI 的网络；
- 下载 Sentinel-2 产品时需要 Copernicus Data Space Ecosystem 账号，检索不需要登录。

项目依赖由 `pyproject.toml` 管理，包括 PySide6、GeoPandas、Shapely、Requests 和测试用
Pytest。不要手工逐个安装依赖。

## 3. 创建环境并安装

推荐使用 Conda。在项目根目录打开 PowerShell：

```powershell
conda create -n satellite-downloader python=3.10 -y
conda activate satellite-downloader
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

如果 PowerShell 提示找不到 `conda activate`，先在 Anaconda Prompt 中执行
`conda init powershell`，关闭并重新打开 PowerShell；也可以直接在 Anaconda Prompt 中
完成上述操作。

也可以使用 Python 自带虚拟环境：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

若 PowerShell 阻止激活脚本，仅对当前终端执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

然后重新执行激活命令。不要把 `.venv/` 发给其他成员。

使用 VS Code 时，按 `Ctrl+Shift+P`，执行 `Python: Select Interpreter`，选择刚创建的
`satellite-downloader` Conda 环境或项目下的 `.venv`。终端提示符中的环境名和
`python --version` 应与所选环境一致。

## 4. 启动与验证

安装完成后，任选一种方式启动：

```powershell
python run.py
satellite-downloader
python -m satellite_downloader
```

程序标题应为“卫星影像下载器”。界面不显示地名、坐标或矢量文件选择控件。固定矩形 AOI
由 `src/satellite_downloader/config.py` 的 `DEFAULT_AOI_BOUNDS` 提供，开发期间不要擅自
替换为外部矢量文件。

运行自动化测试：

```powershell
python -m pytest
```

测试必须全部通过后再开始功能开发。测试只使用脱敏 fixture 或代码内构造的矩形，不能
依赖外部网络、真实账号或原始矢量数据。

## 5. 当前目录说明

```text
src/satellite_downloader/
├── app.py                 # 应用装配与固定矩形 AOI
├── config.py              # 应用名、固定矩形边界和路径
├── aoi.py                 # AOI 几何和搜索窗口
├── models.py              # 当前领域模型
├── workers.py             # Qt 搜索与下载后台任务
├── providers/             # 当前 Sentinel-2/CDSE Provider
└── ui/main_window.py      # 当前桌面界面
tests/                     # 不访问真实网络的自动化测试
docs/                      # 设计、扩展计划和本交接指南
```

后续目标结构、接口契约和验收标准见[多源扩展计划](multi-source-extension-plan.md)。在开始
改造前先阅读[系统设计](system-design.md)。

## 6. 两人开发边界

按扩展计划分工，避免同时修改同一文件：

| 人员 | 主要负责目录和模块 |
| --- | --- |
| 研一 A | `core/`、`shared/cdse.py`、`datasets/sentinel1/`、公共契约测试 |
| 研一 B | `datasets/landsat/`、`datasets/sentinel2/`、`ui/`、集成测试 |

当前仓库尚未创建上述目标目录时，应先由研一 A 交付最小公共契约，再由研一 B 基于 fixture
和 Fake Provider 并行实现。研一 B 不直接修改 `core/` 方法签名；需要变更时，先写清楚
新增字段、调用方和兼容方式，由研一 A 统一实现。

## 7. 不使用 Git 的交付规则

两人仍应在各自独立的项目副本中开发，不要共享同一个目录或互相覆盖整包文件。每次交付
只发送以下内容：

- 自己负责范围内的新增或修改源码；
- 对应测试、fixture 和文档；
- 一份简短变更说明：修改目的、涉及文件、运行过的测试和已知限制。

集成人员先备份主副本，再逐文件合并变更并运行 `python -m pytest`。不得发送或覆盖
`data/`、`downloads/`、`.venv/`、账号信息和真实目录响应。

## 8. 凭据与数据要求

- Copernicus 密码和 token 不得写入代码、测试、文档、截图或交接包；
- 自动化测试不访问真实网络；
- 真实检索和下载仅作为人工 smoke test，记录日期、产品 ID 和结果，不记录凭据；
- 固定矩形边界属于当前程序配置，原始高精度矢量文件不属于交接内容。
