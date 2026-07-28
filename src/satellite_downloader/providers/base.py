from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from pathlib import Path

from shapely.geometry.base import BaseGeometry

from ..models import ProductOrder, SatelliteProduct, SearchCriteria, order_products


CancelCheck = Callable[[], bool]
SearchProgress = Callable[[int, int], None]
DownloadProgress = Callable[[int, int], None]


class SatelliteProvider(ABC):
    display_name: str

    def arrange_products(
        self,
        products: Iterable[SatelliteProduct],
        order: ProductOrder,
    ) -> list[SatelliteProduct]:
        return order_products(products, order)

    @abstractmethod
    def search(
        self,
        criteria: SearchCriteria,
        aoi: BaseGeometry,
        search_boxes: list[tuple[float, float, float, float]],
        progress: SearchProgress,
        cancelled: CancelCheck,
    ) -> list[SatelliteProduct]:
        raise NotImplementedError

    @abstractmethod
    def authenticate(self, username: str, password: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def download(
        self,
        product: SatelliteProduct,
        destination: Path,
        progress: DownloadProgress,
        cancelled: CancelCheck,
    ) -> Path:
        raise NotImplementedError
