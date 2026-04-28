# -*- coding: utf-8 -*-
# show_xyz_live_list.py

"""
DocXYZLiveDialog – visar XYZ + Hits + PowerIn / PowerOut
direkt från collect_ray_hits_and_stats (ingen DB, alltid mode="final")
"""

import csv
from PySide import QtCore, QtWidgets
import FreeCADGui as Gui

from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats
from .filter_panel import ClusterHitFilterPanel


class DocXYZLiveDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())

        self.setWindowTitle("XYZ + Hits + Power (Live, Final)")
        self.setModal(True)
        self.setMinimumSize(1100, 650)

        self._build_ui()
        self._wire()

        # 🔥 alltid final
        self.filterPanel.set_mode("final")
        self._reload()

    # ------------------------------------------------------------
    # UI
    # ------------------------------------------------------------
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # ---------- TOP BAR ----------
        top = QtWidgets.QHBoxLayout()

        self.btnReload = QtWidgets.QPushButton("Reload")
        top.addWidget(self.btnReload)

        top.addStretch(1)

        self.chkShowFilter = QtWidgets.QCheckBox("Show Filter")
        self.chkShowFilter.setChecked(True)
        top.addWidget(self.chkShowFilter)

        root.addLayout(top)

        # ---------- TABLE ----------
        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setColumnCount(6)
        self.tbl.setHorizontalHeaderLabels(["X", "Y", "Z", "Hits", "Power In", "Power Out"])
        self.tbl.setSortingEnabled(True)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # ---------- FILTER PANEL (REUSED) ----------
        self.filterPanel = ClusterHitFilterPanel(self)
        self.filterPanel.setMaximumHeight(220)

        # ---------- SPLITTER (TABLE | FILTER) ----------
        self.mainSplitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.mainSplitter.addWidget(self.tbl)
        self.mainSplitter.addWidget(self.filterPanel)
        self.mainSplitter.setStretchFactor(0, 1)  # tabell prioritet
        self.mainSplitter.setStretchFactor(1, 0)  # filter sekundär

        root.addWidget(self.mainSplitter, 1)

        # ---------- STATUS ----------
        self.lblStatus = QtWidgets.QLabel("")
        self.lblStatus.setStyleSheet("color: gray;")
        root.addWidget(self.lblStatus)

        # ---------- BUTTONS ----------
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)

        self.btnCopy = QtWidgets.QPushButton("Kopiera")
        self.btnCSV = QtWidgets.QPushButton("Exportera CSV")
        self.btnClose = QtWidgets.QPushButton("Stäng")

        btns.addWidget(self.btnCopy)
        btns.addWidget(self.btnCSV)
        btns.addWidget(self.btnClose)

        root.addLayout(btns)

    # ------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------
    def _wire(self):
        self.btnReload.clicked.connect(self._reload)
        self.filterPanel.filter_changed.connect(self._reload)
        self.chkShowFilter.toggled.connect(self.filterPanel.setVisible)

        self.btnCopy.clicked.connect(self._copy_clipboard)
        self.btnCSV.clicked.connect(self._export_csv)
        self.btnClose.clicked.connect(self.accept)

    # ------------------------------------------------------------
    # Data logic (LIVE, FINAL)
    # ------------------------------------------------------------
    def _reload(self):
        hits, _stats = collect_ray_hits_and_stats(mode="final")

        filter_spec = self.filterPanel.get_filter_spec()
        allowed_emitters = set(filter_spec["emitters"])
        allowed_objects = set(filter_spec["objects"])

        # ---------- Aggregate per (object, point) ----------
        accum = {}

        for h in hits:
            emitter = h.get("emitter_id")
            obj = h.get("object")

            if emitter not in allowed_emitters:
                continue
            if obj not in allowed_objects:
                continue

            pt = h["point"]
            key = (obj, pt)

            if key not in accum:
                accum[key] = {
                    "x": pt[0],
                    "y": pt[1],
                    "z": pt[2],
                    "hits": 0,
                    "power_in": 0.0,
                    "power_out": 0.0,
                }

            a = accum[key]
            a["hits"] += 1
            a["power_in"] += h.get("power_in") or 0.0
            a["power_out"] += h.get("power_out") or 0.0

        # ---------- Fill table ----------
        self.tbl.setSortingEnabled(False)
        self.tbl.setRowCount(len(accum))

        sum_hits = 0
        sum_pin = 0.0
        sum_pout = 0.0

        for row, a in enumerate(accum.values()):
            self.tbl.setItem(row, 0, self._num_item(a["x"]))
            self.tbl.setItem(row, 1, self._num_item(a["y"]))
            self.tbl.setItem(row, 2, self._num_item(a["z"]))
            self.tbl.setItem(row, 3, self._num_item(a["hits"]))
            self.tbl.setItem(row, 4, self._num_item(a["power_in"]))
            self.tbl.setItem(row, 5, self._num_item(a["power_out"]))

            sum_hits += a["hits"]
            sum_pin += a["power_in"]
            sum_pout += a["power_out"]

        self.tbl.setSortingEnabled(True)

        status = (f"Punkter: {len(accum):,} | Hits: {sum_hits:,} | " f"Σ Power In: {sum_pin:.6g} | Σ Power Out: {sum_pout:.6g}").replace(",", " ")

        self.lblStatus.setText(status)

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _num_item(self, v):
        it = QtWidgets.QTableWidgetItem()
        it.setData(QtCore.Qt.EditRole, v)
        it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
        return it

    # ------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------
    def _copy_clipboard(self):
        rows = self.tbl.rowCount()
        cols = self.tbl.columnCount()

        lines = []
        headers = [self.tbl.horizontalHeaderItem(c).text() for c in range(cols)]
        lines.append("\t".join(headers))

        for r in range(rows):
            vals = [self.tbl.item(r, c).text() if self.tbl.item(r, c) else "" for c in range(cols)]
            lines.append("\t".join(vals))

        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    def _export_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Exportera CSV", "", "CSV (*.csv)")
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow([self.tbl.horizontalHeaderItem(c).text() for c in range(self.tbl.columnCount())])
            for r in range(self.tbl.rowCount()):
                w.writerow([self.tbl.item(r, c).text() if self.tbl.item(r, c) else "" for c in range(self.tbl.columnCount())])


# ------------------------------------------------------------
def OBA_ShowXYZLiveList(parent=None):
    if parent is None and Gui:
        parent = Gui.getMainWindow()

    dlg = DocXYZLiveDialog(parent)
    dlg.show()

    Gui._xyz_live_list_dialog = dlg
    return dlg
