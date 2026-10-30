"""CityMemory engine: link complaints to assets, build each asset's memory, predict, rank.

Everything here is plain Python and explainable; no external service is needed.
"""
import math
import os
from datetime import date, timedelta
from statistics import median

from . import text as tx

# ---- matching -------------------------------------------------------------
WEIGHTS = {"location": 0.40, "meaning": 0.35, "type": 0.15, "time": 0.10}
AUTO_LINK, REVIEW = 0.75, 0.50
SEARCH_RADIUS_M = 300
SAME_FAILURE_DAYS = 21          # complaints this close together describe the same failure

DEPARTMENTS = {"drainage": "Stormwater Drains", "road": "Roads", "streetlight": "Electrical (Streetlights)",
               "footpath": "Roads", "toilet": "Health & Sanitation"}
SAFETY = {"hospital": 0.9, "school": 0.8, "bus_stop": 0.6, "market": 0.5, None: 0.3}

# Contractor guarantee (defect liability) when a repair record does not say: patch 3 months, permanent 2 years
WARRANTY_DEFAULT = {"patch": 3, "permanent": 24}
# Typical one-time cost of a permanent fix, used only when no permanent fix has been done yet (an estimate)
PERMANENT_ESTIMATE = {"drainage": 650000, "road": 1050000, "streetlight": 175000, "footpath": 275000, "toilet": 350000}


def months_later(x: date, months: int) -> date:
    return x + timedelta(days=round(months * 30.44))


def today() -> date:
    """Real date, or a fixed demo date from CITYMEMORY_TODAY=YYYY-MM-DD (keeps the demo numbers stable)."""
    fixed = os.getenv("CITYMEMORY_TODAY")
    return date.fromisoformat(fixed) if fixed else date.today()


def d(s) -> date:
    return s if isinstance(s, date) else date.fromisoformat(s)


def distance_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def location_score(dist):
    if dist <= 40:
        return 1.0
    if dist >= 200:
        return 0.0
    return round(1 - (dist - 40) / 160, 3)


def time_score(days_since_last):
    if days_since_last is None:
        return 0.3
    if days_since_last <= 120:
        return 1.0
    if days_since_last >= 730:
        return 0.3
    return round(1 - 0.7 * (days_since_last - 120) / 610, 3)


def match(db, ctext, lat, lng, ctype, on_date=None):
    """Score every nearby asset. Returns (decision, ranked candidates)."""
    on_date = on_date or today()
    candidates = []
    for a in db["assets"]:
        dist = distance_m(lat, lng, a["lat"], a["lng"])
        if dist > SEARCH_RADIUS_M:
            continue
        past = [c for c in db["complaints"] if c["asset_id"] == a["id"]]
        texts = [c["text"] for c in past] + [a["name"]]
        sims = sorted((tx.similarity(ctext, t) for t in texts), reverse=True)
        meaning = min(1.0, (sims[0] if sims else 0) / 0.6)
        if ctype is None:
            type_s = 0.4
        else:
            type_s = 1.0 if ctype == a["type"] else 0.0
        last = last_event_date(db, a["id"])
        days = (on_date - last).days if last else None
        sig = {"location": location_score(dist), "meaning": round(meaning, 3), "type": type_s,
               "time": time_score(days)}
        score = sum(WEIGHTS[k] * v for k, v in sig.items())
        candidates.append({"asset_id": a["id"], "name": a["name"], "type": a["type"],
                           "distance_m": round(dist), "signals": sig, "score": round(score, 3)})
    candidates.sort(key=lambda c: c["score"], reverse=True)
    best = candidates[0]["score"] if candidates else 0
    decision = "auto" if best >= AUTO_LINK else ("review" if best >= REVIEW else "new")
    return decision, candidates[:3]


def last_event_date(db, asset_id):
    dates = [d(c["date"]) for c in db["complaints"] if c["asset_id"] == asset_id]
    dates += [d(r["date"]) for r in db["repairs"] if r["asset_id"] == asset_id]
    return max(dates) if dates else None


# ---- memory: failures, repairs, patterns ---------------------------------
def in_season(x: date) -> bool:
    """Bengaluru's rainy season: pre-monsoon showers from mid-May through October."""
    return (x.month == 5 and x.day >= 15) or 6 <= x.month <= 10


def next_season_start(x: date) -> date:
    y = x.year if x < date(x.year, 6, 1) else x.year + 1
    return date(y, 6, 1)


