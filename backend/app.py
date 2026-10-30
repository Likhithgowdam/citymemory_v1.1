"""CityMemory API (FastAPI). Start with:  python run.py"""
import base64
import binascii
import hashlib
import json
import secrets
import re
import threading
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, engine, seed

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "ward_151.json"
PHOTOS = ROOT / "data" / "photos"
USERS = ROOT / "data" / "users.json"   # app accounts; kept when the demo data is reset
INDEX = ROOT / "frontend" / "index.html"
MOBILE = ROOT / "frontend" / "mobile.html"
PHOTOS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="CityMemory", version="1.1")
app.mount("/vendor", StaticFiles(directory=ROOT / "frontend" / "vendor"), name="vendor")
app.mount("/photos", StaticFiles(directory=PHOTOS), name="photos")
_lock = threading.Lock()
DB = {}


def load():
    global DB
    if not DATA.exists():
        seed.write(DATA)
    DB = json.loads(DATA.read_text(encoding="utf-8"))
    changed = False
    if "dataset" not in DB:  # changes on every reset, so phones know their old complaint ids are gone
        DB["dataset"] = uuid.uuid4().hex[:8]
        changed = True
    if "works" not in DB:  # data saved by an older version
        DB["works"] = [dict(w) for w in seed.WORKS]
        changed = True
    if any(not r.get("contractor") for r in DB["repairs"]):
        seed.add_contractors(DB)
        changed = True
    if changed:
        save()


def save():
    DATA.write_text(json.dumps(DB, ensure_ascii=False, indent=1), encoding="utf-8")


load()


def asset_or_404(asset_id):
    a = next((a for a in DB["assets"] if a["id"] == asset_id), None)
    if not a:
        raise HTTPException(404, f"Asset {asset_id} not found")
    return a


def next_id(items, prefix, width):
    nums = [int(x["id"].split("-")[-1]) for x in items if x["id"].startswith(prefix)]
    return f"{prefix}{(max(nums) + 1 if nums else 1):0{width}d}"


# ---- pages -------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(INDEX)


@app.get("/m", include_in_schema=False)
def mobile():
    """The mobile app screens (opened by the Android app, or in a phone browser)."""
    return FileResponse(MOBILE, headers={"Cache-Control": "no-cache"})


def save_photo(data_url: Optional[str], name: str):
    """Store a photo sent as a data URL (data:image/jpeg;base64,...) and return its web path."""
    if not data_url:
        return None
    m = re.match(r"^data:image/(jpeg|jpg|png|webp);base64,(.+)$", data_url, re.S)
    if not m:
        raise HTTPException(400, "The photo must be a JPEG, PNG or WebP image")
    try:
        raw = base64.b64decode(m.group(2))
    except (binascii.Error, ValueError):
        raise HTTPException(400, "The photo could not be read")
    if len(raw) > 6_000_000:
        raise HTTPException(413, "The photo is too large (6 MB at most)")
    ext = "jpg" if m.group(1) in ("jpeg", "jpg") else m.group(1)
    (PHOTOS / f"{name}.{ext}").write_bytes(raw)
    return f"/photos/{name}.{ext}"


# ---- read ----------------------------------------------------------------------
@app.get("/api/meta")
def meta():
    return {"ward": DB["ward"], "center": DB["center"], "today": engine.today().isoformat(),
            "ai_mode": ai.mode(), "model": ai.model_name() if ai.mode() == "gemini" else None,
            "dataset": DB.get("dataset")}


