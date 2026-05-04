# -*- coding: utf-8 -*-
# oba_ray_analyser.py

"""
Ray analysis built on OBARayManager singleton.

- En hit = en faktisk geometrisk träff
- power_out = kvarvarande transportenergi efter interaktionen
- power_in = inkommande energi till ytan
- absorbed_power = energi som absorberades i träffen
"""

import math
from .oba_ray_core import OBARayManager


# ============================================================
# 1. CORE: collect hits + groups
# ============================================================


def collect_ray_hits_and_stats(
    mode="final",
    *,
    min_bounce=None,
    max_bounce=None,
    hit_selection="all",  # "all" | "incoming" | "outgoing"
):
    """
    Returnerar hit-data och kluster-statistik.

    hit_selection:
        "incoming"  -> endast första träffen per ray
        "outgoing"  -> endast sista träffen per ray
        "all"       -> första + sista träffen per ray (DEFAULT, rekommenderat)
    """

    rm = OBARayManager()
    hits = []
    groups = {}

    for ray in rm.get_all_rays():
        if mode and ray.mode != mode:
            continue

        # --------------------------------------------------
        # Exakt strålgång
        # --------------------------------------------------
        path_signature = tuple((h["object_name"], h["face_id"]) for h in ray.history if isinstance(h, dict) and "hit_point" in h)

        ray_points = []
        ray_bounces = []
        ray_power_out = 0.0
        ray_power_in = 0.0
        ray_absorbed = 0.0

        for h in ray.history:
            if not isinstance(h, dict):
                continue
            if "hit_point" not in h:
                continue

            bounce = h.get("bounce_index", 0)

            if min_bounce is not None and bounce < min_bounce:
                continue
            if max_bounce is not None and bounce > max_bounce:
                continue

            extra = h.get("extra", {})

            hit = {
                "ray_id": h.get("ray_id"),
                "parent_id": h.get("parent_id"),
                "path_id": getattr(ray, "path_id", ray.id),
                "path_signature": path_signature,
                "emitter_id": ray.emitter_id,
                "object": h.get("object_name"),
                "face": h.get("face_id"),
                "prev_face": ray.prev_hit_face,
                "bounce": bounce,
                "point": h.get("hit_point"),
                "power_out": h.get("power_out", 0.0),
                "power_in": extra.get("power_in", 0.0),
                "absorbed_power": extra.get("absorbed_power", 0.0),
            }

            hits.append(hit)

            ray_points.append(hit["point"])
            ray_bounces.append(bounce)

            ray_power_out += hit["power_out"]
            if hit["power_in"] is not None:
                ray_power_in += hit["power_in"]
            ray_absorbed += hit["absorbed_power"]

        if not ray_points:
            continue

        # --------------------------------------------------
        # Välj REPRESENTATIVA punkter per ray
        # --------------------------------------------------
        if hit_selection == "incoming":
            selected_points = [ray_points[0]]

        elif hit_selection == "outgoing":
            selected_points = [ray_points[-1]]

        else:  # "all" = incoming + outgoing
            if len(ray_points) == 1:
                selected_points = [ray_points[0]]
            else:
                selected_points = [ray_points[0], ray_points[-1]]

        key = (ray.emitter_id, path_signature)

        if key not in groups:
            groups[key] = {
                "points": [],
                "bounces": [],
                "power_in_sum": 0.0,
                "power_out_sum": 0.0,
                "absorbed_power_sum": 0.0,
            }

        g = groups[key]
        g["points"].extend(selected_points)
        g["bounces"].extend(ray_bounces)
        g["power_out_sum"] += ray_power_out
        g["power_in_sum"] += ray_power_in
        g["absorbed_power_sum"] += ray_absorbed

    # --------------------------------------------------
    # FINALIZE STATISTIK
    # --------------------------------------------------
    stats = {}

    for key, g in groups.items():
        pts = g["points"]
        if not pts:
            continue

        n = len(pts)
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        cz = sum(p[2] for p in pts) / n

        stats[key] = {
            "centroid": (cx, cy, cz),
            "count": n,
            "power_in": g["power_in_sum"],
            "power_out": g["power_out_sum"],
            "absorbed_power": g["absorbed_power_sum"],
            "min_bounce": min(g["bounces"]),
            "max_bounce": max(g["bounces"]),
            "mean_bounce": sum(g["bounces"]) / len(g["bounces"]),
            "hit_points": pts,
        }

    return hits, stats


