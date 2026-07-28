# 多源卫星影像扩展：架构改造与两人并行开发方案

## 1. 文档目的

本文档定义在现有 Sentinel-2 L2A 下载器基础上，扩展 Sentinel-1 IW GRD 和
Landsat 8/9 Collection 2 Level-2 的目标架构、公共接口、人员分工和验收标准。

参与人员为两名研一。两人从第一周同时开始开发，不采用“一个人先完成公共框架，
其他人再开始”的串行方式。为降低并行开发冲突，本方案按技术链路、文件所有权和
稳定接口拆分任务：

- 研一 A：Sentinel-1、CDSE 公共客户端和核心架构；
- 研一 B：Landsat Provider、多数据源 UI、Sentinel-2 插件迁移和集成测试。

现有 Sentinel-2 已经实现，不作为一个新的卫星任务。它用于验证插件架构、提供参考
实现并承担回归测试。

## 2. 首版范围

| 数据集            | 数据目录    | 空间检索               | 下载方式       | 首版范围                     |
| ----------------- | ----------- | ---------------------- | -------------- | ---------------------------- |
| Sentinel-2 L2A    | CDSE OData  | MGRS tile + 足迹校验   | 整包 ZIP       | 迁移现有功能，不改变业务行为 |
| Sentinel-1 IW GRD | CDSE OData  | AOI 足迹相交           | 整包 ZIP       | GRD、IW、极化和升降轨筛选    |
| Landsat 8/9 C2 L2 | 待选定 STAC | AOI / WRS-2 + 足迹校验 | 分资产 GeoTIFF | RGB + QA_PIXEL 顺序下载      |

首版不包含：

- Sentinel-1 SLC、配准、干涉和 SAR 预处理；
- 下载后自动解压、裁剪、拼接、重投影或云掩膜；
- Landsat 任意波段组合和资产并发下载；
- 多 frame、多瓦片完整覆盖自动判定；
- 下载任务数据库、定时检索和代理配置界面；
- Windows 安装包。

## 3. 设计目标

完成改造后，每个卫星或数据集应成为相对独立的插件。新增数据集时，主要修改应限制
在自己的 `datasets/<dataset>/` 目录，不应在主窗口或 worker 中增加卫星名称判断。

目标目录结构：

```text
src/satellite_downloader/
├── core/
│   ├── contracts.py          # 插件、检索、认证和下载公共接口
│   ├── models.py             # SatelliteProduct、ProductAsset
│   ├── registry.py           # 内置插件发现和注册
│   └── workers.py            # 通用搜索和资产级下载任务
├── datasets/
│   ├── sentinel2/
│   │   ├── plugin.py
│   │   ├── provider.py
│   │   └── options.py
│   ├── sentinel1/
│   │   ├── plugin.py
│   │   ├── provider.py
│   │   └── options.py
│   └── landsat/
│       ├── plugin.py
│       ├── provider.py
│       └── options.py
├── shared/
│   └── cdse.py               # S1/S2 共用认证、HTTP 和整包下载
├── ui/
│   └── main_window.py        # 按插件声明渲染控件和结果列
└── app.py
```

迁移期间允许旧模块保留兼容导入，待三个数据集完成联调后再统一清理。迁移不能破坏当前
Sentinel-2 功能。

## 4. 公共接口契约

公共接口由研一 A 负责实现和维护。第一天两人共同评审接口字段，评审后原则上只允许
向后兼容地增加字段，不能由各分支自行修改方法签名。研一 B 通过接口变更说明提出
需求，由研一 A 修改 `core/` 文件。

### 4.1 检索请求

公共条件与数据集专属条件分离，不再把极化、轨道方向、WRS path/row 等字段不断加入
公共 `SearchCriteria`，也不依赖不存在的 `criteria.metadata`。

```python
@dataclass(frozen=True)
class SearchRequest:
    start_date: date
    end_date: date
    max_results: int
    options: Mapping[str, object] = field(default_factory=dict)
```

