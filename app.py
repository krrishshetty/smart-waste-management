import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (Flask, g, render_template, request, redirect, url_for,
                    session, flash, jsonify, send_from_directory)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import logic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "swms.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

# Flask application setup
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "dev-secret-key-change-in-production"
)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB uploads

UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(UPLOAD_DIR, exist_ok=True)


class RowJSONProvider(app.json_provider_class):
    """Allow templates to serialize sqlite3.Row objects with |tojson."""
    def default(self, o):
        if isinstance(o, sqlite3.Row):
            return dict(o)
        return super().default(o)


app.json = RowJSONProvider(app)
def init_db():
    with sqlite3.connect(DB_PATH) as db:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            db.executescript(f.read())


def create_admin():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("PRAGMA foreign_keys = ON")

        db.execute(
            "INSERT OR IGNORE INTO role (role_name) VALUES (?)",
            ("Administrator",)
        )

        role_id = db.execute(
            "SELECT role_id FROM role WHERE role_name = ?",
            ("Administrator",)
        ).fetchone()[0]

        admin_password = generate_password_hash("admin123")

        existing_admin = db.execute(
            "SELECT user_id FROM user WHERE email = ?",
            ("admin@swms.gov.in",)
        ).fetchone()

        if existing_admin:
            db.execute("""
                UPDATE user
                SET name = ?, password = ?, role_id = ?, status = 'Active'
                WHERE email = ?
            """, (
                "System Admin",
                admin_password,
                role_id,
                "admin@swms.gov.in"
            ))
        else:
            db.execute("""
                INSERT INTO user
                (name, email, password, role_id, status)
                VALUES (?, ?, ?, ?, 'Active')
            """, (
                "System Admin",
                "admin@swms.gov.in",
                admin_password,
                role_id
            ))

        db.commit()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


