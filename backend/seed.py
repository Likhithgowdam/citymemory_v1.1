"""Generates the sample ward dataset used for the demo.

Deterministic (fixed random seed), so every run produces the same ward.
The hero asset SWD-151-07 reproduces the story from our Level 1 document:
8 complaints, 6 patch repairs, Rs 4.1 lakh spent, a 43-day re-failure,
and failures every monsoon.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

CENTER = (12.9352, 77.6245)
WARD = "Ward 151"

LANDMARKS = [
    # (english, kannada, nearby-facility tag)
    ("bus stop", "ಬಸ್ ನಿಲ್ದಾಣ", "bus_stop"),
    ("government school", "ಸರ್ಕಾರಿ ಶಾಲೆ", "school"),
    ("PHC hospital", "ಆಸ್ಪತ್ರೆ", "hospital"),
    ("vegetable market", "ತರಕಾರಿ ಮಾರುಕಟ್ಟೆ", "market"),
    ("Ganesha temple", "ಗಣೇಶ ದೇವಸ್ಥಾನ", None),
    ("park gate", "ಪಾರ್ಕ್ ಗೇಟ್", None),
    ("water tank", "ನೀರಿನ ಟ್ಯಾಂಕ್", None),
    ("1st Cross junction", "1ನೇ ಕ್ರಾಸ್", None),
    ("5th Cross", "5ನೇ ಕ್ರಾಸ್", None),
    ("church", "ಚರ್ಚ್", None),
    ("ration shop", "ರೇಷನ್ ಅಂಗಡಿ", None),
    ("railway underpass", "ಅಂಡರ್‌ಪಾಸ್", None),
]

TYPES = {
    "drainage": {"prefix": "SWD", "label": "Stormwater drain", "count": 12, "seasonal": True,
                 "patch": (30000, 110000), "permanent": (400000, 900000)},
    "road": {"prefix": "RD", "label": "Road stretch", "count": 14, "seasonal": True,
             "patch": (15000, 90000), "permanent": (600000, 1500000)},
    "streetlight": {"prefix": "SL", "label": "Streetlight", "count": 8, "seasonal": False,
                    "patch": (3000, 15000), "permanent": (100000, 250000)},
    "footpath": {"prefix": "FP", "label": "Footpath", "count": 4, "seasonal": False,
                 "patch": (10000, 40000), "permanent": (150000, 400000)},
    "toilet": {"prefix": "PT", "label": "Public toilet", "count": 2, "seasonal": False,
               "patch": (8000, 30000), "permanent": (200000, 500000)},
}

TEMPLATES = {
    "drainage": {
        "en": ["Water logging near {lm}", "Drain overflowing near {lm}, water on road",
               "Gutter blocked near {lm}, very bad smell", "Road flooded after rain near {lm}",
               "Stagnant water near {lm} for two days"],
        "kg": ["{lm} hatra road mele neeru nintide", "{lm} hatra charandi block agide",
               "Male bandre {lm} hatra neeru tumbutte"],
        "kn": ["{lmk} ಹತ್ತಿರ ಚರಂಡಿ ತುಂಬಿ ನೀರು ರಸ್ತೆಗೆ ಬರುತ್ತಿದೆ"],
    },
    "road": {
        "en": ["Big pothole near {lm}", "Road damaged near {lm}, bikes falling",
               "Potholes again on the road near {lm}", "Patch work washed away near {lm}"],
        "kg": ["{lm} hatra dodda gundi ide", "{lm} hatra rasthe haalagide"],
        "kn": ["{lmk} ಹತ್ತಿರ ರಸ್ತೆಯಲ್ಲಿ ದೊಡ್ಡ ಗುಂಡಿ"],
    },
    "streetlight": {
        "en": ["Street light not working near {lm}", "Street lights off near {lm}, very dark at night"],
        "kg": ["{lm} hatra deepa illa, tumba kattale"],
        "kn": ["{lmk} ಹತ್ತಿರ ಬೀದಿ ದೀಪ ಕೆಲಸ ಮಾಡುತ್ತಿಲ್ಲ"],
    },
    "footpath": {
        "en": ["Footpath slab broken near {lm}", "Broken pavement near {lm}, people tripping"],
        "kg": ["{lm} hatra footpath slab odedide"],
        "kn": [],
    },
    "toilet": {
        "en": ["Public toilet near {lm} not cleaned, no water", "Toilet near {lm} very dirty and smelling"],
        "kg": ["{lm} hatra toilet alli neeru illa"],
        "kn": [],
    },
}

CHANNELS = ["app", "app", "helpline", "whatsapp", "app", "helpline", "meeting"]

# Made-up contractor names for the demo (no real companies)
CONTRACTORS = {
    "drainage": ["Sri Ganesh Constructions", "Kaveri Civil Works", "Namma Drains & Co"],
    "road": ["Lakshmi Road Works", "Sri Ganesh Constructions", "Hosa Roads Pvt Ltd"],
    "streetlight": ["BrightLine Electricals", "Deepa Electric Services"],
    "footpath": ["Namma Civil Works", "Kaveri Civil Works"],
    "toilet": ["Swachh Facility Services"],
}
HERO_CONTRACTOR = {"SWD-151-07": "Sri Ganesh Constructions"}

# Sample planned digging by other agencies (made-up, for the "Don't dig again" alert)
WORKS = [
    {"id": "W-01", "agency": "BWSSB", "what": "Water pipeline replacement", "place": "Main Road, near the bus stop",
     "lat": 12.9372, "lng": 77.6264, "radius_m": 180, "start": "2026-12-01", "end": "2027-01-31"},
    {"id": "W-02", "agency": "BESCOM", "what": "Underground power cable laying", "place": "Road outside the government school",
     "lat": 12.9332, "lng": 77.6291, "radius_m": 150, "start": "2027-02-10", "end": "2027-03-15"},
    {"id": "W-03", "agency": "Gas utility", "what": "Gas pipeline work", "place": "Lane off Hospital Road",
     "lat": 12.9306, "lng": 77.6206, "radius_m": 140, "start": "2026-11-15", "end": "2026-12-20"},
]


def add_contractors(db):
    """Give every repair a contractor and a guarantee period (fixed rules, no randomness)."""
    types = {a["id"]: a["type"] for a in db["assets"]}
    for r in db["repairs"]:
        t = types.get(r["asset_id"], "road")
        if not r.get("contractor"):
            names = CONTRACTORS.get(t, CONTRACTORS["road"])
            r["contractor"] = HERO_CONTRACTOR.get(r["asset_id"]) or names[int(r["id"].split("-")[-1]) % len(names)]
        if not r.get("warranty_months"):
            r["warranty_months"] = 3 if r["kind"] == "patch" else (12 if t == "streetlight" else 24)
    return db
START, END = date(2024, 1, 5), date(2026, 10, 20)


def jitter(rng, lat, lng, meters):
    dlat = rng.uniform(-meters, meters) / 111000
    dlng = rng.uniform(-meters, meters) / 108500
    return round(lat + dlat, 6), round(lng + dlng, 6)


def in_season(d):
    return (d.month == 5 and d.day >= 15) or 6 <= d.month <= 10


def random_event_date(rng, seasonal):
    while True:
        d = START + timedelta(days=rng.randrange((END - START).days))
        if not seasonal or in_season(d) or rng.random() < 0.25:
            return d


def complaint_text(rng, atype, lm):
    t = TEMPLATES[atype]
    pool = [("en", x) for x in t["en"]] * 3 + [("kg", x) for x in t["kg"]] * 2 + [("kn", x) for x in t["kn"]]
    lang, tpl = rng.choice(pool)
    return tpl.format(lm=lm[0], lmk=lm[1]), lang


def build():
    rng = random.Random(151)
    assets, complaints, repairs = [], [], []

    # ---- hero assets placed by hand -------------------------------------
    hero = {"id": "SWD-151-07", "type": "drainage", "name": "Stormwater drain beside bus stop, Main Road",
            "landmark": "bus stop", "landmark_kn": "ಬಸ್ ನಿಲ್ದಾಣ", "near": "bus_stop", "road_class": "main",
            "lat": 12.9369, "lng": 77.6268}
    road_at_stop = {"id": "RD-151-02", "type": "road", "name": "Main Road stretch near bus stop",
                    "landmark": "bus stop", "landmark_kn": "ಬಸ್ ನಿಲ್ದಾಣ", "near": "bus_stop", "road_class": "main",
                    "lat": 12.9376, "lng": 77.6261}
    fixed_road = {"id": "RD-151-05", "type": "road", "name": "Hospital Road stretch",
                  "landmark": "PHC hospital", "landmark_kn": "ಆಸ್ಪತ್ರೆ", "near": "hospital", "road_class": "main",
                  "lat": 12.9318, "lng": 77.6214}
    school_light = {"id": "SL-151-03", "type": "streetlight", "name": "Streetlight row outside government school",
                    "landmark": "government school", "landmark_kn": "ಸರ್ಕಾರಿ ಶಾಲೆ", "near": "school",
                    "road_class": "local", "lat": 12.9331, "lng": 77.6290}
    hand_placed = [hero, road_at_stop, fixed_road, school_light]
    taken = {a["id"] for a in hand_placed}

    # ---- generated assets -------------------------------------------------
    for atype, spec in TYPES.items():
        n = 1
        made = 0
        while made < spec["count"]:
            aid = f"{spec['prefix']}-151-{n:02d}"
            n += 1
            if aid in taken:
                made += 1
                continue
            lm = rng.choice(LANDMARKS)
            while True:
                lat, lng = jitter(rng, *CENTER, 950)
                # keep the north-east corner empty for the "new spot" demo
                if lat > 12.9405 and lng > 77.6300:
                    continue
                if all(abs(lat - a["lat"]) + abs(lng - a["lng"]) > 0.0016 for a in assets + hand_placed):
                    break
            assets.append({"id": aid, "type": atype, "name": f"{spec['label']} near {lm[0]}",
                           "landmark": lm[0], "landmark_kn": lm[1], "near": lm[2],
                           "road_class": rng.choice(["main", "local", "local"]), "lat": lat, "lng": lng})
            made += 1
    assets = hand_placed + assets
    for a in assets:
        a.update({"ward": WARD, "status": "active", "decision": None})

    # ---- history for generated assets ------------------------------------
    # A fixed plan keeps the ward realistic: a few chronic assets, many with a
    # couple of failures, and quiet ones. Several citizens often report one failure.
    events = []  # (asset, date, n_complaints)
    generated = [a for a in assets if a not in hand_placed]
    plan = ["chronic"] * 8 + ["twice"] * 12 + ["quiet"] * (len(generated) - 20)
    rng.shuffle(plan)
    for a, kind in zip(generated, plan):
        k = {"chronic": rng.randint(3, 5), "twice": 2, "quiet": rng.randint(0, 1)}[kind]
        per = {"chronic": [2, 3], "twice": [4, 5, 6, 6, 7], "quiet": [4, 6, 8]}[kind]
        dates = sorted(random_event_date(rng, TYPES[a["type"]]["seasonal"]) for _ in range(k))
        for d in dates:
            events.append((a, d, rng.choice(per)))

    def add_complaint(a, d, text, lang, channel, spread=30):
        lat, lng = jitter(rng, a["lat"], a["lng"], spread)
        complaints.append({"date": d.isoformat(), "text": text, "lang": lang, "channel": channel,
                           "lat": lat, "lng": lng, "asset_id": a["id"], "status": "linked",
                           "match": {"score": None, "decision": "historical"}})

    def add_repair(a, d, cost, kind, note):
        repairs.append({"date": d.isoformat(), "asset_id": a["id"], "cost": int(cost), "kind": kind, "note": note})

    patch_notes = {"drainage": "Desilted drain mouth and cleared blockage", "road": "Pothole patch work",
                   "streetlight": "Replaced lamp", "footpath": "Replaced broken slab", "toilet": "Cleaning and tap repair"}

    for a, d, nc in events:
        lm = (a["landmark"], a["landmark_kn"])
        for i in range(nc):
            text, lang = complaint_text(rng, a["type"], lm)
            add_complaint(a, d + timedelta(days=i * rng.randint(1, 4)), text, lang, rng.choice(CHANNELS))
        if rng.random() < 0.82:
            lo, hi = TYPES[a["type"]]["patch"]
            add_repair(a, d + timedelta(days=rng.randint(3, 12)), round(rng.randint(lo, hi), -3), "patch",
                       patch_notes[a["type"]])

    # ---- hero: SWD-151-07 (exactly as in the document) --------------------
    hero_c = [
        ("2024-06-12", "Water logging near bus stop on Main Road", "en", "app"),
        ("2024-06-15", "Drain overflowing near bus stop, water on road", "en", "helpline"),
        ("2024-08-02", "Bus stop hatra road mele neeru nintide again", "kg", "whatsapp"),
        ("2025-05-28", "Gutter blocked near bus stop, bad smell and water on road", "en", "app"),
        ("2025-06-03", "ಬಸ್ ನಿಲ್ದಾಣ ಹತ್ತಿರ ಚರಂಡಿ ತುಂಬಿ ನೀರು ರಸ್ತೆಗೆ ಬರುತ್ತಿದೆ", "kn", "app"),
        ("2025-07-25", "Water logging again near bus stop after one hour of rain", "en", "helpline"),
        ("2026-06-10", "Road flooded near bus stop, buses cannot stop", "en", "meeting"),
        ("2026-09-14", "Bus stop hatra charandi block agide, neeru road mele", "kg", "whatsapp"),
    ]
    for d, t, lang, ch in hero_c:
        add_complaint(hero, date.fromisoformat(d), t, lang, ch, spread=20)
    for d, cost in [("2024-06-20", 38000), ("2024-08-10", 45000), ("2025-06-08", 62000),
                    ("2025-07-29", 70000), ("2026-06-18", 85000), ("2026-09-20", 110000)]:
        add_repair(hero, date.fromisoformat(d), cost, "patch", "Desilted drain mouth and patched the road")

    # ---- road at the same bus stop: two pothole episodes -----------------
    for d, t, lang in [("2025-07-02", "Big pothole near bus stop", "en"),
                       ("2026-08-21", "Bus stop hatra dodda gundi ide", "kg")]:
        add_complaint(road_at_stop, date.fromisoformat(d), t, lang, "app", spread=15)
    add_repair(road_at_stop, date(2025, 7, 9), 28000, "patch", "Pothole patch work")

    # ---- hospital road: chronic, then fixed permanently -------------------
    for d, t, lang in [("2024-07-08", "Potholes again on the road near PHC hospital", "en"),
                       ("2024-07-10", "Ambulance struggling, big pothole near PHC hospital", "en"),
                       ("2024-09-19", "PHC hospital hatra dodda gundi ide", "kg"),
                       ("2025-01-14", "Road damaged near PHC hospital, bikes falling", "en"),
                       ("2025-06-21", "ಆಸ್ಪತ್ರೆ ಹತ್ತಿರ ರಸ್ತೆಯಲ್ಲಿ ದೊಡ್ಡ ಗುಂಡಿ", "kn"),
                       ("2025-09-02", "Patch work washed away near PHC hospital", "en")]:
        add_complaint(fixed_road, date.fromisoformat(d), t, lang, rng.choice(CHANNELS), spread=25)
    for d, cost in [("2024-07-16", 52000), ("2024-09-27", 61000), ("2025-01-22", 48000),
                    ("2025-06-28", 66000), ("2025-09-10", 70000)]:
        add_repair(fixed_road, date.fromisoformat(d), cost, "patch", "Pothole patch work")
    add_repair(fixed_road, date(2025, 11, 25), 950000, "permanent",
               "Resurfaced with base compaction and side drain (permanent fix)")

    # ---- school streetlights: cable fault, bulbs keep getting replaced ----
    for d, t, lang in [("2024-02-11", "Street light not working near government school", "en"),
                       ("2024-04-02", "Street lights off near government school, very dark at night", "en"),
                       ("2024-11-18", "government school hatra deepa illa, tumba kattale", "kg"),
                       ("2025-03-09", "Street light not working near government school", "en"),
                       ("2025-10-27", "ಸರ್ಕಾರಿ ಶಾಲೆ ಹತ್ತಿರ ಬೀದಿ ದೀಪ ಕೆಲಸ ಮಾಡುತ್ತಿಲ್ಲ", "kn"),
                       ("2026-07-30", "Street lights off near government school, children walk in the dark", "en")]:
        add_complaint(school_light, date.fromisoformat(d), t, lang, rng.choice(CHANNELS), spread=20)
    for d, cost in [("2024-02-15", 6000), ("2024-04-06", 7500), ("2024-11-22", 6500),
                    ("2025-03-12", 8000), ("2025-10-30", 9000), ("2026-08-03", 9500)]:
        add_repair(school_light, date.fromisoformat(d), cost, "patch", "Replaced lamp")

    # ---- ids --------------------------------------------------------------
    complaints.sort(key=lambda c: (c["date"], c["asset_id"]))
    for i, c in enumerate(complaints, 1):
        c["id"] = f"C-{i:04d}"
    repairs.sort(key=lambda r: (r["date"], r["asset_id"]))
    for i, r in enumerate(repairs, 1):
        r["id"] = f"R-{i:03d}"

    return add_contractors({"ward": WARD, "center": list(CENTER), "assets": assets,
                            "complaints": complaints, "repairs": repairs, "decisions": [],
                            "works": [dict(w) for w in WORKS]})


def write(path: Path):
    data = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "data" / "ward_151.json"
    d = write(out)
    print(f"{len(d['assets'])} assets, {len(d['complaints'])} complaints, {len(d['repairs'])} repairs -> {out}")