`options` 的键必须来自对应插件的 `search_fields`。Provider 负责验证并转换为自己的
强类型 options，例如 `Sentinel1SearchOptions` 或 `LandsatSearchOptions`。

### 4.2 产品与资产模型

整包产品和分波段产品统一表示为包含资产的产品：

```python
@dataclass(frozen=True)
class ProductAsset:
    key: str
    title: str
    url: str
    size_bytes: int | None = None
    checksum: str | None = None
    roles: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SatelliteProduct:
    provider_id: str
    product_id: str
    name: str
    sensing_time: datetime
    footprint: BaseGeometry
    cloud_cover: float | None = None
    size_bytes: int | None = None
    online: bool = True
    assets: tuple[ProductAsset, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
```

Sentinel-1/2 的整包 ZIP 作为一个资产；Landsat 的红、绿、蓝和 QA 文件分别作为资产。
外部 STAC 资产键必须由 Landsat Provider 映射为项目内部统一键，UI 不直接解释 STAC。

### 4.3 认证模型

认证不能继续假设所有数据源都需要用户名和密码：

```python
class AuthMode(Enum):
    NONE = "none"
    USERNAME_PASSWORD = "username_password"
    TOKEN = "token"


@dataclass(frozen=True)
class Credentials:
    username: str = ""
    password: str = ""
    token: str = ""
```

插件通过 `AuthSpec` 声明认证方式。`AuthMode.NONE` 时 UI 隐藏认证区域，worker 不得强制
检查账号密码。密码和令牌不得写入日志、fixture 或版本库。

### 4.4 下载模型

下载接口不能再假设“一景产品只返回一个 Path”：

```python
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
```

首版 Landsat 资产顺序下载。单资产失败应保留其他已完成文件并报告明确错误；取消后保留
可续传的 `.part` 文件。

### 4.5 插件声明

```python
class DatasetPlugin(Protocol):
    plugin_id: str
    display_name: str
    auth_spec: AuthSpec
    search_fields: tuple[FieldSpec, ...]
    result_columns: tuple[ColumnSpec, ...]
    download_spec: DownloadSpec

    def create_provider(self) -> SatelliteProvider:
        ...
```

`FieldSpec` 至少支持数字、枚举和布尔类型，并包含默认值、可选项和校验约束。
`ColumnSpec` 从 `SatelliteProduct` 公共字段或 `metadata` 读取显示值。主窗口只渲染声明，
不得出现 `if plugin_id == "sentinel1"` 一类分支。

内置插件由 `core/registry.py` 从 `datasets/*/plugin.py` 发现。每个插件导出一个约定名称
的 `PLUGIN` 对象，新增插件不要求修改主窗口和 worker。

## 5. 任务 A：Sentinel-1 与 CDSE 公共客户端（研一 A）

### 5.1 工作范围

1. 在 `shared/cdse.py` 提取 S1/S2 共用能力：
   - OAuth2 认证和令牌刷新；
   - HTTP Session、重试、超时和重定向；
   - Range 断点续传；
   - `.part` 文件、校验和原子改名。
2. 实现 Sentinel-1 IW GRD Provider：
   - `Collection/Name eq 'SENTINEL-1'`；
   - 使用 AOI 搜索窗口和 `OData.CSC.Intersects`；
   - 产品类型固定为首版 GRD；
   - 支持极化和升降轨筛选；
   - 本地足迹精确相交和产品去重。
3. 解析平台、模式、极化、轨道方向、相对轨道号等元数据。
4. 提供脱敏的真实目录响应 fixture 和离线测试。

平台字段不得只写死 Sentinel-1A/1B，应兼容目录返回的其他 Sentinel-1 平台标识。

### 5.2 文件所有权

```text
src/satellite_downloader/shared/cdse.py
src/satellite_downloader/datasets/sentinel1/
tests/fixtures/sentinel1/
tests/test_sentinel1.py
```

