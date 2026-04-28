# -*- coding: utf-8 -*-
# heatmap_viewer.py

import os
import numpy as np
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from PySide.QtWidgets import QSizePolicy

import matplotlib

matplotlib.use("Agg")

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .scan_db import HitsDB

DOCK_OBJECT_NAME = "BeamAbsorberHeatmapDock"


class BeamAbsorberHeatmapDock(QtWidgets.QDockWidget):

    # ==========================================================
    # INIT
    # ==========================================================
    def __init__(self, parent=None):
        super().__init__("Heatmap Viewer", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        self.db = HitsDB()
        self._last_mtime = None

        self._build_ui()
        self._populate_doc_list()
        self._populate_targets()
        self._populate_emitters()
        self._update_plot()

        self._watch = QtCore.QTimer(self)
        self._watch.timeout.connect(self._maybe_refresh)
        self._watch.start(500)

    # ==========================================================
    # UI
    # ==========================================================
    def _build_ui(self):
        central = QtWidgets.QWidget(self)
        self.setWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        form = QtWidgets.QFormLayout()

        self.comboDoc = QtWidgets.QComboBox()
        self.comboTarget = QtWidgets.QComboBox()

        self.comboPlane = QtWidgets.QComboBox()
        self.comboPlane.addItems(["XY", "XZ", "YZ"])

        self.comboValue = QtWidgets.QComboBox()
        self.comboValue.addItem("Hits", "hits")
        self.comboValue.addItem("Power In", "power_in")
        self.comboValue.addItem("Power Out", "power_out")

        row_doc = QtWidgets.QHBoxLayout()
        self.btnReload = QtWidgets.QPushButton("Reload")
        self.btnDeleteDoc = QtWidgets.QPushButton("Delete")

        row_doc.addWidget(self.comboDoc)
        row_doc.addWidget(self.btnReload)
        row_doc.addWidget(self.btnDeleteDoc)

        form.addRow("Document:", self._wrap(row_doc))
        form.addRow("Target object:", self.comboTarget)
        form.addRow("Value:", self.comboValue)

        # Emitters
        self.emitterBox = QtWidgets.QGroupBox("Emitters")
        self.emitterLayout = QtWidgets.QVBoxLayout(self.emitterBox)
        form.addRow(self.emitterBox)

        # Options
        self.chkSmooth = QtWidgets.QCheckBox("Smooth")
        self.spinSmooth = QtWidgets.QSpinBox()
        self.spinSmooth.setRange(1, 10)
        self.spinSmooth.setValue(2)

        self.chkPercent = QtWidgets.QCheckBox("Show %")

        row_opt = QtWidgets.QHBoxLayout()
        row_opt.addWidget(QtWidgets.QLabel("Plane:"))
        row_opt.addWidget(self.comboPlane)
        row_opt.addSpacing(20)
        row_opt.addWidget(self.chkSmooth)
        row_opt.addWidget(QtWidgets.QLabel("Strength:"))
        row_opt.addWidget(self.spinSmooth)
        row_opt.addSpacing(20)
        row_opt.addWidget(self.chkPercent)

        form.addRow(row_opt)
        layout.addLayout(form)

        # Plots
        plotArea = QtWidgets.QHBoxLayout()

        self.fig3d = Figure(figsize=(5, 5))
        self.canvas3d = FigureCanvas(self.fig3d)
        self.canvas3d.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.figProf = Figure(figsize=(5, 5))
        self.canvasProf = FigureCanvas(self.figProf)
        self.canvasProf.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        plotArea.addWidget(self.canvas3d)
        plotArea.addWidget(self.canvasProf)
        layout.addLayout(plotArea, 1)

        # Signals
        self.comboDoc.currentIndexChanged.connect(self._doc_changed)
        self.comboTarget.currentIndexChanged.connect(self._target_changed)
        self.btnReload.clicked.connect(self._reload_structure)

        self.comboPlane.currentIndexChanged.connect(self._update_plot)
        self.comboValue.currentIndexChanged.connect(self._update_plot)

        self.chkSmooth.toggled.connect(self._update_plot)
        self.spinSmooth.valueChanged.connect(self._update_plot)
        self.chkPercent.toggled.connect(self._update_plot)

        self.btnDeleteDoc.clicked.connect(self._on_delete_document_clicked)

    def _wrap(self, layout):
        w = QtWidgets.QWidget()
        w.setLayout(layout)
        return w

    def _reload_structure(self):
        self._last_mtime = None  # reset watcher
        self._populate_doc_list()
        self._populate_targets()
        self._populate_emitters()
        self._update_plot()

    # ==========================================================
    # DATA
    # ==========================================================
    def _populate_doc_list(self):
        current = self.comboDoc.currentText()
        docs = self.db.list_documents()

        self.comboDoc.blockSignals(True)
        self.comboDoc.clear()
        self.comboDoc.addItems(docs if docs else ["<none>"])
        if current:
            i = self.comboDoc.findText(current)
            if i >= 0:
                self.comboDoc.setCurrentIndex(i)
        self.comboDoc.blockSignals(False)

    def _populate_targets(self):
        self.comboTarget.clear()
        doc = self.comboDoc.currentText()
        if "<" in doc:
            return
        self.comboTarget.addItems(self.db.list_target_objects(doc))

    def _populate_emitters(self):
        while self.emitterLayout.count():
            w = self.emitterLayout.takeAt(0).widget()
            if w:
                w.deleteLater()

        doc = self.comboDoc.currentText()
        target = self.comboTarget.currentText()
        if not doc or not target or "<" in doc:
            return

        self.emitter_checks = {}
        for em in self.db.list_emitters(doc, target):
            chk = QtWidgets.QCheckBox(em)
            chk.setChecked(em == "__ALL__")
            chk.toggled.connect(self._update_plot)
            self.emitterLayout.addWidget(chk)
            self.emitter_checks[em] = chk

    # ==========================================================
    # CORE
    # ==========================================================
    def _doc_changed(self):
        self._last_mtime = None
        self._populate_targets()
        self._populate_emitters()
        self._update_plot()

    def _target_changed(self):
        self._populate_emitters()
        self._update_plot()

    def _maybe_refresh(self):
        try:
            mtime = os.path.getmtime(self.db.path)
        except Exception:
            return
        if mtime != self._last_mtime:
            self._last_mtime = mtime
            self._update_plot()

    def _get_selected_emitters(self):
        if "__ALL__" in self.emitter_checks and self.emitter_checks["__ALL__"].isChecked():
            return ["__ALL__"]
        return [e for e, chk in self.emitter_checks.items() if chk.isChecked()]

    def _update_plot(self):
        doc = self.comboDoc.currentText()
        target = self.comboTarget.currentText()

        if "<" in doc or not target:
            self._clear_plots()
            return

        emitters = self._get_selected_emitters()
        if not emitters:
            self._clear_plots()
            return

        # Samlingsarrayer
        X = Y = Z = V = None

        value_key = self.comboValue.currentText()
        # value_key är: "Hits", "Power In", "Power Out"

        for em in emitters:
            # NYTT schema
            Xi, Yi, Zi, Hi, Pin, Pout = self.db.read_grid(doc, target, em)
            if not Xi:
                continue

            # Välj korrekt observabel
            if value_key == "Hits":
                val = np.asarray(Hi, dtype=float)
            elif value_key == "Power In":
                val = np.asarray(Pin, dtype=float)
            elif value_key == "Power Out":
                val = np.asarray(Pout, dtype=float)
            else:
                continue

            if V is None:
                X = np.asarray(Xi)
                Y = np.asarray(Yi)
                Z = np.asarray(Zi)
                V = val.copy()
            else:
                V += val

        if V is None:
            self._clear_plots()
            return

        # Projektion
        plane = self.comboPlane.currentText()
        if plane == "XY":
            px, py = X, Y
        elif plane == "XZ":
            px, py = X, Z
        else:  # YZ
            px, py = Y, Z

        # Grid / interpolation
        Xi, Yi, Vi = self._build_grid(px, py, V)

        # Procentläge
        if self.chkPercent.isChecked():
            Vi, _ = self._to_percent(Vi)

        # Plot
        self._plot_surface(Xi, Yi, Vi, plane)
        self._plot_profiles(Xi, Yi, Vi)

    def _update_plot_old(self):
        doc = self.comboDoc.currentText()
        target = self.comboTarget.currentText()

        if "<" in doc or not target:
            self._clear_plots()
            return

        emitters = self._get_selected_emitters()
        if not emitters:
            self._clear_plots()
            return

        X = Y = Z = V = None
        use_power = self.comboValue.currentText() == "Power"

        for em in emitters:
            Xi, Yi, Zi, Hi, Pi = self.db.read_grid(doc, target, em)

            if not Xi:
                continue

            val = np.asarray(Pi if use_power else Hi)

            if V is None:
                X, Y, Z, V = map(np.asarray, (Xi, Yi, Zi, val))
            else:
                V += val

        if V is None:
            self._clear_plots()
            return

        plane = self.comboPlane.currentText()
        if plane == "XY":
            px, py = X, Y
        elif plane == "XZ":
            px, py = X, Z
        else:
            px, py = Y, Z

        Xi, Yi, Vi = self._build_grid(px, py, V)

        if self.chkPercent.isChecked():
            Vi, _ = self._to_percent(Vi)

        self._plot_surface(Xi, Yi, Vi, plane)
        self._plot_profiles(Xi, Yi, Vi)

    # ==========================================================
    # GRID / FILTERS
    # ==========================================================
    def _build_grid(self, X, Y, V, res=80):
        xi = np.linspace(X.min(), X.max(), res)
        yi = np.linspace(Y.min(), Y.max(), res)
        Xi, Yi = np.meshgrid(xi, yi)

        Vi = np.zeros_like(Xi)
        for i in range(res):
            for j in range(res):
                d = np.sqrt((X - Xi[i, j]) ** 2 + (Y - Yi[i, j]) ** 2)
                w = 1.0 / (d + 1e-6)
                Vi[i, j] = np.sum(w * V) / np.sum(w)

        # if self.chkSmooth.isChecked():
        #     Vi = self._median(Vi, 3)

        if self.chkSmooth.isChecked():
            strength = self.spinSmooth.value()
            k = max(1, 2 * strength + 1)
            Vi = self._median(Vi, k)

        return Xi, Yi, Vi

    def _median(self, data, k=3):
        pad = k // 2
        p = np.pad(data, pad, mode="edge")
        out = np.zeros_like(data)
        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                out[i, j] = np.median(p[i : i + k, j : j + k])
        return out

    def _to_percent(self, data):
        m = np.max(data)
        if not np.isfinite(m) or m <= 0:
            return np.zeros_like(data), 0
        return data / m * 100.0, m

    # ==========================================================
    # PLOTS
    # ==========================================================
    def _plot_surface(self, Xi, Yi, Vi, plane):
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")
        ax.plot_surface(Xi, Yi, Vi, cmap="viridis")
        ax.set_title(f"{plane}")
        self.canvas3d.draw_idle()

    def _plot_profiles(self, Xi, Yi, Vi):
        self.figProf.clear()
        ax = self.figProf.add_subplot(111)
        ax.plot(Xi[Vi.shape[0] // 2], Vi[Vi.shape[0] // 2], label="X profile")
        ax.plot(Yi[:, Vi.shape[1] // 2], Vi[:, Vi.shape[1] // 2], "--", label="Y profile")
        ax.legend()
        ax.grid(True)
        self.canvasProf.draw_idle()

    # ==========================================================
    def _clear_plots(self):
        self.fig3d.clear()
        self.figProf.clear()
        self.canvas3d.draw_idle()
        self.canvasProf.draw_idle()

    def _on_delete_document_clicked(self):
        doc = self.comboDoc.currentText()
        if "<" in doc:
            return
        if QtWidgets.QMessageBox.question(self, "Delete", f"Delete {doc}?") == QtWidgets.QMessageBox.Yes:
            self.db.delete_document(doc)
            self._populate_doc_list()
            self._clear_plots()


# ==========================================================
def ShowHeatmapViewer():
    mw = Gui.getMainWindow()
    old = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if old:
        mw.removeDockWidget(old)
        old.deleteLater()

    dock = BeamAbsorberHeatmapDock(mw)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()
    return dock
