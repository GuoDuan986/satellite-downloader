from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import math
import os
import time
from collections.abc import Iterable, Sequence
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from urllib3.util.retry import Retry

from ..exceptions import (
    AuthenticationError,
    CatalogueError,
    DownloadCancelled,
    DownloadError,
)
from ..models import ProductOrder, SatelliteProduct, SearchCriteria, order_products
from .base import CancelCheck, DownloadProgress, SatelliteProvider, SearchProgress


class CopernicusSentinel2Provider(SatelliteProvider):
    display_name = "Sentinel-2 L2A"
    catalogue_url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
    token_url = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
        "protocol/openid-connect/token"
    )
    download_url = "https://download.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"

    def __init__(
        self,
        timeout: tuple[int, int] = (15, 90),
        tile_ids: Sequence[str] | None = None,
    ) -> None:
        self.timeout = timeout
        self.tile_ids = tuple(tile_ids or ())
        self.session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET", "POST")),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": "satellite-image-downloader/0.1"})
        self._username = ""
        self._password = ""
        self._access_token = ""
        self._token_expiry = 0.0

    def arrange_products(
        self,
        products: Iterable[SatelliteProduct],
        order: ProductOrder,
    ) -> list[SatelliteProduct]:
        return order_products(products, order, self.tile_ids)

    def search(
        self,
        criteria: SearchCriteria,
        aoi: BaseGeometry,
        search_boxes: list[tuple[float, float, float, float]],
        progress: SearchProgress,
        cancelled: CancelCheck,
    ) -> list[SatelliteProduct]:
        criteria.validate()
        products: dict[str, SatelliteProduct] = {}
        queries = self._search_queries(criteria, search_boxes)
        total_queries = len(queries)
        per_query_limit = max(10, math.ceil(criteria.max_results / max(total_queries, 1)))

        for index, params in enumerate(queries, start=1):
            if cancelled():
                break
            progress(index - 1, total_queries)
            next_url: str | None = self.catalogue_url
            query_params: dict[str, str] | None = params
            query_product_ids: set[str] = set()

            while next_url and len(query_product_ids) < per_query_limit:
                if cancelled():
                    break
                try:
                    response = self.session.get(
                        next_url, params=query_params, timeout=self.timeout
                    )
                    response.raise_for_status()
                    payload = response.json()
                except (requests.RequestException, ValueError) as exc:
                    raise CatalogueError(f"Copernicus 检索失败：{exc}") from exc

                for item in payload.get("value", []):
                    product = self._parse_product(item)
                    if product is not None and product.footprint.intersects(aoi):
                        products[product.product_id] = product
                        query_product_ids.add(product.product_id)
                        if len(query_product_ids) >= per_query_limit:
                            break
                next_url = payload.get("@odata.nextLink")
                query_params = None
            progress(index, total_queries)

        ordered = self.arrange_products(products.values(), criteria.product_order)
        return ordered[: criteria.max_results]

    def _search_queries(
        self,
        criteria: SearchCriteria,
        search_boxes: list[tuple[float, float, float, float]],
    ) -> list[dict[str, str]]:
        if self.tile_ids:
            return [self._search_params(criteria, tile_id=tile_id) for tile_id in self.tile_ids]
        return [self._search_params(criteria, bounds=bounds) for bounds in search_boxes]

    @staticmethod
    def _search_params(
        criteria: SearchCriteria,
        bounds: tuple[float, float, float, float] | None = None,
        tile_id: str | None = None,
    ) -> dict[str, str]:
        start = criteria.start_date.isoformat()
        end = criteria.end_date.isoformat()
        cloud = criteria.max_cloud_cover
        filters = [
            "Collection/Name eq 'SENTINEL-2'",
            "contains(Name,'MSIL2A')",
            f"ContentDate/Start ge {start}T00:00:00.000Z",
            f"ContentDate/Start le {end}T23:59:59.999Z",
            (
                "Attributes/OData.CSC.DoubleAttribute/any(att:"
                "att/Name eq 'cloudCover' and "
                f"att/OData.CSC.DoubleAttribute/Value le {cloud:.2f})"
            ),
        ]
        if tile_id:
            filters.append(
                "Attributes/OData.CSC.StringAttribute/any(att:"
                "att/Name eq 'tileId' and "
                f"att/OData.CSC.StringAttribute/Value eq '{tile_id}')"
            )
        elif bounds:
            min_x, min_y, max_x, max_y = bounds
            polygon = (
                f"POLYGON(({min_x:.6f} {min_y:.6f},{max_x:.6f} {min_y:.6f},"
                f"{max_x:.6f} {max_y:.6f},{min_x:.6f} {max_y:.6f},"
                f"{min_x:.6f} {min_y:.6f}))"
            )
            filters.append(f"OData.CSC.Intersects(area=geography'SRID=4326;{polygon}')")
        else:
            raise ValueError("tile_id 和 bounds 至少需要提供一项")
        return {
            "$filter": " and ".join(filters),
            "$expand": "Attributes",
            "$orderby": "ContentDate/Start desc",
            "$top": "100",
        }

    @staticmethod
    def _parse_product(item: dict[str, Any]) -> SatelliteProduct | None:
        geo_footprint = item.get("GeoFootprint")
        content_date = item.get("ContentDate") or {}
        if not geo_footprint or not content_date.get("Start"):
            return None

        attributes = {
            attribute.get("Name"): attribute.get("Value")
            for attribute in item.get("Attributes", [])
        }
        checksums = {
            checksum.get("Algorithm", "").upper(): checksum.get("Value")
            for checksum in item.get("Checksum", [])
        }
        sensing_time = datetime.fromisoformat(content_date["Start"].replace("Z", "+00:00"))
        return SatelliteProduct(
            provider="copernicus-sentinel-2",
            product_id=item["Id"],
            name=item["Name"],
            sensing_time=sensing_time,
            cloud_cover=_as_float(attributes.get("cloudCover")),
            tile_id=_as_text(attributes.get("tileId")),
            size_bytes=int(item.get("ContentLength") or 0),
            online=bool(item.get("Online", True)),
            footprint=shape(geo_footprint),
            checksum_md5=checksums.get("MD5"),
            metadata={"s3_path": item.get("S3Path"), "attributes": attributes},
        )

    def authenticate(self, username: str, password: str) -> None:
        username = username.strip()
        if not username or not password:
            raise AuthenticationError("请输入 Copernicus Data Space 账号和密码")
        self._username = username
        self._password = password
        self._request_token()

    def _request_token(self) -> None:
        try:
            response = self.session.post(
                self.token_url,
                data={
                    "client_id": "cdse-public",
                    "username": self._username,
                    "password": self._password,
                    "grant_type": "password",
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AuthenticationError(f"登录服务连接失败：{exc}") from exc
        if response.status_code != 200:
            message = "账号或密码错误"
            try:
                detail = response.json().get("error_description")
                if detail:
                    message = detail
            except ValueError:
                pass
            raise AuthenticationError(f"Copernicus 登录失败：{message}")

        payload = response.json()
        self._access_token = payload["access_token"]
        self._token_expiry = time.time() + int(payload.get("expires_in", 600)) - 30

    def _valid_token(self) -> str:
        if not self._access_token or time.time() >= self._token_expiry:
            if not self._username or not self._password:
                raise AuthenticationError("请先登录 Copernicus Data Space")
            self._request_token()
        return self._access_token

    def download(
        self,
        product: SatelliteProduct,
        destination: Path,
        progress: DownloadProgress,
        cancelled: CancelCheck,
    ) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        final_path = destination / product.archive_name
        part_path = final_path.with_suffix(final_path.suffix + ".part")

        if final_path.is_file() and final_path.stat().st_size == product.size_bytes:
            progress(product.size_bytes, product.size_bytes)
            return final_path
        if part_path.is_file() and part_path.stat().st_size == product.size_bytes:
            if not product.checksum_md5 or _matches_md5(part_path, product.checksum_md5):
                os.replace(part_path, final_path)
                progress(product.size_bytes, product.size_bytes)
                return final_path

        response = self._open_download(product, part_path)
        existing = part_path.stat().st_size if part_path.exists() else 0
        if response.status_code == 200 and existing:
            existing = 0
        mode = "ab" if response.status_code == 206 and existing else "wb"
        total = product.size_bytes or _response_total(response, existing)
        downloaded = existing
        progress(downloaded, total)

        try:
            with part_path.open(mode) as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if cancelled():
                        raise DownloadCancelled("下载已取消，可稍后从断点继续")
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    progress(downloaded, total)
        except OSError as exc:
            raise DownloadError(f"写入文件失败：{exc}") from exc
        finally:
            response.close()

        if total and downloaded != total:
            raise DownloadError(f"下载不完整：应为 {total} 字节，实际为 {downloaded} 字节")
        if product.checksum_md5 and not _matches_md5(part_path, product.checksum_md5):
            raise DownloadError("MD5 校验失败，保留 .part 文件以便重新下载")

        os.replace(part_path, final_path)
        return final_path

    def _open_download(self, product: SatelliteProduct, part_path: Path) -> requests.Response:
        url = self.download_url.format(product_id=product.product_id)
        existing = part_path.stat().st_size if part_path.exists() else 0

        for auth_attempt in range(2):
            token = self._valid_token()
            headers = {"Authorization": f"Bearer {token}"}
            if existing:
                headers["Range"] = f"bytes={existing}-"

            for _ in range(8):
                try:
                    response = self.session.get(
                        url,
                        headers=headers,
                        stream=True,
                        allow_redirects=False,
                        timeout=self.timeout,
                    )
                except requests.RequestException as exc:
                    raise DownloadError(f"下载连接失败：{exc}") from exc
                if response.status_code in (301, 302, 303, 307, 308):
                    redirect = response.headers.get("Location")
                    response.close()
                    if not redirect:
                        raise DownloadError("下载服务返回了无目标地址的重定向")
                    url = redirect
                    continue
                break
            else:
                raise DownloadError("下载服务重定向次数过多")

            if response.status_code == 401 and auth_attempt == 0:
                response.close()
                self._access_token = ""
                continue
            if response.status_code not in (200, 206):
                detail = response.text[:300]
                response.close()
                raise DownloadError(f"下载服务返回 HTTP {response.status_code}：{detail}")
            return response
        raise AuthenticationError("登录凭据已失效，请重新登录")


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _response_total(response: requests.Response, existing: int) -> int:
    content_range = response.headers.get("Content-Range", "")
    if "/" in content_range:
        try:
            return int(content_range.rsplit("/", 1)[1])
        except ValueError:
            pass
    try:
        return existing + int(response.headers.get("Content-Length", 0))
    except ValueError:
        return 0


def _matches_md5(path: Path, expected: str) -> bool:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected.lower()