def failure_events(complaints):
    """Group complaints that are close in time into one failure."""
    events = []
    for c in sorted(complaints, key=lambda c: c["date"]):
        cd = d(c["date"])
        if events and (cd - events[-1]["last"]).days <= SAME_FAILURE_DAYS:
            events[-1]["complaint_ids"].append(c["id"])
            events[-1]["last"] = cd
        else:
            events.append({"start": cd, "last": cd, "complaint_ids": [c["id"]]})
    return events


def analyze(db, asset_id, on_date=None):
    on_date = on_date or today()
    comps = sorted([c for c in db["complaints"] if c["asset_id"] == asset_id], key=lambda c: c["date"])
    reps = sorted([r for r in db["repairs"] if r["asset_id"] == asset_id], key=lambda r: r["date"])
    events = failure_events(comps)

    # how long did each repair last?
    refail = []
    for r in reps:
        rd = d(r["date"])
        nxt = next((e["start"] for e in events if e["start"] > rd), None)
        wm = r.get("warranty_months") or WARRANTY_DEFAULT.get(r["kind"], 6)
        until = months_later(rd, wm)
        refail.append({"repair_id": r["id"], "date": r["date"], "cost": r["cost"], "kind": r["kind"],
                       "lasted_days": (nxt - rd).days if nxt else None,
                       "still_holding_days": None if nxt else (on_date - rd).days,
                       "contractor": r.get("contractor") or "Not recorded", "warranty_months": wm,
                       "warranty_until": until.isoformat(),
                       "failed_in_warranty": nxt is not None and nxt <= until,
                       "warranty_days_left": (until - on_date).days if (nxt is None and until >= on_date) else None})
    held = [x["lasted_days"] for x in refail if x["lasted_days"] is not None]
    repeat_spend = sum(x["cost"] for x in refail if x["lasted_days"] is not None and x["lasted_days"] <= 365)

    gaps = [(events[i]["start"] - events[i - 1]["start"]).days for i in range(1, len(events))]
    seasonal_share = (sum(in_season(e["start"]) for e in events) / len(events)) if events else 0.0

    # a permanent fix with no failure after it = fixed
    perm = [r for r in reps if r["kind"] == "permanent"]
    fixed_on = None
    if perm:
        pd_ = d(perm[-1]["date"])
        if not any(e["start"] > pd_ for e in events):
            fixed_on = pd_

    last_rep = d(reps[-1]["date"]) if reps else None
    out = {
        "complaints": len(comps),
        "failures": len(events),
        "events": [{"start": e["start"].isoformat(), "complaint_ids": e["complaint_ids"]} for e in events],
        "repairs": len(reps),
        "total_cost": sum(r["cost"] for r in reps),
        "repeat_spend": repeat_spend,
        "repairs_detail": refail,
        "shortest_lasted_days": min(held) if held else None,
        "median_gap_days": round(median(gaps)) if gaps else None,
        "seasonal_share": round(seasonal_share, 2),
        "last_repair": last_rep.isoformat() if last_rep else None,
        "days_since_last_repair": (on_date - last_rep).days if last_rep else None,
        "fixed_on": fixed_on.isoformat() if fixed_on else None,
    }
    out["prediction"] = predict(out, events, on_date)

    # contractor guarantee: repairs that failed while still under warranty can be recovered
    in_w = [x for x in refail if x["failed_in_warranty"]]
    active = next((x for x in reversed(refail) if x["warranty_days_left"] is not None), None)
    out["warranty"] = {"recoverable": sum(x["cost"] for x in in_w), "failed_in_warranty": len(in_w),
                       "contractors": sorted({x["contractor"] for x in in_w}),
                       "active": {k: active[k] for k in ("repair_id", "contractor", "warranty_until",
                                                         "warranty_days_left", "kind")} if active else None}

    # money: what patching costs each year, against a one-time permanent fix (an estimate)
    out["money"] = None
    asset = next((a for a in db["assets"] if a["id"] == asset_id), None)
    patch_cost = sum(r["cost"] for r in reps if r["kind"] == "patch")
    starts = [e["start"] for e in events] + [d(r["date"]) for r in reps]
    if asset and patch_cost and starts:
        perm_d = d(perm[-1]["date"]) if perm else None
        years = max(0.5, ((perm_d or on_date) - min(starts)).days / 365)
        per_year = patch_cost / years
        perm_cost = perm[-1]["cost"] if perm else PERMANENT_ESTIMATE.get(asset["type"], 500000)
        out["money"] = {"patch_spent": patch_cost, "patch_per_year": round(per_year),
                        "permanent_cost": perm_cost, "permanent_is_estimate": not perm,
                        "payback_years": round(perm_cost / per_year, 1),
                        "ten_year_saving": round(per_year * 10 - perm_cost),
                        "saved_so_far": round(per_year * (on_date - perm_d).days / 365) if perm_d else None}
    return out


