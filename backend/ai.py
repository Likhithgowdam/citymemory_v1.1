"""AI layer.

If GEMINI_API_KEY is set, Google Gemini is used to (1) understand a complaint in any
language and (2) suggest the root cause of a failing asset, citing record IDs.
If there is no key, no internet, or any error, CityMemory falls back to built-in
rules, so the demo never breaks.
"""
import json
import os
import urllib.request

from . import text as tx
from .engine import rupees

TYPES = ["drainage", "road", "streetlight", "footpath", "toilet"]


def mode():
    return "gemini" if os.getenv("GEMINI_API_KEY") else "offline"


def model_name():
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _gemini_json(prompt: str, timeout=25):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name()}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    raw = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(raw)


# ---- 1. understanding a complaint -------------------------------------------
def understand(text: str):
    typ, conf, _ = tx.detect_type(text)
    result = {"type": typ, "confidence": conf, "english": None, "source": "offline rules"}
    if mode() == "gemini":
        try:
            g = _gemini_json(
                "You read civic complaints from Bengaluru written in English, Kannada or Kannada-English "
                "(Kanglish). Return JSON with keys: type (one of " + ", ".join(TYPES) + " or null), "
                "confidence (0 to 1), english (a short plain-English translation). Complaint: " + json.dumps(text))
            if g.get("type") in TYPES or g.get("type") is None:
                result = {"type": g.get("type"), "confidence": float(g.get("confidence", 0.7)),
                          "english": g.get("english"), "source": "Gemini"}
        except Exception as e:  # network, quota, bad JSON -> keep offline result
            result["note"] = f"Gemini unavailable ({type(e).__name__}); used offline rules"
    return result


# ---- 2. root-cause suggestion ------------------------------------------------
def suggest(asset, analysis, complaints, repairs):
    if mode() == "gemini":
        try:
            return _suggest_gemini(asset, analysis, complaints, repairs)
        except Exception as e:
            out = _suggest_rules(asset, analysis, complaints, repairs)
            out["note"] = f"Gemini unavailable ({type(e).__name__}); used offline rules"
            return out
    return _suggest_rules(asset, analysis, complaints, repairs)


def _suggest_gemini(asset, an, complaints, repairs):
    records = {
        "asset": {k: asset[k] for k in ("id", "type", "name", "near", "road_class")},
        "complaints": [{"id": c["id"], "date": c["date"], "text": c["text"]} for c in complaints],
        "repairs": [{"id": r["id"], "date": r["date"], "kind": r["kind"], "cost_rs": r["cost"], "note": r["note"]}
                    for r in repairs],
        "patterns": {k: an[k] for k in ("failures", "shortest_lasted_days", "median_gap_days", "seasonal_share")},
    }
    prompt = (
        "You help a municipal engineer in Bengaluru find the ROOT CAUSE of a civic asset that keeps failing. "
        "Use ONLY the records below. Do not invent facts. Reply in simple English. Return JSON with keys: "
        "cause (1-2 sentences), fix (1-2 sentences, a permanent fix), evidence (list of record IDs you relied on, "
        "taken only from the records), confidence (0 to 1). If the records are not enough, set cause to "
        "'Not enough evidence' and confidence below 0.4.\nRecords:\n" + json.dumps(records, ensure_ascii=False))
    g = _gemini_json(prompt)
    valid = {c["id"] for c in complaints} | {r["id"] for r in repairs}
    evidence = [e for e in g.get("evidence", []) if e in valid]
    conf = max(0.0, min(1.0, float(g.get("confidence", 0.5))))
    return {"cause": g.get("cause", ""), "fix": g.get("fix", ""), "evidence": evidence,
            "confidence": round(conf, 2), "confidence_label": _label(conf), "source": f"Gemini ({model_name()})"}


def _label(c):
    return "High" if c >= 0.75 else ("Medium" if c >= 0.5 else "Low")


def _suggest_rules(asset, an, complaints, repairs):
    t = asset["type"]
    seasonal = an["seasonal_share"] >= 0.6 and an["failures"] >= 3
    quick = an["shortest_lasted_days"] is not None and an["shortest_lasted_days"] <= 90
    if an["failures"] < 2:
        cause, fix, conf = ("Not enough evidence - this asset has failed only once.",
                            "Do the normal repair and let CityMemory keep watching it.", 0.3)
    elif t == "drainage":
        if seasonal:
            cause = ("The drain outlet is too small or blocked with silt, so rainwater backs up onto the road "
                     "every monsoon. Patching the road does not remove the cause.")
            fix = "Desilt the drain and widen or clear the outlet before June, then check it after the first heavy rain."
            conf = 0.8 if quick else 0.7
        else:
            cause = "The drain keeps getting blocked by silt and garbage."
            fix = "Desilt it fully, add a silt trap and put it on the pre-monsoon cleaning list."
            conf = 0.6
    elif t == "road":
        if seasonal:
            cause = ("Rainwater stands on this stretch and weakens the road base, so patches wash out every monsoon.")
            fix = "Fix the side drain and road slope first, then resurface the stretch instead of patching."
            conf = 0.75 if quick else 0.65
        else:
            cause = "The road base is weak for the traffic it carries, so patches break quickly."
            fix = "Mill and resurface the stretch with proper base compaction."
            conf = 0.6
    elif t == "streetlight":
        cause = ("The lights fail again and again even after lamps are replaced, which points to a cable or "
                 "feeder fault, not the bulbs.")
        fix = "Test and replace the underground cable or feeder pillar instead of replacing lamps."
        conf = 0.75 if an["failures"] >= 4 else 0.6
    elif t == "footpath":
        cause = "Slabs keep breaking, which suggests a weak base or a drain line underneath."
        fix = "Rebuild the base and use load-bearing slabs."
        conf = 0.55
    else:
        cause = "Repeated complaints suggest a water-supply or drain-line problem, not just cleaning."
        fix = "Repair the supply and drain lines and set a regular maintenance contract."
        conf = 0.55

    keywords = {"drainage": ["water", "neeru", "ನೀರು", "drain", "gutter", "charandi", "ಚರಂಡಿ", "flood"],
                "road": ["pothole", "gundi", "ಗುಂಡಿ", "patch", "damaged", "washed"],
                "streetlight": ["light", "deepa", "ದೀಪ", "dark", "kattale"],
                "footpath": ["slab", "footpath", "pavement"], "toilet": ["toilet", "water"]}[t]
    ev_c = [c["id"] for c in sorted(complaints, key=lambda c: c["date"], reverse=True)
            if any(k in c["text"].lower() for k in keywords)][:4]
    ev_r = [x["repair_id"] for x in an["repairs_detail"] if x["lasted_days"] is not None and x["lasted_days"] <= 90][:3]
    if an["failures"] >= 2 and an["total_cost"]:
        cause += f" So far {rupees(an['total_cost'])} has been spent on {an['repairs']} repairs."
    return {"cause": cause, "fix": fix, "evidence": ev_r + ev_c, "confidence": conf,
            "confidence_label": _label(conf), "source": "offline rules"}