@app.get("/api/assets")
def assets():
    rows = [engine.summary(DB, a) for a in DB["assets"]]
    rows.sort(key=lambda r: r["priority"]["score"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


@app.get("/api/assets/{asset_id}")
def asset_detail(asset_id: str):
    a = asset_or_404(asset_id)
    an = engine.analyze(DB, asset_id)
    comps = sorted([c for c in DB["complaints"] if c["asset_id"] == asset_id], key=lambda c: c["date"])
    reps = sorted([r for r in DB["repairs"] if r["asset_id"] == asset_id], key=lambda r: r["date"])
    decisions = [x for x in DB["decisions"] if x["asset_id"] == asset_id]
    return {"asset": a, "department": engine.DEPARTMENTS[a["type"]], "analysis": an,
            "priority": engine.priority(a, an), "complaints": comps, "repairs": reps, "decisions": decisions,
            "works_nearby": works_near(a["lat"], a["lng"])}


def works_near(lat, lng):
    """Digging planned by other agencies near a place, that has not finished yet ("Don't dig again")."""
    t = engine.today().isoformat()
    out = []
    for w in DB.get("works", []):
        dist = engine.distance_m(lat, lng, w["lat"], w["lng"])
        if dist <= w["radius_m"] + 60 and w["end"] >= t:
            out.append({**w, "distance_m": round(dist)})
    return out


@app.get("/api/works")
def works():
    return DB.get("works", [])


@app.get("/api/monsoon")
def monsoon_list():
    """Pre-monsoon list: assets likely to fail in the next rains, with a date to inspect them by."""
    t = engine.today()
    rows = []
    for a in DB["assets"]:
        s = engine.summary(DB, a)
        p = s["prediction"]
        if not p.get("date") or s["priority"]["band"].startswith("Fixed"):
            continue
        if not p.get("at_risk"):
            continue
        pd_ = engine.d(p["date"])
        inspect_by = max(t, pd_ - engine.timedelta(days=45))
        s["inspect_by"] = inspect_by.isoformat()
        s["overdue"] = pd_ <= t
        rows.append(s)
    rows.sort(key=lambda r: (r["prediction"]["date"], -r["priority"]["score"]))
    return rows


def ward_health():
    """One simple 0-100 score for the ward. Lower when assets keep failing, repairs don't last,
    citizens say repairs didn't work, or danger reports are still open."""
    sums = [engine.analyze(DB, a["id"]) for a in DB["assets"]]
    n = max(1, len(sums))
    chronic = sum(1 for x in sums if x["failures"] >= 3 and not x["fixed_on"])
    lasted = [r["lasted_days"] for x in sums for r in x["repairs_detail"] if r["lasted_days"] is not None]
    quick = sum(1 for v in lasted if v <= 90) / max(1, len(lasted))
    fb = [c["feedback"]["fixed"] for c in DB["complaints"] if c.get("feedback")]
    unhappy = (fb.count(False) / len(fb)) if fb else 0
    danger = sum(1 for c in DB["complaints"] if c.get("urgent") and not c.get("safe_on"))
    parts = {"chronic": 0.40 * min(1, chronic / n * 2), "quick_fail": 0.35 * quick,
             "citizens_unhappy": 0.15 * unhappy, "open_danger": 0.10 * min(1, danger / 3)}
    score = round(100 * (1 - sum(parts.values())))
    label = "Good" if score >= 75 else ("Needs work" if score >= 50 else "Poor")
    reasons = {"chronic": f"{chronic} assets keep failing", "quick_fail": f"{round(quick * 100)}% of repairs failed within 3 months",
               "citizens_unhappy": f"{fb.count(False)} citizens said a repair did not work",
               "open_danger": f"{danger} danger reports still open"}
    worst = max(parts, key=parts.get)
    recoverable = sum(x["warranty"]["recoverable"] for x in sums)
    return {"score": max(0, score), "label": label, "main_reason": reasons[worst], "recoverable": recoverable}


@app.get("/api/health")
def health():
    return ward_health()


@app.get("/api/stats")
def stats():
    sums = [engine.summary(DB, a) for a in DB["assets"]]
    ledger = {}
    for s in sums:
        row = ledger.setdefault(s["department"], {"department": s["department"], "spend": 0, "repeat_spend": 0,
                                                   "assets": 0})
        row["spend"] += s["total_cost"]
        row["repeat_spend"] += s["repeat_spend"]
        row["assets"] += 1
    linked = sum(1 for c in DB["complaints"] if c["asset_id"])
    return {
        "complaints": len(DB["complaints"]), "linked": linked, "assets": len(DB["assets"]),
        "in_review": sum(1 for c in DB["complaints"] if c["status"] == "review"),
        "total_spend": sum(s["total_cost"] for s in sums),
        "repeat_spend": sum(s["repeat_spend"] for s in sums),
        "chronic": sum(1 for s in sums if s["failures"] >= 3 and not s["prediction"]["label"].startswith("Permanent")),
        "at_risk": sum(1 for s in sums if s["prediction"].get("at_risk")),
        "ledger": sorted(ledger.values(), key=lambda r: r["repeat_spend"], reverse=True),
    }


@app.get("/api/review")
def review_queue():
    return [c for c in DB["complaints"] if c["status"] == "review"]


# ---- write ---------------------------------------------------------------------
class ComplaintIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    lat: float
    lng: float
    channel: str = "app"
    date: Optional[str] = None
    type: Optional[str] = None      # problem type the citizen tapped in the app, if any
    photo: Optional[str] = None     # data URL from the app camera
    urgent: bool = False            # "Danger now" button
    hazard: Optional[str] = None    # manhole, wire, flood, tree, other


HAZARD_TYPE = {"manhole": "drainage", "flood": "drainage", "wire": "streetlight", "tree": "road", "other": None}


@app.post("/api/complaints")
def new_complaint(body: ComplaintIn, x_token: Optional[str] = Header(None)):
    on = date.fromisoformat(body.date) if body.date else engine.today()
    und = ai.understand(body.text)
    if body.urgent and not body.type:
        body.type = HAZARD_TYPE.get(body.hazard or "other")
    if body.type in ai.TYPES and und["type"] != body.type:
        # the citizen told us the problem type by tapping a picture; trust that
        und = {**und, "type": body.type, "confidence": max(und.get("confidence") or 0, 0.9),
               "source": f"{und['source']} + citizen's choice"}
    decision, cands = engine.match(DB, body.text, body.lat, body.lng, und["type"], on)
    if decision == "new" and not und["type"]:
        decision = "review"  # unknown problem type in an unknown place: a person should look

    with _lock:
        cid = next_id(DB["complaints"], "C-", 4)
        comp = {"id": cid, "date": on.isoformat(), "text": body.text, "lang": None, "channel": body.channel,
                "lat": body.lat, "lng": body.lng, "asset_id": None, "status": "review",
                "match": {"decision": decision, "score": cands[0]["score"] if cands else 0,
                          "candidates": cands, "understanding": und}}
        if body.photo:
            comp["photo"] = save_photo(body.photo, cid)
        who = user_from_token(x_token)
        if who:
            comp["user"] = who
        if body.urgent:
            comp["urgent"] = True
            comp["hazard"] = body.hazard if body.hazard in HAZARD_TYPE else "other"
        new_asset = None
        if decision == "auto":
            comp["asset_id"], comp["status"] = cands[0]["asset_id"], "linked"
        elif decision == "new":
            new_asset = _create_asset(und["type"], body.lat, body.lng, body.text)
            comp["asset_id"], comp["status"] = new_asset["id"], "new_asset"
        DB["complaints"].append(comp)
        save()

    out = {"complaint": comp, "understanding": und, "decision": decision, "candidates": cands}
    if comp["asset_id"]:
        out["asset"] = engine.summary(DB, asset_or_404(comp["asset_id"]), on)
        out["alert"] = _alert(comp, on, created=bool(new_asset))
    else:
        out["alert"] = {"level": "review", "headline": "Needs a city employee to confirm",
                        "detail": "CityMemory is not sure which asset this is. It has been added to the review queue "
                                  "with the most likely matches."}
    return out


def _create_asset(atype, lat, lng, text):
    prefix = {"drainage": "SWD", "road": "RD", "streetlight": "SL", "footpath": "FP", "toilet": "PT"}[atype]
    aid = next_id(DB["assets"], f"{prefix}-151-", 2)
    label = {"drainage": "Stormwater drain", "road": "Road stretch", "streetlight": "Streetlight",
             "footpath": "Footpath", "toilet": "Public toilet"}[atype]
    a = {"id": aid, "type": atype, "name": f"{label} (new, from complaint)", "landmark": "", "landmark_kn": "",
         "near": None, "road_class": "local", "lat": lat, "lng": lng, "ward": DB["ward"], "status": "active",
         "decision": None, "created_from_complaint": True}
    DB["assets"].append(a)
    return a


def _alert(comp, on, created=False):
    an = engine.analyze(DB, comp["asset_id"], on)
    n = an["complaints"]
    failure_no = next((i for i, e in enumerate(an["events"], 1) if comp["id"] in e["complaint_ids"]), an["failures"])
    if created:
        return {"level": "new", "headline": f"New asset created: {comp['asset_id']}",
                "detail": "No known asset nearby, so CityMemory started a new memory for this place."}
    prior = [r for r in DB["repairs"] if r["asset_id"] == comp["asset_id"] and r["date"] <= comp["date"]]
    if prior:
        last = max(prior, key=lambda r: r["date"])
        days = (on - date.fromisoformat(last["date"])).days
        detail = (f"Last repaired {days} days ago ({engine.fmt(date.fromisoformat(last['date']))}). "
                  f"{an['failures']} failures and {engine.rupees(an['total_cost'])} spent so far.")
    else:
        detail = "No repair on record yet for this asset."
    level = "repeat" if an["failures"] >= 2 else "first"
    headline = (f"Complaint #{n} at {comp['asset_id']}, failure #{failure_no}" if level == "repeat"
                else f"First failure on record at {comp['asset_id']}")
    return {"level": level, "headline": headline, "detail": detail}


class ReviewIn(BaseModel):
    asset_id: Optional[str] = None
    create_new: bool = False


@app.post("/api/review/{complaint_id}")
def resolve_review(complaint_id: str, body: ReviewIn):
    with _lock:
        c = next((c for c in DB["complaints"] if c["id"] == complaint_id), None)
        if not c or c["status"] != "review":
            raise HTTPException(404, "No complaint waiting for review with that id")
        if body.create_new:
            und = c["match"].get("understanding", {})
            a = _create_asset(und.get("type") or "road", c["lat"], c["lng"], c["text"])
            c["asset_id"], c["status"] = a["id"], "new_asset"
        else:
            asset_or_404(body.asset_id)
            c["asset_id"], c["status"] = body.asset_id, "linked"
        c["match"]["confirmed_by"] = "engineer"
        save()
    return {"complaint": c, "asset": engine.summary(DB, asset_or_404(c["asset_id"]))}


@app.post("/api/assets/{asset_id}/suggest")
def suggest(asset_id: str):
    a = asset_or_404(asset_id)
    an = engine.analyze(DB, asset_id)
    comps = [c for c in DB["complaints"] if c["asset_id"] == asset_id]
    reps = [r for r in DB["repairs"] if r["asset_id"] == asset_id]
    return ai.suggest(a, an, comps, reps)


class DecisionIn(BaseModel):
    action: str = Field(pattern="^(approve_fix|reject)$")
    note: str = ""
    suggestion: Optional[dict] = None


@app.post("/api/assets/{asset_id}/decision")
def decide(asset_id: str, body: DecisionIn):
    with _lock:
        a = asset_or_404(asset_id)
        rec = {"asset_id": asset_id, "date": engine.today().isoformat(), "action": body.action,
               "note": body.note, "suggestion": body.suggestion}
        DB["decisions"].append(rec)
        if body.action == "approve_fix":
            a["status"] = "fix_planned"
        save()
    return {"ok": True, "decision": rec, "asset": engine.summary(DB, a)}


@app.post("/api/reset")
def reset():
    """Restore the original sample ward (use before each demo)."""
    with _lock:
        seed.write(DATA)
        load()
        for f in PHOTOS.glob("*"):
            if f.is_file():
                f.unlink()
    return {"ok": True}


# ---- accounts (simple username + password for the mobile app) -----------------------
def _load_users():
    if USERS.exists():
        return json.loads(USERS.read_text(encoding="utf-8"))
    return {"users": {}, "tokens": {}}


ACC = _load_users()


def _save_users():
    USERS.write_text(json.dumps(ACC, ensure_ascii=False, indent=1), encoding="utf-8")


def _hash(password: str, salt: str) -> str:
    # passwords are never stored as plain text
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000).hex()


def _public(username):
    u = ACC["users"][username]
    return {"username": username, "name": u["name"], "created": u["created"]}


def _new_token(username):
    tok = secrets.token_hex(24)
    ACC["tokens"][tok] = username
    return tok


def user_from_token(token: Optional[str]):
    u = ACC["tokens"].get(token or "")
    return u if u in ACC["users"] else None


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    username: str = Field(min_length=3, max_length=20)
    password: str = Field(min_length=4, max_length=64)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=64)


