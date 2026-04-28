# -*- coding: utf-8 -*-
# batch_runner.py

import json
import math
import time
import FreeCAD as App
from PySide import QtGui
import numpy as np

from oba_rayengine.oba_ray_core import OBARayManager
from .scan_db import HitsDB  # behålls som dummy / framtida


PRINT_DEBUGG = False


# ============================================================
# Math helpers
# ============================================================
def rotate(x, y, z, axis, angle_rad):
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    axis = axis.upper()

    if axis == "X":
        return (x, y * c - z * s, y * s + z * c)
    elif axis == "Y":
        return (x * c + z * s, y, -x * s + z * c)
    else:  # Z
        return (x * c - y * s, x * s + y * c, z)


def fmt_time(sec):
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ============================================================
# DUMMY DB HOOK (INTENTIONALLY NO-OP)
# ============================================================
def record_step_result_dummy(batch, step, offset):
    """
    Placeholder for future persistence.
    Currently NO-OP by design.

    offset = (dx, dy, dz) is the ONLY meaningful coordinate.
    """
    # Example future hook:
    # db.write_hit(batch.GroupId, step.Id, dx, dy, dz, stats)
    return


# ============================================================
# MAIN RUN FUNCTION
# ============================================================


# ----------------------------------------------------------
# Placement snapshot / restore
# ----------------------------------------------------------


