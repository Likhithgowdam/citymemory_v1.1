"""Start CityMemory.

In IntelliJ: right-click this file -> Run 'run'. Then open http://localhost:8000
Settings (Gemini key, demo date, port) go in the .env file next to this one.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v:
                    os.environ.setdefault(k.strip(), v)


if __name__ == "__main__":
    load_env()
    import uvicorn
    from backend.app import app

    port = int(os.getenv("PORT", "8000"))
    ai = "Gemini" if os.getenv("GEMINI_API_KEY") else "offline rules (add GEMINI_API_KEY to .env to use Gemini)"
    print(f"\n  CityMemory is running:  http://localhost:{port}")
    print(f"  AI mode: {ai}")
    if os.getenv("CITYMEMORY_TODAY"):
        print(f"  Demo date: {os.getenv('CITYMEMORY_TODAY')}")
    print("  Stop with the red square in IntelliJ (or Ctrl+C)\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
