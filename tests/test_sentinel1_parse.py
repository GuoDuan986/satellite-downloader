import json
from pathlib import Path
from satellite_downloader.datasets.sentinel1.provider import Sentinel1Provider


def test_sentinel1_parse_orbit_direction():
    fixture_path = Path(__file__).parent / "fixtures" / "sentinel1" / "sample_response.json"
    with open(fixture_path) as f:
        data = json.load(f)

    provider = Sentinel1Provider()
    item = data["value"][0]

    product = provider._parse_item(item)
    assert product is not None
    assert product.metadata.get("orbit_direction") in ["ASCENDING", "DESCENDING"]