def run_steps_for_batch(batch, prog_bar, status_lbl, pump_events_func, stop_flag_func):
    """
    Kör batch‑steg, samlar ray‑hits och skriver energibokföring till DB.
    """

    App.Console.PrintLog("▶ Starting batch run\n")

    import json, math, time
    from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats
    from .scan_db import HitsDB

    doc = batch.Document
    db = HitsDB()

    # ----------------------------------------------------------
    # Find OBARayConfig
    # ----------------------------------------------------------
    collector = None
    for obj in doc.Objects:
        if hasattr(obj, "Proxy") and obj.Proxy and obj.Proxy.__class__.__name__ == "OBARayConfig":
            collector = obj
            break

    if collector is None:
        status_lbl.setText("No OBARayConfig – aborting")
        App.Console.PrintError("❌ OBARayConfig missing\n")
        return

    # Disable debounce for performance
    try:
        collector.DisableDebounce = True
        App.Console.PrintLog("✅ RayCollector.DisableDebounce = True\n")
    except Exception:
        App.Console.PrintError("⚠️ Could not set DisableDebounce\n")

    # ----------------------------------------------------------
    # Collect active steps
    # ----------------------------------------------------------
    steps = [s for s in batch.Group if s.TypeId.startswith("App::FeaturePython") and getattr(s, "Active", True)]

    parsed_steps = []
    total_iters = 0

    for step in steps:
        try:
            data = json.loads(step.DataJSON or "{}")
        except Exception:
            data = {}

        A = max(1, int(data.get("angle", 5)))
        rf = float(data.get("rf", 0.0))
        rt = float(data.get("rt", 0.4))
        R = max(1, int(data.get("rs", 4)))

        iters = A * R - (A - 1) if rf == 0 else A * R
        total_iters += iters
        parsed_steps.append((step, data, A, rf, rt, R))

    prog_bar.setRange(0, total_iters)
    prog_bar.setValue(0)

    # ----------------------------------------------------------
    # Label → Name map
    # ----------------------------------------------------------
    label_to_name = {obj.Label: obj.Name for obj in doc.Objects}

    # ----------------------------------------------------------
    # Snapshot initial placements
    # ----------------------------------------------------------
    global_initial_positions = {}

    for step, data, *_ in parsed_steps:
        for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
            if not lbl or lbl == "none":
                continue
            obj = doc.getObject(label_to_name.get(lbl, ""))
            if obj and lbl not in global_initial_positions:
                global_initial_positions[lbl] = obj.Placement.Base

    # ----------------------------------------------------------
    # RUN
    # ----------------------------------------------------------
    start_time = time.time()
    done_iters = 0
    last_ui_update = 0.0
    UI_UPDATE_INTERVAL = 0.4

    try:
        for step, data, A, rf, rt, R in parsed_steps:
            if stop_flag_func():
                break

            plan = data.get("plan", "XY")
            targets = [t for t in (data.get("move"), data.get("move1"), data.get("move2")) if t and t != "none"]

            rot_axis = data.get("rotAxis", "X")
            rot_angle_rad = math.radians(float(data.get("rotAngle", 0.0)))

            initial_positions = {lbl: global_initial_positions[lbl] for lbl in targets if lbl in global_initial_positions}

            r_step = 0 if R <= 1 else (rt - rf) / float(R - 1)

            doc.openTransaction(f"Run {step.Label}")

            for ri in range(R):
                if stop_flag_func():
                    break

                radius = rf + r_step * ri
                ai_range = range(1) if (ri == 0 and abs(radius) < 1e-12) else range(A)

                for ai in ai_range:
                    if stop_flag_func():
                        break

                    pump_events_func()

                    ang = (2.0 * math.pi / A) * ai
                    dx = radius * math.cos(ang)
                    dy = radius * math.sin(ang)
                    dz = 0.0

                    if plan == "XZ":
                        dz, dy = dy, 0.0
                    elif plan == "YZ":
                        dx, dy, dz = 0.0, dx, dy

                    from .batch_runner import rotate

                    dx, dy, dz = rotate(dx, dy, dz, rot_axis, rot_angle_rad)

                    # ----------------------------------------------
                    # Move objects
                    # ----------------------------------------------
                    for lbl in targets:
                        obj = doc.getObject(label_to_name.get(lbl, ""))
                        base0 = initial_positions.get(lbl)
                        if not obj or not base0:
                            continue

                        obj.Placement.Base = App.Vector(
                            base0.x + dx,
                            base0.y + dy,
                            base0.z + dz,
                        )

                    # ----------------------------------------------
                    # ANALYSIS → DB
                    # ----------------------------------------------
                    hits, _stats = collect_ray_hits_and_stats(mode="final")
                    doc_name = f"{doc.Name}_{batch.Label}_{step.Id}"

                    # (target, emitter) → accumulator
                    accum = {}

                    for hit in hits:
                        target = hit.get("object")
                        if not target:
                            continue

                        obj = doc.getObject(target)
                        if not obj:
                            continue

                        optical_type = getattr(obj, "OpticalType", "UNKNOWN")
                        emitter = hit.get("emitter_id") or "__UNKNOWN__"

                        key = (target, emitter)

                        if key not in accum:
                            accum[key] = {
                                "count": 0,
                                "power_in": 0.0,
                                "power_out": 0.0,
                                "absorbed_power": 0.0,
                                "optical_type": optical_type,
                            }

                        accum[key]["count"] += 1
                        accum[key]["power_in"] += hit.get("power_in") or 0.0
                        accum[key]["power_out"] += hit.get("power_out") or 0.0
                        accum[key]["absorbed_power"] += hit.get("absorbed_power") or 0.0

                    # ----------------------------------------------
                    # Write DB rows (per emitter + ALL)
                    # ----------------------------------------------
                    rows = []

                    for (target, emitter), info in accum.items():
                        rows.append(
                            (
                                doc_name,
                                target,
                                emitter,
                                info["optical_type"],
                                dx,
                                dy,
                                dz,
                                info["count"],
                                info["power_in"],
                                info["power_out"],
                                info["absorbed_power"],
                            )
                        )

                        rows.append(
                            (
                                doc_name,
                                target,
                                "__ALL__",
                                info["optical_type"],
                                dx,
                                dy,
                                dz,
                                info["count"],
                                info["power_in"],
                                info["power_out"],
                                info["absorbed_power"],
                            )
                        )

                    if rows:
                        db.write_hits_batch(rows)
                        db.commit()

                    # ----------------------------------------------
                    # UI / ETA
                    # ----------------------------------------------
                    done_iters += 1
                    now = time.time()

                    if now - last_ui_update > UI_UPDATE_INTERVAL:
                        last_ui_update = now
                        prog_bar.setValue(done_iters)

                        elapsed = now - start_time
                        speed = done_iters / elapsed if elapsed > 0 else 0
                        rem = (total_iters - done_iters) / speed if speed > 0 else 0

                        status_lbl.setText(f"{step.Id} | {done_iters}/{total_iters} | " f"⏱ {int(elapsed)} s / ⏳ {int(rem)} s")
                        pump_events_func()

            doc.commitTransaction()
            doc.recompute()

    finally:
        # ------------------------------------------------------
        # Restore initial placements
        # ------------------------------------------------------
        doc.openTransaction("Restore positions")

        for lbl, base in global_initial_positions.items():
            obj = doc.getObject(label_to_name.get(lbl, ""))
            if obj:
                obj.Placement.Base = base

        try:
            collector.DisableDebounce = False
            App.Console.PrintLog("✅ RayCollector.DisableDebounce restored\n")
        except Exception:
            App.Console.PrintError("⚠️ Could not restore DisableDebounce\n")

        doc.commitTransaction()
        doc.recompute()

        status_lbl.setText("Stopped" if stop_flag_func() else "Done")


