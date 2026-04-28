import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore

from .oba_ray_core import OBARayManager


# ============================================================
#  HUVUDFUNKTION
# ============================================================


def OBA_ShowRayHistory():
    mgr = OBARayManager()
    rays = mgr.rays

    if not rays:
        QtWidgets.QMessageBox.information(None, "Ray Debug", "Inga rays hittades i OBARayManager().")
        return

    dlg = RayHistoryDialog(rays)
    dlg.exec_()


# ============================================================
#  DIALOG
# ============================================================


class RayHistoryDialog(QtWidgets.QDialog):
    def __init__(self, rays):
        super().__init__()
        self.setWindowTitle("Ray History Debug")
        self.resize(1000, 600)

        self.rays = rays
        self.all_bounces = self._collect_all_bounces()

        vbox = QtWidgets.QVBoxLayout(self)

        # ---- Combobox ----
        self.cmb = QtWidgets.QComboBox()
        self.cmb.addItem("Alla studsar", -1)
        for bc in sorted(self.all_bounces):
            self.cmb.addItem(f"Bounce {bc}", bc)
        self.cmb.currentIndexChanged.connect(self.update_table)
        vbox.addWidget(self.cmb)

        # ---- Tabell ----
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels(
            [
                "Ray#",
                "Bounce#",
                "Object Name",
                "Optical Type",
                "FaceID",
                "Hit (x,y,z)",
                "Incoming",
                "Outgoing",
                "Power In",
                "Power Out",
                "Absorbed Power",
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)

        vbox.addWidget(self.table)

        self.update_table()

    # --------------------------------------------------------

    def _collect_all_bounces(self):
        s = set()
        for r in self.rays:
            for h in r.history:
                if isinstance(h, dict):
                    s.add(h.get("bounce_index", 0))
        return s

    # --------------------------------------------------------

    def update_table(self):
        bc_filter = self.cmb.currentData()

        rows = []
        for idx, ray in enumerate(self.rays):
            for h in ray.history:
                if not isinstance(h, dict):
                    continue
                if bc_filter != -1 and h.get("bounce_index") != bc_filter:
                    continue
                rows.append((idx, h))

        self.table.setRowCount(len(rows))

        for r_idx, (ray_id, h) in enumerate(rows):

            def setcol(col, text):
                item = QtWidgets.QTableWidgetItem(str(text))
                self.table.setItem(r_idx, col, item)

            p = h["hit_point"]
            inc = h["incoming_dir"]
            out = h["outgoing_dir"]

            extra = h.get("extra", {})
            power_in = extra.get("power_in")
            power_out = h.get("power", 0.0)
            absorbed_power = extra.get("absorbed_power", 0.0)

            setcol(0, ray_id)
            setcol(1, h["bounce_index"])
            setcol(2, h.get("object_name"))
            setcol(3, h.get("optical_type"))
            setcol(4, h.get("face_id"))

            setcol(5, f"({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f})")
            setcol(6, f"({inc[0]:.3f}, {inc[1]:.3f}, {inc[2]:.3f})")
            setcol(7, f"({out[0]:.3f}, {out[1]:.3f}, {out[2]:.3f})")

            # ---- Energi ----
            setcol(8, f"{power_in:.6f}" if power_in is not None else "-")
            setcol(9, f"{power_out:.6f}")
            setcol(10, f"{absorbed_power:.6f}")


# ============================================================
#  COMMAND
# ============================================================


class _CmdShowRayHistory:
    def GetResources(self):
        return {"MenuText": "Visa Ray-Historik", "ToolTip": "Visar full historik för alla OBARay-objekt", "Pixmap": ""}

    def Activated(self):
        OBA_ShowRayHistory()


if "OBA_ShowRayHistory" not in Gui.listCommands():
    Gui.addCommand("OBA_ShowRayHistory", _CmdShowRayHistory())