@app.post("/api/register")
def register(body: RegisterIn):
    username = body.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.]{3,20}", username):
        raise HTTPException(400, "Username can use only letters, numbers, dot and underscore (3 to 20).")
    with _lock:
        if username in ACC["users"]:
            raise HTTPException(409, "This username is already taken. Try another one.")
        salt = secrets.token_hex(16)
        ACC["users"][username] = {"name": body.name.strip(), "salt": salt, "hash": _hash(body.password, salt),
                                  "created": engine.today().isoformat()}
        tok = _new_token(username)
        _save_users()
    return {"token": tok, "user": _public(username)}


@app.post("/api/login")
def login(body: LoginIn):
    username = body.username.strip().lower()
    u = ACC["users"].get(username)
    if not u or not secrets.compare_digest(_hash(body.password, u["salt"]), u["hash"]):
        raise HTTPException(401, "Wrong username or password.")
    with _lock:
        tok = _new_token(username)
        _save_users()
    return {"token": tok, "user": _public(username)}


@app.get("/api/me")
def me(x_token: Optional[str] = Header(None)):
    u = user_from_token(x_token)
    if not u:
        raise HTTPException(401, "Please log in again.")
    return _public(u)


@app.post("/api/logout")
def logout(x_token: Optional[str] = Header(None)):
    with _lock:
        ACC["tokens"].pop(x_token or "", None)
        _save_users()
    return {"ok": True}


