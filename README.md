# Smart Waste Management & Prediction System — Runnable Prototype

A working academic-project implementation of the SRS (v1.0, Aug 2026) — built with
**Python/Flask + SQLite + HTML/CSS/JS (Leaflet + Chart.js)**, matching the modules,
database schema, roles and page inventory defined in the document.

## 1. Quick Start

```bash
# 1. Install dependencies (a virtual environment is recommended)
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Create and seed the database (Mumbai ward demo data)
python scripts/init_db.py

# 3. Run the app
python app.py
# or: flask --app app run --debug
```

Open **http://127.0.0.1:5000** in your browser. Leaflet and Chart.js are loaded from a
CDN, so an internet connection is needed for the maps/charts to render.

### Demo accounts (seeded automatically)

| Role | Email | Password |
|---|---|---|
| Administrator | admin@swms.gov.in | admin123 |
| Government Operator | operator@swms.gov.in | operator123 |
| Analyst | analyst@swms.gov.in | analyst123 |
| Citizen | citizen@example.com | citizen123 |
| Driver | driver1@swms.gov.in ... driver6@swms.gov.in | driver123 |

To reset all demo data at any point, just re-run `python scripts/init_db.py` (it drops
and recreates `swms.db`).

## 2. What's implemented (mapped to the SRS)

| SRS Section | Feature | Where in code |
|---|---|---|
| 3.1 User Management | Role-based login, session auth, activate/deactivate accounts | `app.py` (`login`, `admin_users`), hashed passwords via Werkzeug |
| 3.2 Citizen Complaint Management | Report form, photo upload, geolocation capture, complaint ID, status tracking | `templates/citizen_report.html`, `citizen_status.html` |
| 3.3 Smart Bin Monitoring | Fill-level table + map, overflow alerts, historical readings, ward/status filters | `templates/bin_monitoring.html`, `logic.py` |
| 3.4 Garbage Truck Tracking | Truck map, task status updates | `templates/truck_tracking.html` |
| 3.5 Waste Image Recognition | **Simulated AI classifier** — analyses uploaded photo colour/brightness to predict waste category, confidence & severity; low-confidence results flagged for review | `logic.py :: classify_waste_image()` |
| 3.6 Hotspot Prediction | Ward risk score = weighted complaint pressure + avg bin fill level | `logic.py :: compute_ward_risk_scores()` |
| 3.7 Route Optimization | Nearest-neighbour route sequencing with priority weighting + haversine distance | `logic.py :: optimize_route()` |
| 3.8 Illegal Dumping Detection | Spatial clustering of repeated open complaints within ~300m | `logic.py :: detect_dumping_clusters()` |
| 3.9–3.12 Government Ops, Analytics, Alerts, Search/Filter | Dashboard, complaint management, analytics charts, alerts inbox | `templates/gov_dashboard.html`, `analytics.html`, `alerts.html` |
| Section 4 | Full relational schema (12 tables, FKs, indexes) | `schema.sql` |
| Section 5 | All 12 pages from the Page Inventory, civic/modern theme | `templates/*.html`, `static/css/style.css` |

## 3. Design notes / honest limitations (say this if asked in a viva)

- **AI classification is a heuristic, not a trained model.** It analyses the average
  colour and brightness of the uploaded photo to pick a plausible waste category and
  confidence score. This matches SRS 2.6 ("hardware feeds may be simulated for the
  academic prototype") and is clearly documented as such — swap in a real CNN
  (e.g. a fine-tuned MobileNet) by replacing `classify_waste_image()` in `logic.py`
  without touching any other code.
- **GPS truck positions and IoT bin readings are seeded/simulated**, not from real
  hardware — also explicitly permitted by SRS 2.6. The `/gov/bins/<id>/reading`
  endpoint simulates an incoming sensor reading so you can demo live updates.
- **Route optimization** uses a nearest-neighbour heuristic over haversine distance,
  not a full TSP solver or a live routing API — appropriate for a prototype per SRS
  4's note that "route distance can be calculated using map coordinates."
- **Database is SQLite**, not MySQL, so graders can run it with zero setup. The schema
  in `schema.sql` uses portable types and maps directly to MySQL if you need to migrate
  (`INT`, `VARCHAR(n)`, `DECIMAL`, `DATETIME` all translate 1:1).
- Passwords are hashed (Werkzeug/Werkzeug's `generate_password_hash`), sessions are
  server-side cookies — adequate for a prototype but not hardened for production
  (no HTTPS enforcement, no rate limiting, no CSRF tokens on forms).

## 4. Project structure

```
swms/
├── app.py              # Flask routes/controllers for all 12 pages + APIs
├── logic.py             # AI classifier, hotspot scoring, route optimizer, dumping detector
├── schema.sql            # Full DB schema (SRS Section 4)
├── requirements.txt
├── scripts/
│   └── init_db.py        # Creates + seeds swms.db with Mumbai demo data
├── static/
│   ├── css/style.css      # Civic/modern theme (SRS 5.1)
│   └── uploads/           # Citizen-submitted photos
└── templates/             # One .html per SRS page (12 pages) + base layout
```

## 5. Suggested next steps for a stronger submission

- Add unit tests for `logic.py` (hotspot scoring, route optimizer) — good for the
  "Testing & Test Cases" section (SRS Section 9).
- Swap `classify_waste_image()` for a small trained image classifier if you want a
  genuine ML component rather than a heuristic.
- Deploy to Render/Railway/PythonAnywhere for a live demo link during evaluation.
