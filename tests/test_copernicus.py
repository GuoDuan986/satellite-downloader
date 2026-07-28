from datetime import date

from satellite_downloader.models import SearchCriteria
from satellite_downloader.providers.copernicus import CopernicusSentinel2Provider


def test_search_filter_targets_sentinel_2_l2a_tile() -> None:
    criteria = SearchCriteria(date(2026, 1, 1), date(2026, 1, 31), 12.5)

    params = CopernicusSentinel2Provider._search_params(
        criteria, tile_id="48RWN"
    )

    query = params["$filter"]
    assert "Collection/Name eq 'SENTINEL-2'" in query
    assert "contains(Name,'MSIL2A')" in query
    assert "cloudCover" in query
    assert "Value le 12.50" in query
    assert "Name eq 'tileId'" in query
    assert "Value eq '48RWN'" in query
    assert "OData.CSC.Intersects" not in query


def test_target_tiles_create_four_exact_queries() -> None:
    criteria = SearchCriteria(date(2026, 1, 1), date(2026, 1, 31), 20)
    provider = CopernicusSentinel2Provider(
        tile_ids=("48RWN", "48QXM", "48RXN", "48RVN")
    )

    queries = provider._search_queries(criteria, [])

    assert len(queries) == 4
    assert all("Name eq 'tileId'" in query["$filter"] for query in queries)


def test_parse_catalogue_product() -> None:
    item = {
        "Id": "abc",
        "Name": "S2C_MSIL2A_20260722T034541_TEST.SAFE",
        "ContentLength": 2048,
        "Online": True,
        "ContentDate": {"Start": "2026-07-22T03:45:41.025000Z"},
        "GeoFootprint": {
            "type": "Polygon",
            "coordinates": [[[102, 23], [103, 23], [103, 24], [102, 23]]],
        },
        "Checksum": [{"Algorithm": "MD5", "Value": "deadbeef"}],
        "Attributes": [
            {"Name": "cloudCover", "Value": 8.25},
            {"Name": "tileId", "Value": "48RVM"},
        ],
    }

    product = CopernicusSentinel2Provider._parse_product(item)

    assert product is not None
    assert product.product_id == "abc"
    assert product.cloud_cover == 8.25
    assert product.tile_id == "48RVM"
    assert product.checksum_md5 == "deadbeef"
