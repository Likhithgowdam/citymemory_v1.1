# CityMemory

**Giving every road, drain and streetlight a memory.**
RAISE AI 24-hour Hackathon, Problem Statement 9.

CityMemory links scattered civic complaints to the physical asset they are about, builds each asset's
history (complaints, repairs, money spent), spots repeat failures, predicts the next failure, and ranks
what to fix permanently first. The AI suggests; the engineer decides.

---

## Run it in IntelliJ (about 5 minutes)

1. **Install Python 3.10 or newer** from python.org. On Windows, tick "Add Python to PATH".
2. **Add Python support to IntelliJ:** Settings → Plugins → Marketplace → install **Python**
   (IntelliJ Ultimate) or **Python Community Edition** (IntelliJ Community). Restart IntelliJ.
3. **Open the project:** File → Open → choose the `citymemory` folder.
4. **Set the Python interpreter:** File → Project Structure → SDKs → **+** → Add Python SDK →
   Virtualenv Environment → New → OK. Then in Project Structure → Project, pick that SDK.
   (Or click "Configure Python interpreter" on the yellow bar IntelliJ shows.)
5. **Install the two libraries:** open the **Terminal** tab at the bottom of IntelliJ and run:
   ```
   pip install -r requirements.txt
   ```
6. **Start it:** right-click `run.py` → **Run 'run'**.
7. Open **http://localhost:8000** in Chrome.

No IntelliJ? From a terminal in this folder: `pip install -r requirements.txt` then `python run.py`.

**Teammates on the same Wi-Fi** can open it on their phones at `http://<your-laptop-IP>:8000`
(allow Python through the Windows firewall if asked).

---

## Android app (Android Studio)

The `android` folder is the City Memory phone app. It is a small Kotlin app: the screens come from
the same server (at `/m`), so the phone, the website and the judges always see the same live data.
The Kotlin part adds what a phone needs: GPS, camera and gallery photos, voice typing in Kannada,
English or Hindi, the Back button, and a help screen when the server can't be reached.
It uses no extra libraries, so the first build is quick.

**Build and run (about 10 minutes the first time):**

1. **Start the server on the laptop first:** right-click `run.py` → Run (or `python run.py`).
2. **Find the laptop's IP address.** Windows: open Command Prompt, type `ipconfig`, look for
   "IPv4 Address" (for example `192.168.1.10`). Mac: System Settings → Wi-Fi → Details.
3. **Open the app in Android Studio:** File → Open → choose the **`android`** folder (not the whole
   project). Click "Trust project". Wait for Gradle sync to finish (it downloads Android build tools
   the first time, so it needs internet). If it says SDK 35 is missing, click the "Install" link.
4. **Phone:** Settings → About phone → tap "Build number" 7 times → Developer options → turn on
   "USB debugging". Connect the phone with a USB cable and tap "Allow".
5. Pick your phone in the device list at the top and press the green **Run ▶** button.
6. **First launch:** type the laptop's address, like `http://192.168.1.10:8000`, and tap **Connect**.
   On the Android emulator, tap **Emulator** instead.

**Make an APK to share:** Build → Build App Bundle(s) / APK(s) → Build APK(s) → click "locate".
Send `app-debug.apk` to teammates (WhatsApp or Drive) and allow "Install unknown apps" when asked.

**If the phone can't connect:** the phone and laptop must be on the same network. Venue Wi-Fi often
blocks devices from talking to each other, so the safest choice is: turn on a **phone hotspot**,
connect the laptop to it, run `ipconfig` again and use the new IP. In the app: Me → Change server address.
On Windows, allow Python on "Private networks" when the firewall asks.

**No Android Studio?** Open `http://<laptop-IP>:8000/m` in Chrome on any phone. It shows the same screens.

**What's in the app**

- **Front page and login:** the City Memory logo opens the app, then a simple **Log in** or
  **Create an account** (name, username, password). Accounts are saved on the server in
  `data/users.json` (passwords are stored hashed, never as plain text). The phone remembers the login,
  so next time the app opens straight to Home. A person's complaints follow their account to any phone.
  Resetting the demo data keeps the accounts.

- **Citizens:** choose a language (Kannada, English, Hindi) → tap a picture of the problem → add a photo,
  speak or type → check the place → send. The app says straight away if the city already knows this
  problem ("complaint #9 for this drain"). Then follow it in 5 simple steps, and answer
  **"Was it fixed?"** after the repair. "Problems near you" lets people tap **Me too** instead of
  sending a duplicate complaint.