# ---- mobile app ------------------------------------------------------------------
def complaint_or_404(cid):
    c = next((c for c in DB["complaints"] if c["id"] == cid), None)
    if not c:
        raise HTTPException(404, f"Complaint {cid} not found")
    return c


# How many days the city has to act on a complaint before it is escalated (simple, published targets)
SLA_DAYS = {"urgent": 1, "drainage": 7, "road": 7, "streetlight": 3, "footpath": 10, "toilet": 3}


def deadline(c, a, repair):
    """Fix-by date for a complaint, and who it is escalated to when it is late."""
    on = engine.today()
    und = (c.get("match") or {}).get("understanding") or {}
    kind = "urgent" if c.get("urgent") else (a["type"] if a else und.get("type"))
    days = SLA_DAYS.get(kind, 7)
    due = engine.d(c["date"]) + engine.timedelta(days=days)
    fb = c.get("feedback")
    done = bool(repair) or bool(c.get("safe_on")) or bool(fb and fb.get("fixed"))
    planned = bool(a and a.get("status") in ("fix_planned", "fixed"))
    late = 0 if (done or planned) else max(0, (on - due).days)
    level = None
    if late:
        level = "Assistant Executive Engineer" if late <= days * 2 else "Executive Engineer"
    return {"due": due.isoformat(), "sla_days": days, "days_left": (due - on).days, "late_days": late,
            "done": done, "planned": planned, "escalated_to": level}