def predict(a, events, on_date):
    if a["fixed_on"]:
        return {"date": None, "label": f"Permanent fix on {fmt(d(a['fixed_on']))}, no failure since",
                "at_risk": False}
    if len(events) < 3 or not a["median_gap_days"]:
        return {"date": None, "label": "Not enough history yet (needs 3 or more failures)", "at_risk": False}
    seasonal = a["seasonal_share"] >= 0.6
    nxt = events[-1]["start"] + timedelta(days=a["median_gap_days"])
    why = f"last failure + usual gap of about {round(a['median_gap_days'] / 30)} month(s)"
    if seasonal and not in_season(nxt):
        nxt = next_season_start(nxt)
        why += ", moved to the start of the rainy season because it fails mostly in the monsoon"
    if nxt <= on_date:
        if seasonal and not in_season(on_date):
            nxt = next_season_start(on_date)
            label = f"Likely at monsoon onset, {nxt.strftime('%B %Y')}"
        else:
            return {"date": on_date.isoformat(), "label": "At risk now: the usual gap has already passed",
                    "why": why, "at_risk": True}
    else:
        label = (f"Likely at monsoon onset, {nxt.strftime('%B %Y')}" if seasonal and nxt.month == 6 and nxt.day == 1
                 else f"Likely around {nxt.strftime('%B %Y')}")
    before_next_monsoon = nxt <= next_season_start(on_date) + timedelta(days=60)
    return {"date": nxt.isoformat(), "label": label, "why": why, "at_risk": before_next_monsoon}


def fmt(x: date) -> str:
    return x.strftime("%d %b %Y")


# ---- ranking ---------------------------------------------------------------
def priority(asset, an):
    recurrence = 1 - math.exp(-an["failures"] / 2.6)
    cost = min(1.0, an["total_cost"] / 500000)
    safety = min(1.0, SAFETY.get(asset.get("near"), 0.3) + (0.1 if asset.get("road_class") == "main" else 0))
    impact = min(1.0, an["complaints"] / 13)
    factors = {"recurrence": round(recurrence, 2), "cost": round(cost, 2),
               "safety": round(safety, 2), "impact": round(impact, 2)}
    w = {"recurrence": 0.35, "cost": 0.25, "safety": 0.25, "impact": 0.15}
    score = sum(w[k] * v for k, v in factors.items())
    if an["fixed_on"]:
        score *= 0.3
    score = round(score, 2)
    if an["fixed_on"]:
        band = "Fixed - monitoring"
    elif asset.get("status") == "fix_planned":
        band = "Permanent fix planned"
    elif score >= 0.7:
        band = "High - fix permanently"
    elif score >= 0.45:
        band = "Medium - inspect soon"
    else:
        band = "Low - routine"
    return {"score": score, "band": band, "factors": factors, "reasons": reasons(asset, an)}


def reasons(asset, an):
    out = []
    if an["failures"] >= 2:
        out.append(f"Failed {an['failures']} times")
    if an["total_cost"]:
        out.append(f"{rupees(an['total_cost'])} spent")
    if an["shortest_lasted_days"] is not None and an["shortest_lasted_days"] <= 90:
        out.append(f"A repair lasted only {an['shortest_lasted_days']} days")
    if an["seasonal_share"] >= 0.6 and an["failures"] >= 3:
        out.append("Fails every monsoon")
    near = {"hospital": "Near a hospital", "school": "Near a school", "bus_stop": "At a bus stop",
            "market": "Near a market"}.get(asset.get("near"))
    if near:
        out.append(near + (" on a main road" if asset.get("road_class") == "main" else ""))
    if an["complaints"] >= 5:
        out.append(f"{an['complaints']} complaints")
    return out


def rupees(n):
    if n >= 100000:
        return f"₹{n / 100000:.1f} lakh"
    return f"₹{n:,}"


def summary(db, asset, on_date=None):
    an = analyze(db, asset["id"], on_date)
    pr = priority(asset, an)
    return {"id": asset["id"], "name": asset["name"], "type": asset["type"], "lat": asset["lat"],
            "lng": asset["lng"], "near": asset.get("near"), "status": asset.get("status"),
            "department": DEPARTMENTS[asset["type"]], "complaints": an["complaints"], "failures": an["failures"],
            "total_cost": an["total_cost"], "repeat_spend": an["repeat_spend"], "prediction": an["prediction"],
            "priority": pr, "warranty_recoverable": an["warranty"]["recoverable"],
            "seasonal_share": an["seasonal_share"], "money": an["money"]}