- **Engineers:** today's list sorted by priority, the new-complaint alert, each asset's history with
  the rain seasons, **Ask AI** for the root cause (with the records it used), **Approve permanent fix**,
  **Log a repair** (patch or permanent, cost, before and after photos), **Review** unclear complaints,
  and a ward map.
- **Me tab:** switch between citizen and engineer, change language, change server address,
  and (engineer) **Reset demo data**.
- **Danger now (citizens):** a red button for an open manhole, a live wire, deep water or a fallen tree.
  It shows as a red DANGER banner at the top of the engineer's Today screen until they tap **Made safe**.
- **Contractor warranty:** every repair records the contractor and guarantee period. The drain page shows
  the days of warranty left, and repairs that **failed within warranty** with the money that can be recovered
  (for SWD-151-07: ₹1.85 lakh from the same contractor).
- **Money: patch again or fix once?** Patching cost per year, the permanent fix cost (an estimate if not done yet),
  the payback time, and the 10-year saving.
- **Ward health score** (0 to 100) for citizens and engineers, from repeat failures, repairs that failed quickly,
  unhappy citizens and open danger reports.
- **Don't dig again:** sample planned works by BWSSB, BESCOM and a gas utility. The drain page warns the engineer,
  and approving or logging a permanent fix there asks for a second tap. Shown as dashed circles on the map.
- **Pre-monsoon list:** tap "at risk before monsoon" on Today to see what to inspect, and by when.
- **Small helpers:** "New update" badges on My complaints, **Share on WhatsApp**, and **send later**: with no
  internet a complaint is saved on the phone and sent automatically when the internet is back.

Contractor names and planned works are made-up sample data for the demo.

- **Live GPS:** report, danger, nearby and Today screens use the phone's real location. Far from the
  sample ward, the app says so and offers "Use the demo spot". The Home header shows the real area name
  (from OpenStreetMap, needs internet on the phone).
- **Bring the sample ward here (engineer, Me tab):** moves the whole sample ward so the bus-stop drain
  SWD-151-07 is where you are standing. Then the full demo works with live GPS anywhere, for example at the venue.
  **Reset demo data** puts it back.
- **Read aloud:** a speaker button on complaints reads the status in Kannada, Hindi or English with the phone's
  voice (English if the phone has no voice for that language).
- **Danger notifications (Android app, engineer phones):** a phone notification with sound when a citizen sends
  a danger alert. It checks every 20 seconds while City Memory is open or was used recently. True background push
  (app fully closed) would need Firebase Cloud Messaging, which is a future step.

**Phone demo (3 minutes), one phone is enough:**

1. Me → Switch to city engineer → Me → **Reset demo data** → Switch to citizen.
2. Report a problem → Drain → take a photo → type or say *"Bus stop hatra road mele neeru nintide"* →
   Send. The app says: **"We already know this drain. Complaint #9."**
3. Me → Switch to city engineer. Today shows the new complaint on top → open SWD-151-07 →
   **Ask AI** → **Approve permanent fix** → **Log a repair**: Permanent fix, ₹6,20,000, after photo → Save.
4. Me → Switch to citizen → My complaints → **Was it fixed? Tell us** → Yes.
5. Show the website: the same drain is now marked as fixed and being watched. One memory, everywhere.

## Turn on Gemini (optional)

The demo works fully offline using built-in rules. To use Google Gemini for understanding complaints
and suggesting root causes:

1. Get a free key at https://aistudio.google.com/apikey
2. Open `.env` and fill in `GEMINI_API_KEY=your-key`
3. Restart `run.py`. The top bar shows **AI: Gemini**.

If Gemini is slow, out of quota or offline, CityMemory quietly falls back to the offline rules,
so the demo never breaks.

## 3-minute demo flow

1. **Reset demo** (top right) so the ward is fresh.
2. **Fix first** tab: point at #1, **SWD-151-07**, a drain at a bus stop, with a "Fix permanently"
   tag. Read its reasons: failed 6 times, ₹4.1 lakh spent, a repair lasted only 43 days.
3. **New complaint** tab → click **Kanglish, bus stop** → **Check complaint**.
   It understands *"Bus stop hatra road mele neeru nintide"* and links it to SWD-151-07:
   *"Complaint #9 at SWD-151-07, failure #7. Last repaired 40 days ago."*
4. Click **Open SWD-151-07's memory**: the timeline shows every complaint and repair, the
   rain seasons, the repairs that did not last, and the **next failure likely: June 2027**.