def citizen_view(c):
    """One complaint as the citizen sees it: where it is in 5 simple steps."""
    a = next((a for a in DB["assets"] if a["id"] == c["asset_id"]), None) if c["asset_id"] else None
    s = engine.summary(DB, a) if a else None
    since = sorted((r for r in DB["repairs"] if a and r["asset_id"] == a["id"] and r["date"] >= c["date"]),
                   key=lambda r: (r["date"], r["id"]))
    repair = since[-1] if since else None
    fb = c.get("feedback")
    if fb and fb.get("fixed"):
        step = 5
    elif repair:
        step = 4
    elif a and a.get("status") in ("fix_planned", "fixed"):
        step = 3
    elif a:
        step = 2
    else:
        step = 1
    dates = [c["date"]] + ([repair["date"]] if repair else []) + ([fb["date"]] if fb else [])
    dates += [x["date"] for x in DB["decisions"] if a and x["asset_id"] == a["id"] and x["date"] >= c["date"]]
    und = (c.get("match") or {}).get("understanding") or {}
    return {"id": c["id"], "date": c["date"], "text": c["text"], "photo": c.get("photo"),
            "type": a["type"] if a else und.get("type"), "status": c["status"], "step": step,
            "closed": bool(fb and fb.get("fixed")), "feedback": fb, "asset": s, "repair": repair,
            "updated": max(dates + ([c["safe_on"]] if c.get("safe_on") else [])),
            "urgent": bool(c.get("urgent")), "hazard": c.get("hazard"), "safe_on": c.get("safe_on"),
            "deadline": deadline(c, a, repair)}