# Create the database tables first, then create the default administrator.
init_db()
create_admin()


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def log_action(action, entity_type=None, entity_id=None):
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
        (session.get("user_id"), action, entity_type, entity_id),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login", next=request.path))
            if session.get("role_name") not in allowed_roles:
                flash("You don't have access to that page.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def inject_user():
    return {
        "current_user": {
            "id": session.get("user_id"),
            "name": session.get("user_name"),
            "role": session.get("role_name"),
        },
        "now": datetime.utcnow(),
    }


# ---------------------------------------------------------------------------
# Page 1 -- Login
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            """SELECT u.*, r.role_name FROM user u JOIN role r ON u.role_id = r.role_id
               WHERE lower(u.email) = ?""", (email,)
        ).fetchone()
        if user is None or not check_password_hash(user["password"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")
        if user["status"] != "Active":
            flash("This account has been deactivated. Contact the administrator.", "error")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user["user_id"]
        session["user_name"] = user["name"]
        session["role_name"] = user["role_name"]
        log_action("Login")
        nxt = request.args.get("next")
        return redirect(nxt or url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    if "user_id" in session:
        log_action("Logout")
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard router (role-specific landing, SRS 5.2 #4)
# ---------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    role = session.get("role_name")
    if role == "Citizen":
        return redirect(url_for("citizen_status"))
    if role == "Driver":
        return redirect(url_for("route_planning"))
    return redirect(url_for("gov_dashboard"))


# ---------------------------------------------------------------------------
# Page 2 -- Citizen Report (SRS 3.2, 5.3 Page 2)
# ---------------------------------------------------------------------------
@app.route("/report", methods=["GET", "POST"])
@roles_required("Citizen")
def citizen_report():
    db = get_db()
    if request.method == "POST":
        description = request.form.get("description", "").strip()
        latitude = request.form.get("latitude") or None
        longitude = request.form.get("longitude") or None
        ward_id = request.form.get("ward_id") or None

        if not description:
            flash("Please describe the issue.", "error")
            return redirect(url_for("citizen_report"))

        image_path = None
        file = request.files.get("image")
        if file and file.filename and "." in file.filename and \
                file.filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT:
            filename = secure_filename(f"{datetime.utcnow().timestamp()}_{file.filename}")
            file.save(os.path.join(UPLOAD_DIR, filename))
            image_path = filename

        cur = db.execute(
            """INSERT INTO complaint (reported_by, description, image_path, latitude, longitude, ward_id, status)
               VALUES (?, ?, ?, ?, ?, ?, 'New')""",
            (session["user_id"], description, image_path, latitude, longitude, ward_id),
        )
        complaint_id = cur.lastrowid
        db.commit()

        if image_path:
            result = logic.classify_waste_image(os.path.join(UPLOAD_DIR, image_path))
            db.execute(
                """INSERT INTO waste_image_analysis (complaint_id, waste_type, confidence, severity, analysed_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (complaint_id, result["waste_type"], result["confidence"], result["severity"],
                 datetime.utcnow()),
            )
            if result["severity"] in ("High",):
                db.execute(
                    """INSERT INTO alert (alert_type, reference_id, message, severity, status)
                       VALUES ('Overflow', ?, ?, 'High', 'New')""",
                    (complaint_id, f"High-severity waste report at complaint #{complaint_id}"),
                )
            db.commit()

        log_action("Submitted complaint", "complaint", complaint_id)
        flash(f"Report submitted. Your complaint ID is #{complaint_id}.", "success")
        return redirect(url_for("citizen_status"))

    wards = db.execute("SELECT * FROM ward ORDER BY ward_name").fetchall()
    return render_template("citizen_report.html", wards=wards)


# ---------------------------------------------------------------------------
# Page 3 -- Complaint Status (SRS 5.3 Page 3)
# ---------------------------------------------------------------------------
@app.route("/my-complaints")
@roles_required("Citizen")
def citizen_status():
    db = get_db()
    complaints = db.execute(
        """SELECT c.*, w.ward_name,
                  a.waste_type, a.confidence, a.severity
           FROM complaint c
           LEFT JOIN ward w ON c.ward_id = w.ward_id
           LEFT JOIN waste_image_analysis a ON a.complaint_id = c.complaint_id
           WHERE c.reported_by = ?
           ORDER BY c.created_at DESC""",
        (session["user_id"],),
    ).fetchall()
    return render_template("citizen_status.html", complaints=complaints)


# ---------------------------------------------------------------------------
# Page 4 -- Government Dashboard (SRS 3.9, 5.3 Page 4)
# ---------------------------------------------------------------------------
@app.route("/gov/dashboard")
@roles_required("Administrator", "Government Operator", "Analyst")
def gov_dashboard():
    db = get_db()
    stats = {
        "active_complaints": db.execute(
            "SELECT COUNT(*) c FROM complaint WHERE status NOT IN ('Resolved')").fetchone()["c"],
        "overflow_bins": db.execute(
            "SELECT COUNT(*) c FROM smart_bin WHERE status = 'Overflow'").fetchone()["c"],
        "warning_bins": db.execute(
            "SELECT COUNT(*) c FROM smart_bin WHERE status = 'Warning'").fetchone()["c"],
        "active_trucks": db.execute(
            "SELECT COUNT(*) c FROM garbage_truck WHERE status = 'Active'").fetchone()["c"],
        "unresolved_alerts": db.execute(
            "SELECT COUNT(*) c FROM alert WHERE status != 'Resolved'").fetchone()["c"],
    }
    risk_scores = logic.compute_ward_risk_scores(db)
    top_hotspots = risk_scores[:5]

    bins = db.execute(
        "SELECT bin_id, latitude, longitude, fill_level, status, label FROM smart_bin").fetchall()
    trucks = db.execute(
        """SELECT t.truck_id, t.registration_no, t.latitude, t.longitude, t.status, u.name as driver_name
           FROM garbage_truck t LEFT JOIN user u ON t.driver_id = u.user_id
           WHERE t.latitude IS NOT NULL""").fetchall()
    complaints = db.execute(
        "SELECT complaint_id, latitude, longitude, priority, status FROM complaint WHERE latitude IS NOT NULL"
    ).fetchall()

    recent_complaints = db.execute(
        """SELECT c.complaint_id, c.description, c.priority, c.status, c.created_at, w.ward_name
           FROM complaint c LEFT JOIN ward w ON c.ward_id = w.ward_id
           ORDER BY c.created_at DESC LIMIT 6"""
    ).fetchall()

    return render_template(
        "gov_dashboard.html", stats=stats, top_hotspots=top_hotspots,
        bins=bins, trucks=trucks, complaints=complaints, recent_complaints=recent_complaints,
    )


# ---------------------------------------------------------------------------
# Page 5 -- Complaint Management (SRS 3.2, 3.9, 5.3 Page 5)
# ---------------------------------------------------------------------------
@app.route("/gov/complaints", methods=["GET"])
@roles_required("Administrator", "Government Operator")
def complaint_management():
    db = get_db()
    status_filter = request.args.get("status", "")
    ward_filter = request.args.get("ward_id", "")
    q = request.args.get("q", "").strip()

    sql = """SELECT c.*, w.ward_name, u.name as citizen_name
              FROM complaint c
              LEFT JOIN ward w ON c.ward_id = w.ward_id
              LEFT JOIN user u ON c.reported_by = u.user_id
              WHERE 1=1"""
    params = []
    if status_filter:
        sql += " AND c.status = ?"
        params.append(status_filter)
    if ward_filter:
        sql += " AND c.ward_id = ?"
        params.append(ward_filter)
    if q:
        sql += " AND (CAST(c.complaint_id AS TEXT) LIKE ? OR c.description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY CASE c.priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, c.created_at DESC"

    complaints = db.execute(sql, params).fetchall()
    wards = db.execute("SELECT * FROM ward ORDER BY ward_name").fetchall()
    trucks = db.execute("SELECT * FROM garbage_truck ORDER BY registration_no").fetchall()
    return render_template("complaint_management.html", complaints=complaints, wards=wards,
                            trucks=trucks, status_filter=status_filter, ward_filter=ward_filter, q=q)


@app.route("/gov/complaints/<int:complaint_id>/update", methods=["POST"])
@roles_required("Administrator", "Government Operator")
def update_complaint(complaint_id):
    db = get_db()
    new_status = request.form.get("status")
    new_priority = request.form.get("priority")
    truck_id = request.form.get("truck_id")

    if new_status:
        db.execute("UPDATE complaint SET status = ?, updated_at = ? WHERE complaint_id = ?",
                   (new_status, datetime.utcnow(), complaint_id))
    if new_priority:
        db.execute("UPDATE complaint SET priority = ? WHERE complaint_id = ?", (new_priority, complaint_id))

    if truck_id:
        db.execute(
            """INSERT INTO collection_task (truck_id, complaint_id, priority, status)
               VALUES (?, ?, (SELECT priority FROM complaint WHERE complaint_id = ?), 'Assigned')""",
            (truck_id, complaint_id, complaint_id),
        )
        db.execute("UPDATE complaint SET status = 'Assigned' WHERE complaint_id = ?", (complaint_id,))

    db.commit()
    log_action(f"Updated complaint #{complaint_id}", "complaint", complaint_id)
    flash(f"Complaint #{complaint_id} updated.", "success")
    return redirect(url_for("complaint_management"))


# ---------------------------------------------------------------------------
# Page 6 -- Smart Bin Monitoring (SRS 3.3, 5.3 Page 6)
# ---------------------------------------------------------------------------
@app.route("/gov/bins")
@roles_required("Administrator", "Government Operator", "Analyst")
def bin_monitoring():
    db = get_db()
    ward_filter = request.args.get("ward_id", "")
    status_filter = request.args.get("status", "")
    sql = """SELECT b.*, w.ward_name FROM smart_bin b LEFT JOIN ward w ON b.ward_id = w.ward_id WHERE 1=1"""
    params = []
    if ward_filter:
        sql += " AND b.ward_id = ?"
        params.append(ward_filter)
    if status_filter:
        sql += " AND b.status = ?"
        params.append(status_filter)
    sql += " ORDER BY b.fill_level DESC"
    bins = db.execute(sql, params).fetchall()
    wards = db.execute("SELECT * FROM ward ORDER BY ward_name").fetchall()
    return render_template("bin_monitoring.html", bins=bins, wards=wards,
                            ward_filter=ward_filter, status_filter=status_filter)


@app.route("/gov/bins/<int:bin_id>/reading", methods=["POST"])
@roles_required("Administrator", "Government Operator")
def add_bin_reading(bin_id):
    """Simulates an incoming IoT fill-level reading (SRS 2.6: sensor feeds may be simulated)."""
    db = get_db()
    fill_level = float(request.form.get("fill_level", 0))
    fill_level = max(0, min(100, fill_level))
    status = "Overflow" if fill_level >= 90 else ("Warning" if fill_level >= 70 else "Normal")

    db.execute("INSERT INTO bin_reading (bin_id, fill_level) VALUES (?, ?)", (bin_id, fill_level))
    db.execute("UPDATE smart_bin SET fill_level = ?, status = ?, last_reading = ? WHERE bin_id = ?",
               (fill_level, status, datetime.utcnow(), bin_id))
    if status == "Overflow":
        db.execute(
            """INSERT INTO alert (alert_type, reference_id, message, severity, status)
               VALUES ('Overflow', ?, ?, 'High', 'New')""",
            (bin_id, f"Bin #{bin_id} has reached overflow threshold ({fill_level:.0f}%)"),
        )
    db.commit()
    log_action(f"Recorded bin reading for #{bin_id}: {fill_level}%", "smart_bin", bin_id)
    flash(f"Reading recorded for bin #{bin_id}.", "success")
    return redirect(url_for("bin_monitoring"))


# ---------------------------------------------------------------------------
# Page 7 -- Truck Tracking (SRS 3.4, 5.3 Page 7)
# ---------------------------------------------------------------------------
@app.route("/gov/trucks")
@roles_required("Administrator", "Government Operator", "Driver")
def truck_tracking():
    db = get_db()
    trucks = db.execute(
        """SELECT t.*, u.name as driver_name, w.ward_name
           FROM garbage_truck t
           LEFT JOIN user u ON t.driver_id = u.user_id
           LEFT JOIN ward w ON t.ward_id = w.ward_id
           ORDER BY t.status, t.registration_no"""
    ).fetchall()
    tasks = db.execute(
        """SELECT ct.*, t.registration_no, c.description
           FROM collection_task ct
           JOIN garbage_truck t ON ct.truck_id = t.truck_id
           LEFT JOIN complaint c ON ct.complaint_id = c.complaint_id
           WHERE ct.status != 'Completed'
           ORDER BY ct.truck_id, ct.route_order"""
    ).fetchall()
    return render_template("truck_tracking.html", trucks=trucks, tasks=tasks)


@app.route("/gov/tasks/<int:task_id>/status", methods=["POST"])
@roles_required("Administrator", "Government Operator", "Driver")
def update_task_status(task_id):
    db = get_db()
    new_status = request.form.get("status")
    db.execute("UPDATE collection_task SET status = ?, completed_at = ? WHERE task_id = ?",
               (new_status, datetime.utcnow() if new_status == "Completed" else None, task_id))
    if new_status == "Completed":
        row = db.execute("SELECT complaint_id FROM collection_task WHERE task_id = ?", (task_id,)).fetchone()
        if row and row["complaint_id"]:
            db.execute("UPDATE complaint SET status = 'Collected', updated_at = ? WHERE complaint_id = ?",
                       (datetime.utcnow(), row["complaint_id"]))
    db.commit()
    log_action(f"Task #{task_id} -> {new_status}", "collection_task", task_id)
    flash("Task status updated.", "success")
    return redirect(request.referrer or url_for("truck_tracking"))


# ---------------------------------------------------------------------------
# Page 8 -- Hotspot & Heatmap (SRS 3.6, 3.8, 5.3 Page 8)
# ---------------------------------------------------------------------------
@app.route("/gov/hotspots")
@roles_required("Administrator", "Government Operator", "Analyst")
def hotspots():
    db = get_db()
    risk_scores = logic.compute_ward_risk_scores(db)
    dumping_clusters = logic.detect_dumping_clusters(db)
    wards = {w["ward_id"]: w for w in db.execute("SELECT * FROM ward").fetchall()}
    bins = db.execute("SELECT bin_id, latitude, longitude, fill_level, status, label FROM smart_bin").fetchall()
    return render_template("hotspots.html", risk_scores=risk_scores,
                            dumping_clusters=dumping_clusters, wards=wards, bins=bins)


@app.route("/gov/hotspots/recompute", methods=["POST"])
@roles_required("Administrator", "Government Operator", "Analyst")
def recompute_hotspots():
    db = get_db()
    logic.save_hotspot_predictions(db)
    log_action("Recomputed hotspot predictions")
    flash("Hotspot predictions recalculated and logged.", "success")
    return redirect(url_for("hotspots"))


# ---------------------------------------------------------------------------
# Page 9 -- Route Planning (SRS 3.7, 5.3 Page 9)
# ---------------------------------------------------------------------------
@app.route("/gov/routes", methods=["GET"])
@roles_required("Administrator", "Government Operator", "Driver")
def route_planning():
    db = get_db()
    trucks = db.execute(
        "SELECT * FROM garbage_truck WHERE status != 'Maintenance' ORDER BY registration_no").fetchall()
    selected_truck_id = request.args.get("truck_id", type=int)
    route = None
    total_km = None
    if selected_truck_id:
        truck = db.execute("SELECT * FROM garbage_truck WHERE truck_id = ?", (selected_truck_id,)).fetchone()
        stops = db.execute(
            """SELECT c.complaint_id as id, c.latitude, c.longitude, c.priority, c.description
               FROM collection_task ct JOIN complaint c ON ct.complaint_id = c.complaint_id
               WHERE ct.truck_id = ? AND ct.status != 'Completed' AND c.latitude IS NOT NULL""",
            (selected_truck_id,),
        ).fetchall()
        stops = [dict(s) for s in stops]
        if truck and stops:
            route, total_km = logic.optimize_route(truck["latitude"], truck["longitude"], stops)
            for stop in route:
                db.execute(
                    "UPDATE collection_task SET route_order = ? WHERE truck_id = ? AND complaint_id = ?",
                    (stop["route_order"], selected_truck_id, stop["id"]),
                )
            db.commit()
    return render_template("route_planning.html", trucks=trucks, selected_truck_id=selected_truck_id,
                            route=route, total_km=total_km)


# ---------------------------------------------------------------------------
# Page 10 -- Analytics & Reports (SRS 3.10, 5.3 Page 10)
# ---------------------------------------------------------------------------
@app.route("/gov/analytics")
@roles_required("Administrator", "Government Operator", "Analyst")
def analytics():
    db = get_db()
    trend = db.execute(
        """SELECT date(created_at) as d, COUNT(*) as c FROM complaint
           GROUP BY date(created_at) ORDER BY d"""
    ).fetchall()
    ward_perf = db.execute(
        """SELECT w.ward_name,
                  COUNT(c.complaint_id) as total,
                  SUM(CASE WHEN c.status = 'Resolved' THEN 1 ELSE 0 END) as resolved
           FROM ward w LEFT JOIN complaint c ON c.ward_id = w.ward_id
           GROUP BY w.ward_id ORDER BY total DESC"""
    ).fetchall()
    category_split = db.execute(
        """SELECT waste_type, COUNT(*) as c FROM waste_image_analysis GROUP BY waste_type"""
    ).fetchall()
    total_complaints = db.execute("SELECT COUNT(*) c FROM complaint").fetchone()["c"]
    resolved = db.execute("SELECT COUNT(*) c FROM complaint WHERE status='Resolved'").fetchone()["c"]
    resolution_rate = round((resolved / total_complaints) * 100, 1) if total_complaints else 0

    return render_template("analytics.html", trend=trend, ward_perf=ward_perf,
                            category_split=category_split, resolution_rate=resolution_rate,
                            total_complaints=total_complaints, resolved=resolved)


# ---------------------------------------------------------------------------
# Page 11 -- Alerts (SRS 3.11, 5.3 Page 11)
# ---------------------------------------------------------------------------
@app.route("/gov/alerts")
@roles_required("Administrator", "Government Operator")
def alerts_page():
    db = get_db()
    status_filter = request.args.get("status", "")
    sql = "SELECT * FROM alert WHERE 1=1"
    params = []
    if status_filter:
        sql += " AND status = ?"
        params.append(status_filter)
    sql += " ORDER BY CASE severity WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, created_at DESC"
    alerts = db.execute(sql, params).fetchall()
    return render_template("alerts.html", alerts=alerts, status_filter=status_filter)


@app.route("/gov/alerts/<int:alert_id>/resolve", methods=["POST"])
@roles_required("Administrator", "Government Operator")
def resolve_alert(alert_id):
    db = get_db()
    db.execute("UPDATE alert SET status = 'Resolved' WHERE alert_id = ?", (alert_id,))
    db.commit()
    log_action(f"Resolved alert #{alert_id}", "alert", alert_id)
    flash("Alert marked resolved.", "success")
    return redirect(url_for("alerts_page"))


# ---------------------------------------------------------------------------
# Page 12 -- Profile / Settings
# ---------------------------------------------------------------------------
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        if new_password:
            if len(new_password) < 6:
                flash("Password must be at least 6 characters.", "error")
            else:
                db.execute("UPDATE user SET password = ? WHERE user_id = ?",
                           (generate_password_hash(new_password), session["user_id"]))
                db.commit()
                log_action("Changed password")
                flash("Password updated.", "success")
        return redirect(url_for("profile"))
    user = db.execute("SELECT * FROM user WHERE user_id = ?", (session["user_id"],)).fetchone()
    return render_template("profile.html", user=user)


# Admin-only: user management (extends Page 12 for Administrator role, SRS 3.1)
@app.route("/admin/users")
@roles_required("Administrator")
def admin_users():
    db = get_db()
    users = db.execute(
        """SELECT u.*, r.role_name FROM user u JOIN role r ON u.role_id = r.role_id ORDER BY u.name"""
    ).fetchall()
    roles = db.execute("SELECT * FROM role ORDER BY role_name").fetchall()
    return render_template("admin_users.html", users=users, roles=roles)


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@roles_required("Administrator")
def toggle_user(user_id):
    db = get_db()
    u = db.execute("SELECT status FROM user WHERE user_id = ?", (user_id,)).fetchone()
    new_status = "Inactive" if u["status"] == "Active" else "Active"
    db.execute("UPDATE user SET status = ? WHERE user_id = ?", (new_status, user_id))
    db.commit()
    log_action(f"Set user #{user_id} to {new_status}", "user", user_id)
    flash("User status updated.", "success")
    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
# JSON endpoints used by dashboard map / charts (lightweight "API layer")
# ---------------------------------------------------------------------------
@app.route("/api/hotspot-scores")
@login_required
def api_hotspot_scores():
    db = get_db()
    return jsonify(logic.compute_ward_risk_scores(db))


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="Access denied."), 403


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print("Database not found. Run: python scripts/init_db.py")
    app.run(debug=True, host="0.0.0.0", port=5000)
