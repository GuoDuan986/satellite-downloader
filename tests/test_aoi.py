import pytest
from shapely.geometry import box

from satellite_downloader.aoi import AreaOfInterest
from satellite_downloader.config import DEFAULT_AOI_BOUNDS


TEST_BOUNDS = (100.0, 20.0, 102.0, 21.0)


def test_default_aoi_uses_configured_rectangle() -> None:
    aoi = AreaOfInterest.from_bounds(DEFAULT_AOI_BOUNDS)

    assert aoi.geometry.bounds == pytest.approx(
        (104.74993, 23.891659, 106.670617, 25.28654)
    )


def test_aoi_from_bounds_creates_valid_rectangle() -> None:
    aoi = AreaOfInterest.from_bounds(TEST_BOUNDS)

    assert not aoi.geometry.is_empty
    assert aoi.geometry.is_valid
    assert aoi.geometry.bounds == pytest.approx(TEST_BOUNDS)


def test_search_boxes_cover_the_aoi() -> None:
    aoi = AreaOfInterest.from_bounds(TEST_BOUNDS)
    windows = aoi.search_boxes()
    covered = aoi.geometry.intersection(box(*windows[0]))
    for window in windows[1:]:
        covered = covered.union(aoi.geometry.intersection(box(*window)))

    assert len(windows) == 3
    assert covered.symmetric_difference(aoi.geometry).area < 1e-12
