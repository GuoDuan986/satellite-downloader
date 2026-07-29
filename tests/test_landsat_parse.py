import json
from pathlib import Path
from unittest.mock import patch
from satellite_downloader.datasets.landsat.provider import LandsatProvider


def test_landsat_parse_sample():
    # 1. 加载脱敏的 Mock 数据
    fixture_path = Path(__file__).parent / "fixtures" / "landsat" / "sample_response.json"
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    provider = LandsatProvider()
    feature = data["features"][0]

    # 2. ✅ 使用 mock 拦截 pc.sign，防止其在测试期间发起任何网络请求
    with patch("satellite_downloader.datasets.landsat.provider.pc.sign", side_effect=lambda x: x):
        product = provider._parse_item(feature, ("red", "green", "blue", "qa_pixel"))

    # 3. 基础断言
    assert product is not None
    assert product.provider_id == "landsat"
    assert product.metadata.get("platform") == "landsat-9"
    assert product.metadata.get("wrs_path") == 80
    assert product.metadata.get("wrs_row") == 244
    assert product.cloud_cover == 100.0
    assert len(product.assets) == 4

    # 4. 验证资产键与结构的完整性
    asset_dict = {a.key: a for a in product.assets}
    for key in ("red", "green", "blue", "qa_pixel"):
        assert key in asset_dict
        asset = asset_dict[key]
        assert asset.url is not None and len(asset.url) > 0
        # 校验文件大小解析（若 json 中包含 size 字段）
        if asset.size_bytes is not None:
            assert isinstance(asset.size_bytes, int)