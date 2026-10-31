"""
Core "smart" logic for the Smart Waste Management & Prediction System prototype.

These are deliberately lightweight, explainable algorithms rather than trained
ML models -- appropriate for an academic prototype (see SRS 1.3 / 2.6: hardware
and model feeds may be simulated). Each function is documented so it can be
swapped for a real trained model / real routing API later without touching
the rest of the app.
"""
import math
import random
from datetime import datetime, date
from PIL import Image

WASTE_CATEGORIES = ["Plastic", "Wet/Organic", "Dry/Recyclable", "Construction Debris", "E-Waste", "Mixed"]


# ---------------------------------------------------------------------------
# 3.5 Waste Image Recognition (simulated AI classifier)
# ---------------------------------------------------------------------------
def classify_waste_image(image_path):
    """
    Heuristic 'AI' classifier: analyses the average colour + brightness of the
    uploaded photo and maps it to a plausible waste category with a confidence
    score. This stands in for a trained CNN in the prototype (SRS 3.5 / 2.6).
    Low-confidence results are flagged for human review, per SRS requirement 26.
    """
    try:
        img = Image.open(image_path).convert("RGB")
        img = img.resize((64, 64))
        pixels = list(img.getdata())
        n = len(pixels)
        r = sum(p[0] for p in pixels) / n
        g = sum(p[1] for p in pixels) / n
        b = sum(p[2] for p in pixels) / n
        brightness = (r + g + b) / 3

        # crude, explainable rules based on dominant colour / brightness
        if g > r and g > b and brightness < 140:
            waste_type, base_conf = "Wet/Organic", 0.78
        elif brightness > 190 and abs(r - g) < 25 and abs(g - b) < 25:
            waste_type, base_conf = "Dry/Recyclable", 0.66
        elif r > g and r > b:
            waste_type, base_conf = "Plastic", 0.72
        elif brightness < 90:
            waste_type, base_conf = "Construction Debris", 0.60
        else:
            waste_type, base_conf = "Mixed", 0.55

        # small pseudo-random jitter so repeated demo runs aren't identical
        confidence = max(0.35, min(0.97, base_conf + random.uniform(-0.08, 0.08)))
        severity = "High" if confidence > 0.8 else ("Medium" if confidence > 0.55 else "Low")
        needs_review = confidence < 0.6

        return {
            "waste_type": waste_type,
            "confidence": round(confidence * 100, 2),
            "severity": severity,
            "needs_review": needs_review,
        }
    except Exception:
        return {
            "waste_type": "Mixed",
            "confidence": 40.0,
            "severity": "Low",
            "needs_review": True,
        }


# ---------------------------------------------------------------------------
# 3.6 Waste Hotspot Prediction
# ---------------------------------------------------------------------------
def compute_ward_risk_scores(db):
    """
    Combines recent complaint frequency + average bin fill level per ward
    into a single 0-100 risk score (SRS 3.6, requirement 29-30).

    risk_score = 0.6 * normalised_complaint_pressure + 0.4 * normalised_bin_fill
    """
    wards = db.execute("SELECT ward_id, ward_name FROM ward").fetchall()
    results = []
    complaint_counts = {
        row["ward_id"]: row["c"]
        for row in db.execute(
            """SELECT ward_id, COUNT(*) as c FROM complaint
               WHERE ward_id IS NOT NULL AND status != 'Resolved'
               GROUP BY ward_id"""
        ).fetchall()
    }
    max_complaints = max(complaint_counts.values()) if complaint_counts else 1

    for w in wards:
        wid = w["ward_id"]
        avg_fill = db.execute(
            "SELECT AVG(fill_level) as a FROM smart_bin WHERE ward_id = ?", (wid,)
        ).fetchone()["a"] or 0
        complaints = complaint_counts.get(wid, 0)
        complaint_pressure = complaints / max_complaints if max_complaints else 0
        risk = round((0.6 * complaint_pressure + 0.4 * (avg_fill / 100)) * 100, 2)
        results.append({
            "ward_id": wid,
            "ward_name": w["ward_name"],
            "open_complaints": complaints,
            "avg_fill_level": round(avg_fill, 1),
            "risk_score": risk,
        })
    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results


def save_hotspot_predictions(db, model_version="v1.0-heuristic"):
    scores = compute_ward_risk_scores(db)
    today = date.today().isoformat()
    for s in scores:
        db.execute(
            """INSERT INTO hotspot_prediction (ward_id, location, risk_score, prediction_date, model_version)
               VALUES (?, ?, ?, ?, ?)""",
            (s["ward_id"], s["ward_name"], s["risk_score"], today, model_version),
        )
    db.commit()
    return scores


# ---------------------------------------------------------------------------
# 3.7 Route Optimization (nearest-neighbour heuristic)
# ---------------------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def optimize_route(start_lat, start_lon, stops):
    """
    Nearest-neighbour route sequencing (SRS 3.7, requirement 35).
    `stops` is a list of dicts with at least: id, latitude, longitude, priority.
    Returns the same dicts in visiting order, each tagged with route_order and
    the cumulative distance in km. Critical/High priority stops are given a
    small distance bonus so they are reached earlier when reasonably close.
    """
    PRIORITY_WEIGHT = {"Critical": 0.5, "High": 0.75, "Medium": 1.0, "Low": 1.25}
    remaining = list(stops)
    ordered = []
    cur_lat, cur_lon = start_lat, start_lon
    total_km = 0.0
    order = 1
    while remaining:
        best_idx, best_score, best_dist = None, None, None
        for i, s in enumerate(remaining):
            d = haversine_km(cur_lat, cur_lon, float(s["latitude"]), float(s["longitude"]))
            score = d * PRIORITY_WEIGHT.get(s.get("priority", "Medium"), 1.0)
            if best_score is None or score < best_score:
                best_score, best_idx, best_dist = score, i, d
        chosen = remaining.pop(best_idx)
        total_km += best_dist
        chosen["route_order"] = order
        chosen["leg_km"] = round(best_dist, 2)
        ordered.append(chosen)
        cur_lat, cur_lon = float(chosen["latitude"]), float(chosen["longitude"])
        order += 1
    return ordered, round(total_km, 2)


# ---------------------------------------------------------------------------
# 3.8 Illegal Dumping Detection
# ---------------------------------------------------------------------------
def detect_dumping_clusters(db, radius_km=0.3, repeat_threshold=3):
    """
    Flags locations with >= repeat_threshold open complaints within radius_km
    of each other (SRS 3.8, requirements 39-41): a simple spatial clustering
    pass suitable for a prototype (no external geo library required).
    """
    rows = db.execute(
        """SELECT complaint_id, latitude, longitude, ward_id, created_at FROM complaint
           WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND status != 'Resolved'"""
    ).fetchall()
    points = [dict(r) for r in rows]
    clusters = []
    used = set()
    for i, p in enumerate(points):
        if p["complaint_id"] in used:
            continue
        group = [p]
        for j, q in enumerate(points):
            if i == j or q["complaint_id"] in used:
                continue
            if haversine_km(p["latitude"], p["longitude"], q["latitude"], q["longitude"]) <= radius_km:
                group.append(q)
        if len(group) >= repeat_threshold:
            for g in group:
                used.add(g["complaint_id"])
            avg_lat = sum(g["latitude"] for g in group) / len(group)
            avg_lon = sum(g["longitude"] for g in group) / len(group)
            clusters.append({
                "count": len(group),
                "latitude": avg_lat,
                "longitude": avg_lon,
                "complaint_ids": [g["complaint_id"] for g in group],
                "ward_id": group[0]["ward_id"],
            })
    return clusters