def late_complaints():
    """Open complaints from the last 60 days that missed their fix-by date (escalated)."""
    t = engine.today()
    rows = []
    for c in DB["complaints"]:
        if (t - engine.d(c["date"])).days > 60:
            continue
        a = next((x for x in DB["assets"] if x["id"] == c["asset_id"]), None) if c["asset_id"] else None
        rep = next((r for r in DB["repairs"] if a and r["asset_id"] == a["id"] and r["date"] >= c["date"]), None)
        dl = deadline(c, a, rep)
        if dl["late_days"]:
            rows.append({"complaint_id": c["id"], "asset_id": c["asset_id"], "date": c["date"], "text": c["text"],
                         "asset_name": a["name"] if a else None, **dl})
    rows.sort(key=lambda r: -r["late_days"])
    return rows


@app.get("/api/my")
def my_complaints(ids: str = "", x_token: Optional[str] = Header(None)):
    """The citizen's own complaints: the ids kept on the phone, plus everything sent while logged in."""
    want = [x.strip() for x in ids.split(",") if x.strip()][:50]
    who = user_from_token(x_token)
    rows = [citizen_view(c) for c in DB["complaints"] if c["id"] in want or (who and c.get("user") == who)]
    rows.sort(key=lambda v: (v["date"], v["id"]), reverse=True)
    return rows


class FeedbackIn(BaseModel):
    fixed: bool


@app.post("/api/complaints/{complaint_id}/feedback")
def feedback(complaint_id: str, body: FeedbackIn):
    """'Was it fixed?' answer from the citizen after a repair."""
    with _lock:
        c = complaint_or_404(complaint_id)
        c["feedback"] = {"fixed": body.fixed, "date": engine.today().isoformat()}
        save()
    return citizen_view(c)


