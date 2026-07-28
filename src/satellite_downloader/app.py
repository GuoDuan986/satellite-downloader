from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .aoi import AreaOfInterest
from .config import APP_NAME, DEFAULT_AOI_BOUNDS, AppPaths
from .providers import CopernicusSentinel2Provider
from .ui.main_window import MainWindow


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setOrganizationName("Aqita")
    application.setStyle("Fusion")

    paths = AppPaths.discover()
    try:
        aoi = AreaOfInterest.from_bounds(DEFAULT_AOI_BOUNDS)
    except Exception as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1

    window = MainWindow(
        paths,
        aoi,
        CopernicusSentinel2Provider(),
    )
    window.show()
    return application.exec()