5. Click **Suggest root cause** → the AI says the outlet is too small and silted, and shows the
   records it used (click a chip to highlight it). Click **Approve permanent fix**. The engineer decides.
6. Optional: **Unclear place** example → goes to **Review** for an engineer to confirm.
   **New place** example → CityMemory starts a new asset.
7. **Spending** tab: how much went on repairs that failed again within a year.

## Project layout

```
citymemory/
├── run.py               start here
├── .env                 settings (Gemini key, demo date, port)
├── requirements.txt
├── backend/
│   ├── app.py           web API (FastAPI)
│   ├── engine.py        matching, asset memory, prediction, ranking
│   ├── text.py          understands English, Kannada and Kanglish complaints
│   ├── ai.py            Gemini + offline fallback for root-cause suggestions
│   └── seed.py          builds the sample Ward 151 data
├── frontend/
│   ├── index.html       the whole dashboard (HTML + CSS + JS)
│   ├── mobile.html      the phone app screens (citizen + engineer), served at /m
│   └── vendor/          map library and fonts, bundled so it works offline
├── android/             Android Studio project (Kotlin): open this folder in Android Studio
│   └── app/src/main/java/com/citymemory/app/MainActivity.kt
└── data/                sample data and uploaded photos (created on first run)
```

## How it works

- **Linking a complaint to an asset:** every nearby asset gets a match score from four signals:
  location (40%), meaning of the words (35%), problem type (15%) and recent activity (10%).
  Above 75% it links automatically; 50 to 75% goes to an engineer to confirm; below 50% starts
  a new asset.
- **Kannada and Kanglish:** words like "water logging", "neeru nintide" and "ನೀರು" map to the same
  meaning, and place words ("bus stop", "ಬಸ್ ನಿಲ್ದಾಣ") count the most.
- **One failure, many complaints:** complaints within 21 days of each other count as one failure.
- **Did the repair last?** For every repair, CityMemory measures the days until the next failure.
- **Prediction:** last failure plus the usual gap between failures; if the asset mostly fails in the
  rains, the prediction moves to the start of the next rainy season.
- **Priority:** how often it fails (35%), money spent (25%), risk to people (25%, e.g. near a school,
  hospital or bus stop) and people affected (15%).

## API (for teammates)

| Method | Path | What it does |
|---|---|---|
| GET | `/api/assets` | All assets, ranked |
| GET | `/api/assets/{id}` | One asset's full memory |
| POST | `/api/complaints` | New complaint `{text, lat, lng, channel}` → linked / review / new asset |
| GET | `/api/review` | Complaints waiting for an engineer |
| POST | `/api/review/{complaint_id}` | `{asset_id}` or `{create_new: true}` |
| POST | `/api/assets/{id}/suggest` | AI root-cause suggestion with evidence |
| POST | `/api/assets/{id}/decision` | `{action: "approve_fix"}` |
| GET | `/api/stats` | Ward totals and spending by department |
| POST | `/api/reset` | Restore the sample ward |
| GET | `/m` | The phone app screens (opened by the Android app) |
| GET | `/api/my?ids=C-0291,C-0292` | A citizen's own complaints, each with its 5-step progress |
| POST | `/api/complaints/{id}/feedback` | "Was it fixed?" answer `{fixed: true}` |
| POST | `/api/assets/{id}/metoo` | "Me too, same problem" `{lat, lng}` |
| GET | `/api/nearby?lat=..&lng=..` | Problems already reported near a place |
| GET | `/api/today` | Engineer's day: new complaints, counts, where to go first |
| POST | `/api/assets/{id}/repairs` | Log a repair `{kind: patch or permanent, cost, note, photo_before, photo_after}` |

`POST /api/complaints` also accepts `type` (the picture the citizen tapped) and `photo` (a data URL).

Interactive API docs: http://localhost:8000/docs

## Splitting the work (team of 3)

- **Person 1, AI and data:** `backend/text.py`, `backend/ai.py`, `backend/seed.py` (Gemini prompts,
  more Kannada words, more realistic sample data).
- **Person 2, backend:** `backend/engine.py`, `backend/app.py` (scoring, prediction, new endpoints).
- **Person 3, dashboard, app and pitch:** `frontend/index.html`, `frontend/mobile.html`, the `android`
  app, the demo flow above, and the slides.

## Notes

- Sample data is made up for the demo. Real use would import the city's complaint exports and
  repair work orders.
- The map background needs internet (OpenStreetMap). Without internet, the asset dots still show.