研一 A 同时拥有 `core/` 文件：公共接口变化、registry、通用 worker 和兼容性由研一 A
统一提交。研一 A 不直接修改 `ui/`、Landsat 和 Sentinel-2 插件文件；跨所有权需求通过
接口变更说明处理。

### 5.3 验收标准

- [ ] 能检索固定矩形 AOI 范围内 Sentinel-1 IW GRD 产品；
- [ ] 极化和升降轨筛选生成正确的目录请求；
- [ ] 响应解析为统一 `SatelliteProduct` 和整包 `ProductAsset`；
- [ ] 能完成认证、下载、取消、续传和校验；
- [ ] 分页结果能够去重并执行本地足迹相交；
- [ ] 查询和解析测试不访问真实网络；
- [ ] 至少完成一次人工触发的真实检索和小范围下载验证。

## 6. 任务 B：多源 UI、Sentinel-2 迁移与集成（研一 B）

### 6.1 工作范围

1. 将现有 Sentinel-2 实现迁移为 `datasets/sentinel2` 插件：
   - 使用程序配置的固定矩形 AOI；
   - 保留云量、日期和最大结果数；
   - 保留原有 CDSE 下载可靠性行为；
   - 对旧导入路径提供临时兼容层。
2. 改造主窗口：
   - 使用 registry 填充数据集选择器；
   - 根据 `FieldSpec` 生成搜索控件；
   - 根据 `ColumnSpec` 生成结果表列；
   - 根据 `AuthSpec` 显示、隐藏或更新认证区域；
   - 切换数据集时清空结果和选择状态；
   - 展示产品级和资产级下载进度。
3. 使用 Fake Provider 独立完成 UI 开发，不等待真实 S1/Landsat Provider。
4. 接入 Sentinel-1，并对三个插件执行集成回归。

### 6.2 文件所有权

```text
src/satellite_downloader/ui/
src/satellite_downloader/app.py
src/satellite_downloader/datasets/sentinel2/
tests/fakes/
tests/test_ui_*.py
tests/test_integration_*.py
```

研一 B 不修改 `core/` 的方法签名和公共实现；Landsat Provider 由研一 B 自己负责。
Sentinel-2 切换到公共 CDSE 客户端的适配也由研一 B 在自己的插件内完成，研一 A 不直接
修改 UI、Landsat 或 Sentinel-2 文件。

### 6.3 验收标准

- [ ] 数据集选择器能列出所有已发现插件；
- [ ] 搜索控件和结果列完全来自插件声明；
- [ ] UI 中没有按卫星名称编写的条件分支；
- [ ] 匿名数据源不会要求输入用户名和密码；
- [ ] 切换数据集后不会保留上一个数据集的结果或下载选择；
- [ ] 支持一个产品对应一个或多个下载文件；
- [ ] Fake S1、S2、Landsat 插件均可独立驱动 UI；
- [ ] 当前 Sentinel-2 搜索、认证、下载和续传行为回归通过。

## 7. 公共架构（研一 A）与 Landsat 实施（研一 B）

### 7.1 公共架构

研一 A 在完成 Sentinel-1/CDSE 主线的同时，负责第 4 节公共接口的实现、文档和兼容性：

- `DatasetPlugin`、`SatelliteProvider` 和 registry；
- `SearchRequest`、`SatelliteProduct`、`ProductAsset`；
- `AuthSpec`、可选凭据和认证调度；
- `DownloadPlan`、`DownloadResult`、资产级进度；
- 通用搜索和下载 worker；
- 接口契约测试和跨任务接口变更裁决。

公共接口需要优先保持简单稳定，不为尚未进入范围的裁剪、拼接和并发下载提前设计复杂
抽象。

### 7.2 核心架构与 Landsat 的边界

核心架构只负责稳定的公共模型、插件发现、认证调度和资产级下载协议；Landsat 的数据源
选型、STAC 响应解析和外部资产键映射由研一 B 负责。研一 B 使用已评审的 contracts 和
STAC fixture 并行开发，不直接修改 `core/` 方法签名。

