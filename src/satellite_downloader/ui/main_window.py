from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QSettings, QThread, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..aoi import AreaOfInterest
from ..config import APP_NAME, AppPaths
from ..models import ProductOrder, SatelliteProduct, SearchCriteria
from ..providers.base import SatelliteProvider
from ..workers import DownloadWorker, SearchWorker


class MainWindow(QMainWindow):
    COL_SELECT = 0
    COL_TIME = 1
    COL_TILE = 2
    COL_CLOUD = 3
    COL_SIZE = 4
    COL_STATUS = 5
    COL_NAME = 6

    def __init__(
        self,
        paths: AppPaths,
        aoi: AreaOfInterest,
        provider: SatelliteProvider,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.aoi = aoi
        self.provider = provider
        self.settings = QSettings("Aqita", "SatelliteImageDownloader")
        self.products: list[SatelliteProduct] = []
        self.search_thread: QThread | None = None
        self.search_worker: SearchWorker | None = None
        self.download_thread: QThread | None = None
        self.download_worker: DownloadWorker | None = None
        self.download_rows: list[int] = []

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(920, 620)
        self._build_ui()
        self._restore_settings()
        self._update_selection_count()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        heading = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        heading.addWidget(title)
        heading.addStretch()
        root.addLayout(heading)

        controls = QGridLayout()
        controls.setHorizontalSpacing(12)
        controls.setVerticalSpacing(8)
        controls.addWidget(self._search_group(), 0, 0)
        controls.addWidget(self._account_group(), 0, 1)
        controls.setColumnStretch(0, 3)
        controls.setColumnStretch(1, 2)
        root.addLayout(controls)

        toolbar = QHBoxLayout()
        self.select_all_button = QPushButton("全选")
        self.select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        self.clear_selection_button = QPushButton("取消全选")
        self.clear_selection_button.clicked.connect(lambda: self._set_all_checked(False))
        self.selection_label = QLabel()
        self.selection_label.setObjectName("muted")
        toolbar.addWidget(self.select_all_button)
        toolbar.addWidget(self.clear_selection_button)
        toolbar.addWidget(self.selection_label)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["选择", "成像时间 (UTC)", "瓦片", "云量", "大小", "状态", "产品名称"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_SELECT, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_TIME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_TILE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_CLOUD, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(self.COL_SELECT, 58)
        self.table.itemChanged.connect(self._table_item_changed)
        root.addWidget(self.table, 1)

        destination_row = QHBoxLayout()
        destination_row.addWidget(QLabel("保存目录"))
        self.destination_edit = QLineEdit()
        self.destination_edit.setReadOnly(True)
        destination_row.addWidget(self.destination_edit, 1)
        self.choose_destination_button = QPushButton("浏览…")
        self.choose_destination_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.choose_destination_button.clicked.connect(self._choose_destination)
        destination_row.addWidget(self.choose_destination_button)
        self.download_button = QPushButton("下载所选")
        self.download_button.setObjectName("primaryButton")
        self.download_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.download_button.clicked.connect(self._start_download)
        destination_row.addWidget(self.download_button)
        self.cancel_download_button = QPushButton("取消下载")
        self.cancel_download_button.setEnabled(False)
        self.cancel_download_button.clicked.connect(self._cancel_download)
        destination_row.addWidget(self.cancel_download_button)
        root.addLayout(destination_row)

        progress_row = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.status_label.setMinimumWidth(310)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        progress_row.addWidget(self.status_label)
        progress_row.addWidget(self.progress_bar, 1)
        root.addLayout(progress_row)

        self.setCentralWidget(central)
        self.setStyleSheet(
            """
            QMainWindow { background: #f5f6f7; }
            QWidget { font-size: 13px; color: #202428; }
            QLabel#title { font-size: 20px; font-weight: 600; }
            QLabel#muted { color: #626a70; }
            QGroupBox {
                background: #ffffff; border: 1px solid #d8dde1;
                border-radius: 6px; margin-top: 8px; padding-top: 8px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit, QDateEdit, QDoubleSpinBox, QSpinBox, QComboBox {
                background: #ffffff; border: 1px solid #bbc3c9;
                border-radius: 4px; padding: 5px 7px; min-height: 20px;
            }
            QPushButton {
                background: #ffffff; border: 1px solid #aeb7bd;
                border-radius: 4px; padding: 6px 12px; min-height: 20px;
            }
            QPushButton:hover { background: #eef2f4; }
            QPushButton:disabled { color: #959da3; background: #eceff1; }
            QPushButton#primaryButton {
                color: #ffffff; background: #176b4d; border-color: #176b4d;
            }
            QPushButton#primaryButton:hover { background: #125b41; }
            QTableWidget {
                background: #ffffff; alternate-background-color: #f7f9fa;
                border: 1px solid #d8dde1; gridline-color: #e7eaec;
            }
            QHeaderView::section {
                background: #e9edef; border: 0; border-right: 1px solid #d4d9dc;
                border-bottom: 1px solid #cbd1d5; padding: 7px 6px; font-weight: 600;
            }
            QProgressBar { border: 1px solid #bbc3c9; border-radius: 3px; text-align: center; }
            QProgressBar::chunk { background: #2f8062; }
            """
        )

    def _search_group(self) -> QGroupBox:
        group = QGroupBox("影像检索")
        layout = QGridLayout(group)
        layout.setContentsMargins(12, 14, 12, 10)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        layout.addWidget(QLabel("数据集"), 0, 0)
        dataset = QLineEdit("Sentinel-2 L2A")
        dataset.setReadOnly(True)
        dataset.setFixedWidth(130)
        layout.addWidget(dataset, 0, 1)

        layout.addWidget(QLabel("开始"), 0, 2)
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1))
        layout.addWidget(self.start_date_edit, 0, 3)

        layout.addWidget(QLabel("结束"), 0, 4)
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_date_edit.setDate(QDate.currentDate())
        layout.addWidget(self.end_date_edit, 0, 5)

        layout.addWidget(QLabel("最大云量"), 1, 0)
        self.cloud_spin = QDoubleSpinBox()
        self.cloud_spin.setRange(0, 100)
        self.cloud_spin.setDecimals(1)
        self.cloud_spin.setSuffix(" %")
        self.cloud_spin.setValue(30)
        self.cloud_spin.setFixedWidth(90)
        layout.addWidget(self.cloud_spin, 1, 1)

        layout.addWidget(QLabel("最多"), 1, 2)
        self.max_results_spin = QSpinBox()
        self.max_results_spin.setRange(10, 5000)
        self.max_results_spin.setSingleStep(50)
        self.max_results_spin.setValue(500)
        self.max_results_spin.setSuffix(" 景")
        self.max_results_spin.setFixedWidth(90)
        layout.addWidget(self.max_results_spin, 1, 3)

        layout.addWidget(QLabel("排列"), 2, 0)
        self.product_order_combo = QComboBox()
        self.product_order_combo.addItem("全部按时间倒序", ProductOrder.TIME_DESC.value)
        self.product_order_combo.addItem(
            "按瓦片聚合（组内时间倒序）",
            ProductOrder.TILE_THEN_TIME_DESC.value,
        )
        self.product_order_combo.setFixedWidth(230)
        self.product_order_combo.currentIndexChanged.connect(
            self._product_order_changed
        )
        layout.addWidget(self.product_order_combo, 2, 1, 1, 3)

        self.search_button = QPushButton("搜索")
        self.search_button.setObjectName("primaryButton")
        self.search_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        self.search_button.clicked.connect(self._start_search)
        layout.addWidget(self.search_button, 1, 4)
        self.cancel_search_button = QPushButton("停止")
        self.cancel_search_button.setEnabled(False)
        self.cancel_search_button.clicked.connect(self._cancel_search)
        layout.addWidget(self.cancel_search_button, 1, 5)
        layout.setColumnStretch(3, 1)
        layout.setColumnStretch(5, 1)
        return group

    def _account_group(self) -> QGroupBox:
        group = QGroupBox("Copernicus Data Space 账号")
        layout = QFormLayout(group)
        layout.setContentsMargins(12, 14, 12, 10)
        layout.setHorizontalSpacing(8)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("用户名或邮箱")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("密码")
        self.show_password_check = QCheckBox("显示")
        self.show_password_check.toggled.connect(
            lambda checked: self.password_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        password_row = QHBoxLayout()
        password_row.addWidget(self.password_edit, 1)
        password_row.addWidget(self.show_password_check)
        layout.addRow("账号", self.username_edit)
        layout.addRow("密码", password_row)
        return group

    def _restore_settings(self) -> None:
        destination = self.settings.value("download_directory", str(self.paths.default_downloads))
        username = self.settings.value("username", "")
        product_order = str(
            self.settings.value("product_order", ProductOrder.TIME_DESC.value)
        )
        self.destination_edit.setText(str(destination))
        self.username_edit.setText(str(username))
        order_index = self.product_order_combo.findData(product_order)
        self.product_order_combo.setCurrentIndex(max(0, order_index))

    def _criteria(self) -> SearchCriteria:
        start_qdate = self.start_date_edit.date()
        end_qdate = self.end_date_edit.date()
        criteria = SearchCriteria(
            start_date=date(start_qdate.year(), start_qdate.month(), start_qdate.day()),
            end_date=date(end_qdate.year(), end_qdate.month(), end_qdate.day()),
            max_cloud_cover=self.cloud_spin.value(),
            max_results=self.max_results_spin.value(),
            product_order=ProductOrder(self.product_order_combo.currentData()),
        )
        criteria.validate()
        return criteria

    def _start_search(self) -> None:
        if self.search_thread or self.download_thread:
            return
        try:
            criteria = self._criteria()
        except ValueError as exc:
            QMessageBox.warning(self, "检索条件", str(exc))
            return

        self.table.setRowCount(0)
        self.products.clear()
        self._set_busy(True, "正在检索卫星影像…")
        self.progress_bar.setRange(0, 0)

        thread = QThread(self)
        worker = SearchWorker(self.provider, criteria, self.aoi)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._search_progress)
        worker.succeeded.connect(self._search_succeeded)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._search_thread_finished)
        self.search_thread = thread
        self.search_worker = worker
        self.cancel_search_button.setEnabled(True)
        thread.start()

    def _search_progress(self, current: int, total: int) -> None:
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.status_label.setText(
            f"正在检索 {current + 1}/{total}…"
            if current < total
            else "正在整理结果…"
        )

    def _search_succeeded(self, products: object) -> None:
        self.products = list(products)  # type: ignore[arg-type]
        self._populate_table()
        self.status_label.setText(
            f"找到 {len(self.products)} 景 Sentinel-2 L2A 影像"
        )
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

    def _product_order_changed(self) -> None:
        order = ProductOrder(self.product_order_combo.currentData())
        self.settings.setValue("product_order", order.value)
        if not self.products or self.search_thread or self.download_thread:
            return

        table_state = self._capture_table_state()
        self.products = self.provider.arrange_products(self.products, order)
        self._populate_table(table_state)

    def _capture_table_state(
        self,
    ) -> dict[str, tuple[Qt.CheckState, str, QBrush, str]]:
        state: dict[str, tuple[Qt.CheckState, str, QBrush, str]] = {}
        for row, product in enumerate(self.products):
            check_item = self.table.item(row, self.COL_SELECT)
            status_item = self.table.item(row, self.COL_STATUS)
            state[product.product_id] = (
                check_item.checkState(),
                status_item.text(),
                status_item.foreground(),
                status_item.toolTip(),
            )
        return state

    def _populate_table(
        self,
        table_state: dict[str, tuple[Qt.CheckState, str, QBrush, str]] | None = None,
    ) -> None:
        table_state = table_state or {}
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.products))
        for row, product in enumerate(self.products):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, self.COL_SELECT, check_item)
            self._set_cell(row, self.COL_TIME, product.sensing_time.strftime("%Y-%m-%d %H:%M"))
            self._set_cell(row, self.COL_TILE, product.tile_id or "—", center=True)
            cloud = f"{product.cloud_cover:.1f} %" if product.cloud_cover is not None else "—"
            self._set_cell(row, self.COL_CLOUD, cloud, center=True)
            self._set_cell(row, self.COL_SIZE, product.size_text, center=True)
            self._set_cell(row, self.COL_STATUS, "在线" if product.online else "离线", center=True)
            self._set_cell(row, self.COL_NAME, product.name)
            if product.product_id in table_state:
                check_state, status, foreground, tooltip = table_state[product.product_id]
                check_item.setCheckState(check_state)
                status_item = self.table.item(row, self.COL_STATUS)
                status_item.setText(status)
                status_item.setForeground(foreground)
                status_item.setToolTip(tooltip)
        self.table.blockSignals(False)
        self._update_selection_count()

    def _set_cell(self, row: int, column: int, text: str, center: bool = False) -> None:
        item = QTableWidgetItem(text)
        if center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, column, item)

    def _cancel_search(self) -> None:
        if self.search_worker:
            self.search_worker.cancel()
            self.status_label.setText("正在停止检索…")
            self.cancel_search_button.setEnabled(False)

    def _search_thread_finished(self) -> None:
        self.search_thread = None
        self.search_worker = None
        self._set_busy(False)

    def _operation_failed(self, message: str) -> None:
        self.status_label.setText("操作失败")
        QMessageBox.critical(self, "操作失败", message)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.search_button.setEnabled(not busy)
        self.cancel_search_button.setEnabled(busy and self.search_thread is not None)
        self.download_button.setEnabled(not busy)
        self.choose_destination_button.setEnabled(not busy)
        self.product_order_combo.setEnabled(not busy)
        if message:
            self.status_label.setText(message)

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == self.COL_SELECT:
            self._update_selection_count()

    def _selected_rows(self) -> list[int]:
        return [
            row
            for row in range(self.table.rowCount())
            if self.table.item(row, self.COL_SELECT).checkState() == Qt.CheckState.Checked
        ]

    def _update_selection_count(self) -> None:
        count = len(self._selected_rows()) if self.table.rowCount() else 0
        self.selection_label.setText(f"已选择 {count} / {len(self.products)} 景")

    def _set_all_checked(self, checked: bool) -> None:
        self.table.blockSignals(True)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, self.COL_SELECT).setCheckState(state)
        self.table.blockSignals(False)
        self._update_selection_count()

    def _choose_destination(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "选择影像保存目录", self.destination_edit.text()
        )
        if selected:
            self.destination_edit.setText(selected)
            self.settings.setValue("download_directory", selected)

    def _start_download(self) -> None:
        if self.download_thread or self.search_thread:
            return
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "下载", "请先勾选要下载的影像")
            return
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "Copernicus 账号", "下载前请输入账号和密码")
            return
        destination = Path(self.destination_edit.text()).expanduser()
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "保存目录", f"无法创建保存目录：{exc}")
            return

        self.settings.setValue("download_directory", str(destination))
        self.settings.setValue("username", username)
        products = [self.products[row] for row in rows]
        self.download_rows = rows
        self._set_busy(True, "正在登录 Copernicus Data Space…")
        self.cancel_search_button.setEnabled(False)
        self.cancel_download_button.setEnabled(True)
        self.progress_bar.setRange(0, 0)

        thread = QThread(self)
        worker = DownloadWorker(
            self.provider, products, destination, username, password
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.authenticated.connect(lambda: self.status_label.setText("登录成功，准备下载…"))
        worker.product_started.connect(self._download_product_started)
        worker.progress.connect(self._download_progress)
        worker.product_finished.connect(self._download_product_finished)
        worker.product_failed.connect(self._download_product_failed)
        worker.cancelled.connect(lambda: self.status_label.setText("下载已取消，断点已保留"))
        worker.completed.connect(self._download_completed)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._download_thread_finished)
        self.download_thread = thread
        self.download_worker = worker
        thread.start()

    def _download_product_started(self, index: int, total: int, name: str) -> None:
        self.status_label.setText(f"正在下载 {index + 1}/{total}：{name}")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        row = self.download_rows[index]
        self.table.item(row, self.COL_STATUS).setText("下载中")
        self.table.selectRow(row)

    def _download_progress(self, index: int, current: int, total: int) -> None:
        if total > 0:
            percent = min(100, int(current * 100 / total))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(f"{percent}%  ({_human_size(current)} / {_human_size(total)})")
        else:
            self.progress_bar.setRange(0, 0)

    def _download_product_finished(self, index: int, path: str) -> None:
        row = self.download_rows[index]
        item = self.table.item(row, self.COL_STATUS)
        item.setText("已下载")
        item.setForeground(QColor("#176b4d"))
        item.setToolTip(path)

    def _download_product_failed(self, index: int, name: str, message: str) -> None:
        row = self.download_rows[index]
        item = self.table.item(row, self.COL_STATUS)
        item.setText("失败")
        item.setForeground(QColor("#b42318"))
        item.setToolTip(message)
        self.status_label.setText(f"{name} 下载失败，继续下一景")

    def _download_completed(self, succeeded: int, failed: int) -> None:
        if self.download_worker and self.download_worker._cancelled.is_set():
            return
        self.status_label.setText(f"下载完成：成功 {succeeded} 景，失败 {failed} 景")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if succeeded else 0)
        if failed:
            QMessageBox.warning(self, "下载完成", f"成功 {succeeded} 景，失败 {failed} 景。\n可查看状态列提示后重试。")

    def _cancel_download(self) -> None:
        if self.download_worker:
            self.download_worker.cancel()
            self.cancel_download_button.setEnabled(False)
            self.status_label.setText("正在取消，已下载部分将保留…")

    def _download_thread_finished(self) -> None:
        self.download_thread = None
        self.download_worker = None
        self.download_rows = []
        self.cancel_download_button.setEnabled(False)
        self.progress_bar.setFormat("%p%")
        self._set_busy(False)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.search_worker or self.download_worker:
            answer = QMessageBox.question(
                self,
                "退出",
                "当前任务仍在运行。确定取消任务并退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self.search_worker:
                self.search_worker.cancel()
            if self.download_worker:
                self.download_worker.cancel()
            event.ignore()
            self.status_label.setText("正在停止任务，完成后请再次关闭窗口…")
            return
        super().closeEvent(event)


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"
