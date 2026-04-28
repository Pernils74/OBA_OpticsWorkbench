# -*- coding: utf-8 -*-
# cluster_plot.py

import os
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5 import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # noqa

from .cluster_core import *
from oba_rayengine.oba_ray_core import OBARayManager
from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats
from .show_xyz_live_list import OBA_ShowXYZLiveList
from .filter_panel import ClusterHitFilterPanel

ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "icons")


# -------------------------------------------------
class ClusterPlotDialog(QtWidgets.QDialog):

    def __init__(self):
        super().__init__(Gui.getMainWindow())

        self.setWindowTitle("Cluster Plot")
        self.resize(1100, 900)

        OBARayManager().add_listener(self.on_rays_updated)

        self._init_ui()
        self.reload_plot()

    # -------------------------------------------------
    def _init_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # ================= TOP BAR =================
        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)

        top.addWidget(QtWidgets.QLabel("Mode:"))
        self.cmbMode = QtWidgets.QComboBox()
        self.cmbMode.addItems(["final", "all"])
        top.addWidget(self.cmbMode)

        btnReload = QtWidgets.QPushButton("Reload")
        btnReload.clicked.connect(self.reload_plot)
        top.addWidget(btnReload)

        top.addSpacing(15)

        top.addWidget(QtWidgets.QLabel("Plane:"))
        self.cmbPlane = QtWidgets.QComboBox()
        self.cmbPlane.addItems(["XY", "XZ", "YZ"])
        top.addWidget(self.cmbPlane)

        self.chkFlip = QtWidgets.QCheckBox("Flip")
        top.addWidget(self.chkFlip)

        self.chkGrid = QtWidgets.QCheckBox("Grid")
        self.chkGrid.setChecked(True)
        top.addWidget(self.chkGrid)

        self.chkEqual = QtWidgets.QCheckBox("Equal")
        self.chkEqual.setChecked(True)
        top.addWidget(self.chkEqual)

        self.chkBlobs = QtWidgets.QCheckBox("Blobs")
        self.chkBlobs.setChecked(True)
        top.addWidget(self.chkBlobs)

        self.chkSmooth = QtWidgets.QCheckBox("Smooth")
        self.chkSmooth.setChecked(True)
        top.addWidget(self.chkSmooth)

        self.chkCentroids = QtWidgets.QCheckBox("Centroids")
        self.chkCentroids.setChecked(True)
        top.addWidget(self.chkCentroids)

        top.addStretch()

        # ---- Filter + 3D ----
        self.chkShowFilter = QtWidgets.QCheckBox("Show Filter")
        self.chkShowFilter.setChecked(True)
        top.addWidget(self.chkShowFilter)

        self.chk3D = QtWidgets.QCheckBox("3D")
        self.chk3D.setChecked(False)
        self.chk3D.toggled.connect(self._update_plot_layout)
        top.addWidget(self.chk3D)

        self.btnXYZ = QtWidgets.QPushButton("XYZ list")
        self.btnXYZ.clicked.connect(self._open_xyz_list)
        top.addWidget(self.btnXYZ)

        # ================= FIGURES =================
        self.fig2d = Figure()
        self.canvas2d = FigureCanvas(self.fig2d)
        self.toolbar = NavigationToolbar(self.canvas2d, self)

        self.fig3d = Figure()
        self.canvas3d = FigureCanvas(self.fig3d)
        self.canvas3d.setVisible(False)

        root.addWidget(self.toolbar)

        # ---- Horizontal splitter: 2D | 3D ----
        self.plotSplitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.plotSplitter.addWidget(self.canvas2d)
        self.plotSplitter.addWidget(self.canvas3d)
        self.plotSplitter.setStretchFactor(0, 1)
        self.plotSplitter.setStretchFactor(1, 1)

        # ================= FILTER PANEL =================
        self.filterPanel = ClusterHitFilterPanel(self)
        self.filterPanel.setMaximumHeight(220)
        self.filterPanel.filter_changed.connect(self.reload_plot)

        self.chkShowFilter.toggled.connect(self.filterPanel.setVisible)

        # ================= MAIN VERTICAL SPLITTER =================
        mainSplitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        mainSplitter.addWidget(self.plotSplitter)
        mainSplitter.addWidget(self.filterPanel)
        mainSplitter.setStretchFactor(0, 1)  # plot prioritet
        mainSplitter.setStretchFactor(1, 0)  # filter sekundär

        root.addWidget(mainSplitter)

        # ================= STATUS =================
        self.lblStatus = QtWidgets.QLabel("")
        root.addWidget(self.lblStatus)

        # ================= SIGNALS =================
        self.cmbPlane.currentIndexChanged.connect(self.reload_plot)
        self.cmbMode.currentIndexChanged.connect(self._on_mode_changed)

        for chk in (
            self.chkFlip,
            self.chkGrid,
            self.chkEqual,
            self.chkBlobs,
            self.chkSmooth,
            self.chkCentroids,
        ):
            chk.stateChanged.connect(self.reload_plot)

        # init filter panel
        self._on_mode_changed()

    # -------------------------------------------------
    def _on_mode_changed(self):
        mode = self.cmbMode.currentText()
        self.filterPanel.set_mode(None if mode == "all" else mode)
        self.reload_plot()

    # -------------------------------------------------
    def _update_plot_layout(self, enabled):
        self.canvas3d.setVisible(enabled)
        self.plotSplitter.setSizes([1, 1] if enabled else [1, 0])
        self.reload_plot()

    # -------------------------------------------------
    def _open_xyz_list(self):
        OBA_ShowXYZLiveList(parent=self)

    # -------------------------------------------------
    def on_rays_updated(self):
        QtCore.QTimer.singleShot(0, self.reload_plot)

    # -------------------------------------------------
    # MAIN DRAW
    # -------------------------------------------------
    def reload_plot(self):
        mode = self.cmbMode.currentText()
        hits, stats = collect_ray_hits_and_stats(None if mode == "all" else "final")

        filter_spec = self.filterPanel.get_filter_spec()
        plane = self.cmbPlane.currentText()
        flip2d = self.chkFlip.isChecked()

        # -------- 2D --------
        self.fig2d.clear()
        ax = self.fig2d.add_subplot(111)

        emitters, objects, bounces = compute_domains_for_legend(hits, filter_spec)
        mixer = ColorMixer(bounces)
        marker_map = {e: "o" for e in emitters}

        draw_points(ax, hits, filter_spec, plane, flip2d, mixer, marker_map)

        if self.chkBlobs.isChecked():
            draw_blobs_2d(ax, hits, filter_spec, plane, flip2d, mixer, self.chkSmooth.isChecked())

        if self.chkCentroids.isChecked():
            draw_centroids(ax, stats, filter_spec, plane, flip2d)

        build_legends(ax, emitters, bounces, marker_map, mixer, hits)

        if self.chkEqual.isChecked():
            ax.set_aspect("equal")
        if self.chkGrid.isChecked():
            ax.grid(True)

        self.canvas2d.draw_idle()

        # -------- 3D --------
        if self.chk3D.isChecked():
            self._draw_3d_plot(hits, filter_spec)

        self.lblStatus.setText(f"Hits: {len(hits)} | Emitters: {len(emitters)} | Objects: {len(objects)}")

    # -------------------------------------------------
    def _draw_3d_plot(self, hits, filter_spec):
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")

        hits_by_object = {}

        for h in hits:
            if h["emitter_id"] not in filter_spec["emitters"]:
                continue
            if h["object"] not in filter_spec["objects"]:
                continue
            hits_by_object.setdefault(h["object"], []).append(h)

        cmap = matplotlib.cm.get_cmap("tab10")

        for i, (obj, obj_hits) in enumerate(sorted(hits_by_object.items())):
            xs, ys, zs = zip(*(h["point"] for h in obj_hits))
            ax.scatter(xs, ys, zs, color=cmap(i), s=40, depthshade=True, label=obj)

        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        ax.legend(title="Objects")

        self.canvas3d.draw_idle()

    # -------------------------------------------------
    def closeEvent(self, event):
        OBARayManager().remove_listener(self.on_rays_updated)
        super().closeEvent(event)


# -------------------------------------------------
def ShowClusterPlotDialog():
    dlg = ClusterPlotDialog()
    dlg.show()
    Gui._cluster_plot_dialog = dlg
    return dlg