### 7.3 Landsat 数据源选型（研一 B）

实现前完成并记录以下验证：

- 国内网络环境下的目录和资产 URL 可达性；
- 是否需要 Earthdata、API key 或 URL 签名；
- Landsat 8/9 Collection 2 Level-2 的覆盖完整性；
- collection ID、分页方式和速率限制；
- 红、绿、蓝、QA_PIXEL 的实际资产键；
- 文件大小和校验值是否稳定提供；
- URL 过期后如何重新获取或签名。

优先评估标准 STAC 目录。WRS-2 path/row 可作为固定研究区优化，但不能代替本地足迹
相交验证；若所选 STAC 的 AOI `intersects` 查询性能和准确性满足要求，首版不强制打包
完整 WRS-2 shapefile。

### 7.4 Landsat Provider（研一 B）

1. 检索 Landsat 8/9 Collection 2 Level-2；
2. 映射时间、平台、云量、path/row、足迹等公共元数据；
3. 将外部资产键映射为内部 `red`、`green`、`blue`、`qa_pixel`；
4. 首版固定下载 RGB + QA_PIXEL；
5. 每个资产独立使用 `.part` 文件，支持取消和错误隔离；
6. 匿名目录使用 `AuthMode.NONE`，需要签名或令牌时通过公共认证模型处理；
7. 使用脱敏 STAC fixture 完成离线测试。

### 7.5 文件所有权

```text
src/satellite_downloader/core/                     # 研一 A
src/satellite_downloader/datasets/landsat/         # 研一 B
tests/fixtures/landsat/                            # 研一 B
tests/test_contracts.py
tests/test_landsat.py                             # 研一 B
docs/provider-contract.md                         # 研一 A
docs/landsat-source-decision.md                   # 研一 B
```

### 7.6 验收标准

- [ ] 公共接口有明确类型、文档和契约测试；
- [ ] registry 能发现三个内置插件；
- [ ] worker 同时支持可选认证、整包产品和多资产产品；
- [ ] Landsat 数据源选型有可复现的网络验证记录；
- [ ] 能检索固定矩形 AOI 范围内 Landsat 8/9 L2 产品；
- [ ] 能顺序下载 RGB + QA_PIXEL 到产品独立目录；
- [ ] 单资产失败不会删除其他已完成资产；
- [ ] 取消后保留可继续使用的 `.part` 文件；
- [ ] 查询、解析和下载协议有离线测试；
- [ ] 至少完成一次人工触发的真实检索和资产下载验证。

## 8. 并行执行安排

两人从第一周同时开始。下表表示每周重点，不表示必须等待对方完成后才能工作。

| 阶段 | 研一 A：S1/CDSE/core                                      | 研一 B：Landsat/UI/S2                                                    |
| ---- | --------------------------------------------------------- | ------------------------------------------------------------------------ |
| 1    | 共同冻结最小契约；S1 OData 调研、fixture、查询与解析测试  | 共同冻结最小契约；Landsat STAC 选型、可达性验证和 fixture；Fake Provider |
| 2    | core/models、registry、workers；CDSE 公共客户端和 S1 搜索 | S2 插件迁移、动态条件和认证 UI；Landsat 搜索解析与资产键映射             |
| 3    | S1 下载、续传、校验和契约测试                             | Landsat RGB + QA_PIXEL 顺序下载、错误隔离和资产进度                      |
| 4    | S1 真实检索下载验证、修复、接口文档                       | 接入三插件、UI 回归、Landsat 实测和用户流程验证                          |
|  5  | 跨模块联调和最终修复                                      | 跨模块联调、smoke test 记录和最终文档收口                                |

为避免公共接口尚未实现造成等待：

- 研一 A 实现正式 contracts，同时使用 S1 fixture 开发查询和解析；
- 研一 B 使用 Fake Provider 和 STAC fixture 开发 UI、Landsat 解析和状态流；
- 正式 contracts 合入后，B 只替换 import 和适配已评审字段，不直接改 `core/`。