def run_steps_for_batch_old(batch, prog_bar, status_lbl, pump_events_func, stop_flag_func):

    App.Console.PrintLog("▶ Starting batch run\n")

    import json, math, time
    from raytracer.oba_ray import OBARayManager
    from .scan_db import HitsDB
    from raytracer.oba_ray_analyser import collect_ray_hits_and_stats

    doc = batch.Document
    db = HitsDB()

    # ----------------------------------------------------------
    # Find OBARayConfig
    # ----------------------------------------------------------
    collector = None
    for obj in doc.Objects:
        if hasattr(obj, "Proxy") and obj.Proxy and obj.Proxy.__class__.__name__ == "OBARayConfig":
            collector = obj
            break

    if collector is None:
        status_lbl.setText("No OBARayConfig – aborting")
        App.Console.PrintError("❌ OBARayConfig missing\n")
        return

    # Disable debounce for performance
    try:
        collector.DisableDebounce = True
        App.Console.PrintLog("✅ RayCollector.DisableDebounce = True\n")
    except Exception:
        App.Console.PrintError("⚠️ Could not set DisableDebounce\n")

    # ----------------------------------------------------------
    # Collect active steps
    # ----------------------------------------------------------
    steps = [s for s in batch.Group if s.TypeId.startswith("App::FeaturePython") and getattr(s, "Active", True)]

    parsed_steps = []
    total_iters = 0

    for step in steps:
        try:
            data = json.loads(step.DataJSON or "{}")
        except Exception:
            data = {}

        A = max(1, int(data.get("angle", 5)))
        rf = float(data.get("rf", 0.0))
        rt = float(data.get("rt", 0.4))
        R = max(1, int(data.get("rs", 4)))

        iters = A * R - (A - 1) if rf == 0 else A * R
        total_iters += iters

        parsed_steps.append((step, data, A, rf, rt, R))

    prog_bar.setRange(0, total_iters)
    prog_bar.setValue(0)

    # ----------------------------------------------------------
    # Label → Name map
    # ----------------------------------------------------------
    label_to_name = {obj.Label: obj.Name for obj in doc.Objects}

    # ----------------------------------------------------------
    # Snapshot initial placements
    # ----------------------------------------------------------
    global_initial_positions = {}

    for step, data, *_ in parsed_steps:
        for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
            if not lbl or lbl == "none":
                continue
            obj = doc.getObject(label_to_name.get(lbl, ""))
            if obj and lbl not in global_initial_positions:
                global_initial_positions[lbl] = obj.Placement.Base

    # ----------------------------------------------------------
    # RUN
    # ----------------------------------------------------------
    start_time = time.time()
    done_iters = 0
    last_ui_update = 0.0
    UI_UPDATE_INTERVAL = 0.4

    try:
        for step, data, A, rf, rt, R in parsed_steps:
            if stop_flag_func():
                break

            plan = data.get("plan", "XY")
            targets = [t for t in (data.get("move"), data.get("move1"), data.get("move2")) if t and t != "none"]

            rot_axis = data.get("rotAxis", "X")
            rot_angle_rad = math.radians(float(data.get("rotAngle", 0.0)))

            initial_positions = {lbl: global_initial_positions[lbl] for lbl in targets if lbl in global_initial_positions}

            r_step = 0 if R <= 1 else (rt - rf) / float(R - 1)

            doc.openTransaction(f"Run {step.Label}")

            for ri in range(R):
                if stop_flag_func():
                    break

                radius = rf + r_step * ri
                ai_range = range(1) if (ri == 0 and abs(radius) < 1e-12) else range(A)

                for ai in ai_range:
                    if stop_flag_func():
                        break

                    pump_events_func()

                    ang = (2.0 * math.pi / A) * ai
                    dx = radius * math.cos(ang)
                    dy = radius * math.sin(ang)
                    dz = 0.0

                    if plan == "XZ":
                        dz, dy = dy, 0.0
                    elif plan == "YZ":
                        dx, dy, dz = 0.0, dx, dy

                    # rotation
                    from .batch_runner import rotate

                    dx, dy, dz = rotate(dx, dy, dz, rot_axis, rot_angle_rad)

                    # ----------------------------------------------
                    # Move objects
                    # ----------------------------------------------
                    for lbl in targets:
                        obj = doc.getObject(label_to_name.get(lbl, ""))
                        base0 = initial_positions.get(lbl)
                        if not obj or not base0:
                            continue

                        obj.Placement.Base = App.Vector(
                            base0.x + dx,
                            base0.y + dy,
                            base0.z + dz,
                        )

                    # ----------------------------------------------
                    # ANALYSIS → DB (central punkt)
                    # ----------------------------------------------
                    hits, stats = collect_ray_hits_and_stats(mode="final")

                    doc_name = f"{doc.Name}_{batch.Label}_{step.Id}"
                    offset = (dx, dy, dz)

                    # Samla (OpticalType, Emitter) → count
                    accum = {}

                    for hit in hits:
                        target = hit.get("object")  # ← Mirror1, Lens3, Absorber01
                        if not target:
                            continue

                        obj = doc.getObject(target)
                        if not obj:
                            continue

                        optical_type = getattr(obj, "OpticalType", "UNKNOWN")
                        emitter = hit.get("emitter_id") or "__UNKNOWN__"

                        key = (target, emitter)

                        accum.setdefault(key, {"count": 0, "power": 0.0, "optical_type": optical_type})
                        accum[key]["count"] += 1
                        accum[key]["power"] += hit.get("power", 0.0)

                        # Skriv till DB: per emitter + ALL
                        # for (target, emitter), info in accum.items():
                        #     db.write_hit(doc_name, target_object=target, emitter_id=emitter, optical_type=info["optical_type"], x=dx, y=dy, z=dz, hits=info["count"])  # ← Mirror1  # ← Mirror
                        #     # ALL‑aggregering per objekt
                        #     db.write_hit(doc_name, target_object=target, emitter_id="__ALL__", optical_type=info["optical_type"], x=dx, y=dy, z=dz, hits=info["count"])

                        rows = []
                        for (target, emitter), info in accum.items():
                            rows.append((doc_name, target, emitter, info["optical_type"], dx, dy, dz, info["count"], info["power"]))
                            rows.append((doc_name, target, "__ALL__", info["optical_type"], dx, dy, dz, info["count"], info["power"]))
                        db.write_hits_batch(rows)
                        db.commit()

                    # ----------------------------------------------
                    # UI / ETA
                    # ----------------------------------------------
                    done_iters += 1
                    now = time.time()

                    if now - last_ui_update > UI_UPDATE_INTERVAL:
                        last_ui_update = now
                        prog_bar.setValue(done_iters)

                        elapsed = now - start_time
                        speed = done_iters / elapsed if elapsed > 0 else 0
                        rem = (total_iters - done_iters) / speed if speed > 0 else 0

                        status_lbl.setText(f"{step.Id} | {done_iters}/{total_iters} | " f"⏱ {int(elapsed)} s / ⏳ {int(rem)} s")
                        pump_events_func()

            doc.commitTransaction()
            doc.recompute()

    finally:
        # ------------------------------------------------------
        # Restore initial placements
        # ------------------------------------------------------
        doc.openTransaction("Restore positions")

        for lbl, base in global_initial_positions.items():
            obj = doc.getObject(label_to_name.get(lbl, ""))
            if obj:
                obj.Placement.Base = base

        try:
            collector.DisableDebounce = False
            App.Console.PrintLog("✅ RayConfig.DisableDebounce restored\n")
        except Exception:
            App.Console.PrintError("⚠️ Could not restore DisableDebounce\n")

        doc.commitTransaction()
        doc.recompute()

        status_lbl.setText("Stopped" if stop_flag_func() else "Done")
