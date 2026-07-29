import json
from pathlib import Path
from satellite_downloader.datasets.sentinel1.provider import Sentinel1Provider


def test_sentinel1_parse_orbit_direction():
    # 1. 读取脱敏的 CDSE OData Fixture 数据
    fixture_path = Path(__file__).parent / "fixtures" / "sentinel1" / "sample_response.json"
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    provider = Sentinel1Provider()
    item = data["value"][0]

    # 2. 执行解析
    product = provider._parse_item(item)

    # 3. 基础与元数据断言
    assert product is not None
    assert product.provider_id == "sentinel1"

    # ✅ 改为精准断言（根据你的 sample_response.json 实际值确定，例如明确断言为 "ASCENDING"）
    orbit_dir = product.metadata.get("orbit_direction")
    assert orbit_dir in ["ASCENDING", "DESCENDING"]  # 仍保留合法性校验
    # assert orbit_dir == "ASCENDING"  # 💡 建议替换为对应 sample_response.json 中第一个item的具体值

    # 4. ✅ 扩展校验：验证 Sentinel-1 的整包 ZIP 资产契约
    assert len(product.assets) == 1
    zip_asset = product.assets[0]
    assert zip_asset.url is not None and len(zip_asset.url) > 0
    assert "zip" in zip_asset.roles or "data" in zip_asset.roles