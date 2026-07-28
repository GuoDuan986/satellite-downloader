from datetime import date, datetime, timezone

import pytest
from shapely.geometry import box

from satellite_downloader.models import (
    ProductOrder,
    SatelliteProduct,
    SearchCriteria,
    order_products,
)


def test_search_criteria_rejects_reversed_dates() -> None:
    criteria = SearchCriteria(date(2026, 2, 1), date(2026, 1, 1), 20)

    with pytest.raises(ValueError, match="开始日期"):
        criteria.validate()


def test_product_archive_name_and_size() -> None:
    product = SatelliteProduct(
        provider="test",
        product_id="id",
        name="S2_TEST.SAFE",
        sensing_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        cloud_cover=10.5,
        tile_id="48R",
        size_bytes=1024**3,
        online=True,
        footprint=box(0, 0, 1, 1),
    )

    assert product.archive_name == "S2_TEST.zip"
    assert product.size_text == "1.0 GB"


def test_products_can_be_grouped_by_tile_with_each_group_newest_first() -> None:
    def product(product_id: str, tile_id: str, day: int) -> SatelliteProduct:
        return SatelliteProduct(
            provider="test",
            product_id=product_id,
            name=product_id,
            sensing_time=datetime(2026, 1, day, tzinfo=timezone.utc),
            cloud_cover=None,
            tile_id=tile_id,
            size_bytes=0,
            online=True,
            footprint=box(0, 0, 1, 1),
        )

    products = [
        product("tile-b-new", "48QXM", 4),
        product("tile-a-old", "48RWN", 1),
        product("tile-a-new", "48RWN", 3),
        product("tile-b-old", "48QXM", 2),
    ]

    ordered = order_products(
        products,
        ProductOrder.TILE_THEN_TIME_DESC,
        ("48RWN", "48QXM"),
    )

    assert [item.product_id for item in ordered] == [
        "tile-a-new",
        "tile-a-old",
        "tile-b-new",
        "tile-b-old",
    ]