def collect_ray_hits_and_stats_old(mode="final"):
    """
    Samlar alla träffar från OBARayManager och returnerar:

    - hits  : platt lista (en dict per träff)
    - stats : grupperad statistik per (object, face, prev_face, bounce, emitter)

    :param mode: "final", "preview" eller None (alla)
    """
    rm = OBARayManager()

    hits = []
    groups = {}

    for ray in rm.get_all_rays():
        if mode and ray.mode != mode:
            continue

        for h in ray.history:
            if not isinstance(h, dict):
                continue
            if "hit_point" not in h:
                continue

            extra = h.get("extra", {})

            # --------------------------------------------------
            # HIT RECORD (platt, en träff)
            # --------------------------------------------------
            hit = {
                # Identitet & relation
                "ray_id": h.get("ray_id"),
                "parent_id": h.get("parent_id"),
                "path_id": getattr(ray, "path_id", ray.id),  #
                "emitter_id": ray.emitter_id,
                # Geometri
                "object": h.get("object_name"),
                "face": h.get("face_id"),
                "prev_face": ray.prev_hit_face,
                "bounce": h.get("bounce_index", 0),
                "point": h.get("hit_point"),
                # Energi (tydlig semantik)
                "power_out": h.get("power", 0.0),
                "power_in": extra.get("power_in"),
                "absorbed_power": extra.get("absorbed_power", 0.0),
            }

            hits.append(hit)

            # --------------------------------------------------
            # GROUP KEY = vad som räknas som "samma träff-kluster"
            # --------------------------------------------------
            key = (
                hit["object"],
                hit["face"],
                hit["path_id"],  # 🔑
                hit["prev_face"],
                hit["bounce"],
                hit["emitter_id"],
            )

            if key not in groups:
                groups[key] = {
                    "points": [],
                    "power_out_sum": 0.0,
                    "power_in_sum": 0.0,
                    "absorbed_power_sum": 0.0,
                }

            g = groups[key]

            g["points"].append(hit["point"])
            g["power_out_sum"] += hit["power_out"]

            if hit["power_in"] is not None:
                g["power_in_sum"] += hit["power_in"]

            g["absorbed_power_sum"] += hit["absorbed_power"]

    # ============================================================
    # 2. FINALIZE: centroid + spread + energy sums
    # ============================================================

    stats = {}

    for key, g in groups.items():
        pts = g["points"]
        if not pts:
            continue

        n = len(pts)

        # --- centroid ---
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        cz = sum(p[2] for p in pts) / n

        # --- maximal geometrisk spridning (från gamla analysen) ---
        dx = [p[0] - cx for p in pts]
        dy = [p[1] - cy for p in pts]
        dz = [p[2] - cz for p in pts]

        radius_3d = max(math.sqrt(dx[i] ** 2 + dy[i] ** 2 + dz[i] ** 2) for i in range(n)) if n > 0 else 0.0

        stats[key] = {
            # Grund
            "centroid": (cx, cy, cz),
            "count": n,
            # Energi (ingen tolkning, bara bokföring)
            "power_out": g["power_out_sum"],
            "power_in": g["power_in_sum"],
            "absorbed_power": g["absorbed_power_sum"],
            # Geometrisk spridning
            "radius_3d": radius_3d,
            # skickar med orginal points utifall
            "hit_points": pts,
        }

    return hits, stats


# ============================================================
# 3. BACKWARD-FRIENDLY WRAPPER
# ============================================================


def analyze_rays(mode="final"):
    """
    Enkel wrapper som matchar gamla analyzers API-stil.

    :return: dict med:
        {
            "hits":  platt lista av träffar,
            "stats": grupperad statistik
        }
    """
    hits, stats = collect_ray_hits_and_stats(mode=mode)
    return {
        "hits": hits,
        "stats": stats,
    }


# ============================================================
# 4. DEBUG / CLI
# ============================================================

if __name__ == "__main__":
    result = analyze_rays(mode="final")

    print("Top clusters by hit count:\n")
    for gid, s in sorted(
        result["stats"].items(),
        key=lambda kv: kv[1]["count"],
        reverse=True,
    )[:10]:
        print(
            gid,
            "hits:",
            s["count"],
            "centroid:",
            tuple(round(c, 3) for c in s["centroid"]),
            "radius:",
            f"{s['radius_3d']:.3g}",
        )