## 9. 分支与文件所有权

建议分支：

```text
feature/sentinel1-cdse        # 研一 A
feature/landsat-multisource  # 研一 B
```

协作规则：

1. 不以整条大分支规定 A → B 的合并顺序，采用可独立评审的小 PR；
2. 每个文件只有一名所有者，其他人不直接在自己的分支修改；
3. `core/` 的接口变化由研一 A 统一提交；
4. `ui/`、Sentinel-2 和 Landsat 插件变化由研一 B 提交；
5. `shared/cdse.py` 和 Sentinel-1 插件变化由研一 A 提交；
6. 需要跨所有权修改时，先提交接口变更说明，再由文件所有者实现；
7. 公共接口 PR 合入后，研一 B 当天同步，尽早暴露兼容问题；
8. 禁止提交真实用户名、密码、token、签名 URL 和未脱敏响应。

## 10. 测试与验收方式

### 10.1 自动化测试

- 查询构造：验证请求参数，不只检查拼接后的字符串片段；
- 响应解析：使用脱敏离线 JSON/STAC fixture；
- HTTP 行为：模拟分页、401、429、5xx、重定向和 Range 响应；
- 下载行为：覆盖续传、服务器忽略 Range、校验失败、取消和原子改名；
- 契约测试：三个 Provider 使用同一套公共行为测试；
- UI 测试：使用 Fake Provider，不访问真实网络；
- 回归测试：现有 Sentinel-2 测试必须继续通过。

自动化测试不得依赖真实账号和外部网络。真实目录和下载测试作为人工 smoke test 单独执行，
记录日期、数据集、产品 ID 和结果，不记录敏感凭据。

### 10.2 完成定义

每个任务只有同时满足以下条件才算完成：

- 代码位于约定目录且未越过文件所有权；
- 单元测试和契约测试通过；
- 至少一名其他成员完成 Code Review；
- 用户可见错误有明确中文提示；
- 真实 smoke test 有记录；
- 文档说明已知限制和未完成范围。

## 11. 主要风险与处理

| 风险                              | 处理方式                                                                  |
| --------------------------------- | ------------------------------------------------------------------------- |
| 公共接口成为单人瓶颈              | 第一天冻结最小契约；A 使用 S1 fixture、B 使用 Fake/STAC Provider 并行开发 |
| 两人同时修改公共文件              | `core/` 由 A 单一所有；跨目录需求由文件所有者提交                       |
| 两人承担三人工作导致延期          | 首版固定 RGB + QA、顺序下载和最小动态 UI；按五周执行，复杂覆盖判断后置    |
| Landsat STAC 国内不可达或需要签名 | Week 1 完成选型门槛，保留第二候选数据目录                                 |
| STAC 资产键和大小不统一           | Provider 内部做键映射，大小字段允许为空                                   |
| S1/S2 复制两套 CDSE 下载代码      | 统一复用`shared/cdse.py`                                                |
| 动态 UI 过度设计                  | 首版 FieldSpec 只支持数字、枚举和布尔控件                                 |
| 多资产下载扩大工作量              | 首版固定 RGB + QA、顺序下载，不做并发和任意选择                           |
| 重构破坏 Sentinel-2               | 保留兼容导入和现有测试，迁移前后执行同一组回归用例                        |

## 12. 最终交付

项目最终应交付：

1. 可切换 Sentinel-2、Sentinel-1 和 Landsat 的桌面应用；
2. 三个独立数据集插件；
3. S1/S2 共用 CDSE 客户端；
4. 支持可选认证和多资产产品的公共 worker；
5. Sentinel-1 整包下载和 Landsat RGB + QA 下载；
6. 离线 fixture、单元测试、契约测试和 Sentinel-2 回归测试；
7. Provider 接口文档和 Landsat 数据源选型记录；
8. 三个数据集各至少一次真实检索与下载 smoke test 记录。
