"""Understanding complaint text (English, Kannada-English and Kannada) without any API.

Two jobs:
1. detect_type()  - what kind of problem is this (drain, road, light, footpath, toilet)?
2. similarity()   - how close in meaning are two complaints, even across languages?

For similarity we map words in all three languages to shared "concept tags"
(e.g. "water logging", "neeru nintide" and "ನೀರು" all become WATER), then compare
character 3-grams. This handles spelling variations such as "gutter"/"guttar".
"""
import math
import re
import unicodedata
from collections import Counter

LEXICON = {
    "drainage": {
        "drain": 2, "gutter": 2, "water": 1, "overflow": 2, "overflowing": 2, "water logging": 3, "waterlogging": 3,
        "waterlogged": 3, "flood": 2, "flooded": 2, "flooding": 2, "stagnant": 2, "standing water": 3,
        "manhole": 2, "sewage": 2, "choked": 2, "blocked": 1, "rajakaluve": 3, "storm water": 3,
        "stormwater": 3, "neeru": 2, "nintide": 2, "tumbutte": 1, "charandi": 3, "ನೀರು": 2, "ಚರಂಡಿ": 3,
    },
    "road": {
        "pothole": 3, "potholes": 3, "crater": 2, "road damaged": 3, "road broken": 3, "broken road": 3,
        "gundi": 3, "rasthe": 1, "road": 1, "tar": 1, "asphalt": 2, "uneven": 1, "haalagide": 2,
        "ಗುಂಡಿ": 3, "ರಸ್ತೆ": 1,
    },
    "streetlight": {
        "street light": 3, "streetlight": 3, "street lights": 3, "light not working": 3, "lights off": 3,
        "dark": 2, "darkness": 2, "bulb": 2, "lamp": 2, "deepa": 2, "kattale": 2, "ದೀಪ": 2, "ಕತ್ತಲೆ": 2,
    },
    "footpath": {
        "footpath": 3, "pavement": 3, "slab": 2, "walkway": 2, "sidewalk": 3, "tripping": 1,
    },
    "toilet": {
        "toilet": 3, "public toilet": 3, "urinal": 2, "shauchalaya": 3, "smelling": 1,
    },
}
# Hindi words, so complaints typed or spoken in Hindi also work offline.
_HINDI = {
    "drainage": {"नाली": 3, "पानी": 2, "जलभराव": 3, "गटर": 2, "बाढ़": 2},
    "road": {"गड्ढा": 3, "गड्ढे": 3, "सड़क": 1},
    "streetlight": {"स्ट्रीट लाइट": 3, "लाइट": 2, "बत्ती": 2, "अंधेरा": 2},
    "footpath": {"फुटपाथ": 3, "फ़ुटपाथ": 3},
    "toilet": {"शौचालय": 3},
}
for _t, _words in _HINDI.items():
    LEXICON[_t].update(_words)

