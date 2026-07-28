from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from .aoi import AreaOfInterest
from .exceptions import DownloadCancelled
from .models import SatelliteProduct, SearchCriteria
from .providers.base import SatelliteProvider


class SearchWorker(QObject):
    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        provider: SatelliteProvider,
        criteria: SearchCriteria,
        aoi: AreaOfInterest,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.criteria = criteria
        self.aoi = aoi
        self._cancelled = Event()

    @Slot()
    def run(self) -> None:
        try:
            products = self.provider.search(
                criteria=self.criteria,
                aoi=self.aoi.geometry,
                search_boxes=self.aoi.search_boxes(),
                progress=self.progress.emit,
                cancelled=self._cancelled.is_set,
            )
            self.succeeded.emit(products)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self._cancelled.set()


class DownloadWorker(QObject):
    authenticated = Signal()
    product_started = Signal(int, int, str)
    progress = Signal(int, int, int)
    product_finished = Signal(int, str)
    product_failed = Signal(int, str, str)
    cancelled = Signal()
    completed = Signal(int, int)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        provider: SatelliteProvider,
        products: list[SatelliteProduct],
        destination: Path,
        username: str,
        password: str,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.products = products
        self.destination = destination
        self.username = username
        self.password = password
        self._cancelled = Event()

    @Slot()
    def run(self) -> None:
        succeeded = 0
        failed = 0
        try:
            self.provider.authenticate(self.username, self.password)
            self.password = ""
            self.authenticated.emit()

            count = len(self.products)
            for index, product in enumerate(self.products):
                if self._cancelled.is_set():
                    self.cancelled.emit()
                    break
                self.product_started.emit(index, count, product.name)
                try:
                    path = self.provider.download(
                        product=product,
                        destination=self.destination,
                        progress=lambda current, total, i=index: self.progress.emit(i, current, total),
                        cancelled=self._cancelled.is_set,
                    )
                    succeeded += 1
                    self.product_finished.emit(index, str(path))
                except DownloadCancelled:
                    self.cancelled.emit()
                    break
                except Exception as exc:
                    failed += 1
                    self.product_failed.emit(index, product.name, str(exc))
            self.completed.emit(succeeded, failed)
        except Exception as exc:
            self.password = ""
            self.failed.emit(str(exc))
        finally:
            self.password = ""
            self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self._cancelled.set()