class PlaceIn(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None


@app.post("/api/assets/{asset_id}/metoo")
def me_too(asset_id: str, body: PlaceIn, x_token: Optional[str] = Header(None)):
    """'Me too, same problem': adds the citizen's voice to a problem that is already known."""
    who = user_from_token(x_token)
    with _lock:
        a = asset_or_404(asset_id)
        cid = next_id(DB["complaints"], "C-", 4)
        comp = {"id": cid, "date": engine.today().isoformat(), "text": "Me too: same problem here", "lang": None,
                "channel": "app", "lat": body.lat if body.lat is not None else a["lat"],
                "lng": body.lng if body.lng is not None else a["lng"], "asset_id": asset_id, "status": "linked",
                "match": {"decision": "me_too", "score": 1.0}}
        if who:
            comp["user"] = who
        DB["complaints"].append(comp)
        save()
    return {"complaint": comp, "asset": engine.summary(DB, a)}


@app.get("/api/nearby")
def nearby(lat: float, lng: float, radius: int = 700):
    """Problems already reported near a place (reported in the last 4 months, or with a fix planned)."""
    t = engine.today()
    rows = []
    for a in DB["assets"]:
        dist = engine.distance_m(lat, lng, a["lat"], a["lng"])
        if dist > radius:
            continue
        recent = [c for c in DB["complaints"] if c["asset_id"] == a["id"] and (t - engine.d(c["date"])).days <= 120]
        if not recent and a.get("status") != "fix_planned":
            continue
        s = engine.summary(DB, a)
        s["distance_m"] = round(dist)
        s["recent_reports"] = len(recent)
        rows.append(s)
    rows.sort(key=lambda r: r["distance_m"])
    return rows[:12]


@app.get("/api/today")
def today_view():
    """The engineer's start-of-day screen: new complaints, counts, and where to go first."""
    t = engine.today()
    ranked = assets()
    recent = sorted((c for c in DB["complaints"] if c["asset_id"] and (t - engine.d(c["date"])).days <= 14),
                    key=lambda c: (c["date"], c["id"]), reverse=True)
    news = []
    for c in recent[:3]:
        al = _alert(c, engine.d(c["date"]))
        news.append({"complaint_id": c["id"], "asset_id": c["asset_id"], "date": c["date"], "text": c["text"],
                     "headline": al["headline"], "detail": al["detail"]})
    visit = [r for r in ranked if not r["priority"]["band"].startswith(("Fixed", "Low"))][:8]
    st = stats()
    urgent = [{"complaint_id": c["id"], "asset_id": c["asset_id"], "date": c["date"], "text": c["text"],
               "hazard": c.get("hazard"), "lat": c["lat"], "lng": c["lng"], "photo": c.get("photo")}
              for c in sorted(DB["complaints"], key=lambda c: c["id"], reverse=True)
              if c.get("urgent") and not c.get("safe_on")]
    high = [r for r in ranked if r["priority"]["band"].startswith("High") and r["money"]]
    late = late_complaints()
    return {"date": t.isoformat(), "ward": DB["ward"], "dataset": DB.get("dataset"), "new": news, "urgent": urgent,
            "counts": {"fix_permanently": sum(1 for r in ranked if r["priority"]["band"].startswith("High")),
                       "at_risk": len(monsoon_list()), "review": st["in_review"]},
            "health": ward_health(),
            "savings": {"assets": len(high), "ten_year": sum(max(0, r["money"]["ten_year_saving"]) for r in high)},
            "late": {"count": len(late), "items": late[:5]},
            "visit": visit}


DEMO_SPOT = (12.93695, 77.62675)   # the bus stop next to drain SWD-151-07, in the original sample ward


class RelocateIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@app.post("/api/relocate")
def relocate(body: RelocateIn):
    """Demo helper: move the whole sample ward so the bus-stop drain is where the phone is now.
    Every asset, complaint and planned work moves together; 'Reset demo data' puts it back."""
    with _lock:
        spot = (DEMO_SPOT[0] + DB["center"][0] - seed.CENTER[0], DEMO_SPOT[1] + DB["center"][1] - seed.CENTER[1])
        dlat, dlng = body.lat - spot[0], body.lng - spot[1]
        for coll in (DB["assets"], DB["complaints"], DB.get("works", [])):
            for x in coll:
                if x.get("lat") is not None:
                    x["lat"], x["lng"] = round(x["lat"] + dlat, 6), round(x["lng"] + dlng, 6)
        DB["center"] = [round(DB["center"][0] + dlat, 6), round(DB["center"][1] + dlng, 6)]
        moved = engine.distance_m(spot[0], spot[1], body.lat, body.lng)
        save()
    return {"ok": True, "center": DB["center"], "moved_m": round(moved)}


@app.post("/api/complaints/{complaint_id}/safe")
def mark_safe(complaint_id: str):
    """Engineer: the danger (open manhole, live wire...) has been made safe."""
    with _lock:
        c = complaint_or_404(complaint_id)
        c["safe_on"] = engine.today().isoformat()
        save()
    return {"ok": True, "complaint": c}


class RepairIn(BaseModel):
    kind: str = Field(pattern="^(patch|permanent)$")
    cost: int = Field(ge=0, le=100_000_000)
    note: str = Field(default="", max_length=300)
    photo_before: Optional[str] = None
    photo_after: Optional[str] = None
    contractor: str = Field(default="", max_length=60)
    warranty_months: Optional[int] = Field(default=None, ge=0, le=120)


@app.post("/api/assets/{asset_id}/repairs")
def log_repair(asset_id: str, body: RepairIn):
    """The engineer logs a repair from the site. A permanent fix starts the 'did it last?' watch."""
    with _lock:
        a = asset_or_404(asset_id)
        rid = next_id(DB["repairs"], "R-", 3)
        note = body.note.strip() or ("Permanent fix" if body.kind == "permanent" else "Patch repair")
        rep = {"id": rid, "date": engine.today().isoformat(), "asset_id": asset_id, "cost": body.cost,
               "kind": body.kind, "note": note,
               "photo_before": save_photo(body.photo_before, f"{rid}-before"),
               "photo_after": save_photo(body.photo_after, f"{rid}-after"),
               "contractor": body.contractor.strip() or "Ward maintenance team",
               "warranty_months": body.warranty_months if body.warranty_months is not None
               else engine.WARRANTY_DEFAULT[body.kind]}
        DB["repairs"].append(rep)
        if body.kind == "permanent":
            a["status"] = "fixed"
        save()
    return {"repair": rep, "asset": engine.summary(DB, a)}