CONCEPTS = {
    "WATER": ["water", "neeru", "ನೀರು", "flood", "flooded", "logging", "waterlogging", "stagnant", "nintide",
              "tumbutte", "overflow", "overflowing", "पानी", "जलभराव"],
    "DRAIN": ["drain", "gutter", "charandi", "ಚರಂಡಿ", "manhole", "sewage", "rajakaluve", "नाली", "गटर"],
    "HOLE": ["pothole", "potholes", "gundi", "ಗುಂಡಿ", "crater", "गड्ढा", "गड्ढे"],
    "ROAD": ["road", "rasthe", "ರಸ್ತೆ", "ರಸ್ತೆಯಲ್ಲಿ", "ರಸ್ತೆಗೆ", "mele", "सड़क"],
    "LIGHT": ["light", "lights", "deepa", "ದೀಪ", "lamp", "bulb", "लाइट", "बत्ती"],
    "DARK": ["dark", "kattale", "ಕತ್ತಲೆ", "night", "अंधेरा"],
    "BLOCK": ["blocked", "block", "choked", "agide"],
}
# Place words say WHERE the problem is, so they count more than generic problem words.
PLACES = {
    "BUSSTOP": ["bus stop", "busstop", "bus stand", "ಬಸ್ ನಿಲ್ದಾಣ", "बस स्टॉप", "बस स्टैंड"],
    "SCHOOL": ["school", "shale", "ಶಾಲೆ", "स्कूल"],
    "HOSPITAL": ["hospital", "aspatre", "ಆಸ್ಪತ್ರೆ", "phc", "अस्पताल"],
    "MARKET": ["market", "ಮಾರುಕಟ್ಟೆ", "बाज़ार", "बाजार"],
    "TEMPLE": ["temple", "ದೇವಸ್ಥಾನ", "मंदिर"],
    "PARK": ["park", "ಪಾರ್ಕ್", "पार्क"],
    "TANK": ["water tank", "tank", "ಟ್ಯಾಂಕ್"],
    "CROSS1": ["1st cross", "1ನೇ ಕ್ರಾಸ್"],
    "CROSS5": ["5th cross", "5ನೇ ಕ್ರಾಸ್"],
    "CHURCH": ["church", "ಚರ್ಚ್"],
    "RATION": ["ration", "ರೇಷನ್"],
    "UNDERPASS": ["underpass", "ಅಂಡರ್‌ಪಾಸ್", "ಅಂಡರ್ಪಾಸ್"],
}
_STOP = {"near", "the", "on", "a", "is", "and", "of", "in", "at", "after", "very", "again", "for", "hatra", "ಹತ್ತಿರ",
         "के", "पास", "में", "है"}


def _nfd(w: str) -> str:
    # One spelling for letters that can be typed two ways (e.g. Hindi ड़), on both sides of every comparison.
    return unicodedata.normalize("NFD", w)


LEXICON = {k: {_nfd(w): v for w, v in d.items()} for k, d in LEXICON.items()}
CONCEPTS = {k: [_nfd(w) for w in ws] for k, ws in CONCEPTS.items()}
PLACES = {k: [_nfd(w) for w in ws] for k, ws in PLACES.items()}
_STOP = {_nfd(w) for w in _STOP}


def _norm(text: str) -> str:
    t = _nfd(text.lower())
    t = re.sub(r"[^\wಀ-೿ऀ-ॿ ]+", " ", t)  # keep Kannada and Devanagari letters and vowel signs
    return re.sub(r"\s+", " ", t).strip()


def detect_type(text: str):
    """Return (type or None, confidence 0-1, scores)."""
    t = " " + _norm(text) + " "
    scores = {}
    for typ, words in LEXICON.items():
        s = 0
        for w, wt in words.items():
            if (" " + w + " ") in t or (len(w) > 4 and w in t):
                s += wt
        scores[typ] = s
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    if scores[best] == 0:
        return None, 0.0, scores
    return best, round(scores[best] / total, 2), scores


def _tags(text: str, table):
    t = " " + _norm(text) + " "
    return [tag for tag, words in table.items()
            if any((" " + w + " ") in t or (len(w) > 4 and w in t) for w in words)]


def concept_tags(text: str):
    return _tags(text, CONCEPTS)


def place_tags(text: str):
    return _tags(text, PLACES)


def _profile(text: str) -> Counter:
    t = _norm(text)
    words = [w for w in t.split() if w not in _STOP]
    grams = Counter()
    for w in words:
        p = f" {w} "
        for i in range(len(p) - 2):
            grams[p[i:i + 3]] += 1
    for tag in concept_tags(text):
        grams["#" + tag] += 2  # same meaning across languages
    for tag in place_tags(text):
        grams["@" + tag] += 6  # same place counts most
    return grams


def _cos(a: Counter, b: Counter) -> float:
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def similarity(a: str, b: str) -> float:
    return _cos(_profile(a), _profile(b))
