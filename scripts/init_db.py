"""
Initializes swms.db from schema.sql and seeds it with realistic demo data
(Mumbai wards) so the prototype is demoable immediately after setup.

Run from the project root:
    python scripts/init_db.py
"""
import os
import random
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "swms.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

random.seed(42)

WARDS = [
    ("A Ward - Colaba", "Mumbai", "South Mumbai"),
    ("D Ward - Malabar Hill", "Mumbai", "South Mumbai"),
    ("F/N Ward - Matunga", "Mumbai", "Central Mumbai"),
    ("G/N Ward - Dadar", "Mumbai", "Central Mumbai"),
    ("H/E Ward - Bandra East", "Mumbai", "Western Suburbs"),
    ("K/W Ward - Andheri West", "Mumbai", "Western Suburbs"),
    ("P/N Ward - Malad", "Mumbai", "Western Suburbs"),
    ("L Ward - Kurla", "Mumbai", "Eastern Suburbs"),
    ("N Ward - Ghatkopar", "Mumbai", "Eastern Suburbs"),
    ("S Ward - Bhandup", "Mumbai", "Eastern Suburbs"),
]

# Approx bounding boxes per ward for scattering demo points (lat, lon)
WARD_CENTERS = [
    (18.9067, 72.8147), (18.9548, 72.7999), (19.0272, 72.8547),
    (19.0176, 72.8425), (19.0596, 72.8656), (19.1364, 72.8296),
    (19.1874, 72.8484), (19.0728, 72.8826), (19.0864, 72.9081),
    (19.1436, 72.9370),
]

WASTE_TYPES = ["Plastic", "Wet/Organic", "Dry/Recyclable", "Construction Debris", "E-Waste", "Mixed"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
COMPLAINT_STATUSES = ["New", "Assigned", "Collected", "Resolved"]

FIRST_NAMES = ["Aarav", "Vivaan", "Isha", "Ananya", "Rohan", "Sneha", "Kabir", "Meera",
               "Arjun", "Diya", "Rahul", "Priya", "Karan", "Neha", "Aditya", "Pooja"]
LAST_NAMES = ["Shah", "Mehta", "Iyer", "Kulkarni", "Nair", "Rao", "Patil", "Desai", "Joshi", "Bhosale"]


def jitter(lat, lon, spread=0.012):
    return round(lat + random.uniform(-spread, spread), 7), round(lon + random.uniform(-spread, spread), 7)


def random_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    cur = conn.cursor()

    # --- Roles ---
    roles = ["Administrator", "Government Operator", "Driver", "Citizen", "Analyst"]
    for r in roles:
        cur.execute("INSERT INTO role (role_name) VALUES (?)", (r,))
    role_id = {name: i + 1 for i, name in enumerate(roles)}

    # --- Wards ---
    for name, city, zone in WARDS:
        cur.execute("INSERT INTO ward (ward_name, city, zone) VALUES (?, ?, ?)", (name, city, zone))

    # --- Users ---
    demo_users = [
        ("Admin User", "admin@swms.gov.in", "Administrator", "admin123"),
        ("Operator Singh", "operator@swms.gov.in", "Government Operator", "operator123"),
        ("Ritika Analyst", "analyst@swms.gov.in", "Analyst", "analyst123"),
        ("Demo Citizen", "citizen@example.com", "Citizen", "citizen123"),
    ]
    user_ids = {}
    for name, email, role, pwd in demo_users:
        cur.execute(
            "INSERT INTO user (name, email, password, role_id, status) VALUES (?, ?, ?, ?, 'Active')",
            (name, email, generate_password_hash(pwd), role_id[role]),
        )
        user_ids[email] = cur.lastrowid

    # extra citizens
    citizen_ids = [user_ids["citizen@example.com"]]
    for i in range(8):
        name = random_name()
        email = f"citizen{i+1}@example.com"
        cur.execute(
            "INSERT INTO user (name, email, password, role_id, status) VALUES (?, ?, ?, ?, 'Active')",
            (name, email, generate_password_hash("citizen123"), role_id["Citizen"]),
        )
        citizen_ids.append(cur.lastrowid)

    # drivers
    driver_ids = []
    for i in range(6):
        name = random_name()
        email = f"driver{i+1}@swms.gov.in"
        cur.execute(
            "INSERT INTO user (name, email, password, role_id, status) VALUES (?, ?, ?, ?, 'Active')",
            (name, email, generate_password_hash("driver123"), role_id["Driver"]),
        )
        driver_ids.append(cur.lastrowid)

    conn.commit()

    # --- Smart bins (6-9 per ward) ---
    bin_ids_by_ward = {i + 1: [] for i in range(len(WARDS))}
    for wi, (lat, lon) in enumerate(WARD_CENTERS):
        ward_id = wi + 1
        for b in range(random.randint(6, 9)):
            blat, blon = jitter(lat, lon)
            fill = round(random.uniform(5, 98), 1)
            status = "Overflow" if fill >= 90 else ("Warning" if fill >= 70 else "Normal")
            cur.execute(
                """INSERT INTO smart_bin (ward_id, label, latitude, longitude, capacity, fill_level, last_reading, status)
                   VALUES (?, ?, ?, ?, 240, ?, ?, ?)""",
                (ward_id, f"Bin {ward_id}-{b+1}", blat, blon, fill,
                 datetime.utcnow() - timedelta(minutes=random.randint(5, 600)), status),
            )
            bin_id = cur.lastrowid
            bin_ids_by_ward[ward_id].append(bin_id)
            # a few historical readings per bin
            for h in range(4):
                hist_fill = max(0, fill - random.uniform(5, 25) * (4 - h))
                cur.execute(
                    "INSERT INTO bin_reading (bin_id, fill_level, recorded_at) VALUES (?, ?, ?)",
                    (bin_id, round(hist_fill, 1), datetime.utcnow() - timedelta(hours=(4 - h) * 6)),
                )

    # --- Garbage trucks ---
    reg_prefixes = ["MH-01", "MH-02", "MH-03", "MH-04"]
    truck_ids = []
    for i, driver_id in enumerate(driver_ids):
        ward_id = (i % len(WARDS)) + 1
        lat, lon = jitter(*WARD_CENTERS[ward_id - 1])
        status = random.choice(["Active", "Active", "Available", "Maintenance"])
        reg_no = f"{random.choice(reg_prefixes)}-GB-{1000+i}"
        cur.execute(
            """INSERT INTO garbage_truck (registration_no, driver_id, ward_id, status, latitude, longitude, last_update)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (reg_no, driver_id, ward_id, status, lat, lon, datetime.utcnow() - timedelta(minutes=random.randint(1, 60))),
        )
        truck_ids.append(cur.lastrowid)

    # --- Complaints (with some image analysis + alerts + tasks) ---
    complaint_ids = []
    for i in range(45):
        ward_idx = random.randint(0, len(WARDS) - 1)
        ward_id = ward_idx + 1
        lat, lon = jitter(*WARD_CENTERS[ward_idx], spread=0.01)
        citizen_id = random.choice(citizen_ids)
        status = random.choices(COMPLAINT_STATUSES, weights=[25, 20, 20, 35])[0]
        priority = random.choices(PRIORITIES, weights=[20, 40, 30, 10])[0]
        created = datetime.utcnow() - timedelta(days=random.randint(0, 21), hours=random.randint(0, 23))
        descriptions = [
            "Overflowing garbage bin near the market entrance.",
            "Construction debris dumped on the footpath.",
            "Plastic waste scattered near the bus stop.",
            "Wet waste not collected for 3 days near the housing society.",
            "Illegal dumping spotted behind the community hall.",
            "E-waste left unattended near the school compound.",
            "Garbage pile blocking the storm drain.",
            "Mixed waste dumped near the children's park.",
        ]
        cur.execute(
            """INSERT INTO complaint (reported_by, description, image_path, latitude, longitude, ward_id, priority, status, created_at, updated_at)
               VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
            (citizen_id, random.choice(descriptions), lat, lon, ward_id, priority, status, created, created),
        )
        cid = cur.lastrowid
        complaint_ids.append(cid)

        if random.random() < 0.7:
            waste_type = random.choice(WASTE_TYPES)
            confidence = round(random.uniform(45, 96), 2)
            severity = "High" if confidence > 80 else ("Medium" if confidence > 60 else "Low")
            cur.execute(
                """INSERT INTO waste_image_analysis (complaint_id, waste_type, confidence, severity, analysed_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (cid, waste_type, confidence, severity, created + timedelta(minutes=2)),
            )

        if status in ("Assigned", "Collected"):
            truck_id = random.choice(truck_ids)
            task_status = "Completed" if status == "Collected" else random.choice(["Assigned", "In Progress"])
            cur.execute(
                """INSERT INTO collection_task (truck_id, complaint_id, priority, status, assigned_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (truck_id, cid, priority, task_status, created + timedelta(hours=2),
                 created + timedelta(hours=6) if task_status == "Completed" else None),
            )

        if priority in ("High", "Critical") and random.random() < 0.5:
            cur.execute(
                """INSERT INTO alert (alert_type, reference_id, message, severity, status, created_at)
                   VALUES ('Dumping', ?, ?, ?, ?, ?)""",
                (cid, f"Repeated dumping pattern flagged near complaint #{cid}",
                 "High" if priority == "Critical" else "Medium",
                 random.choice(["New", "Seen", "Resolved"]), created),
            )

    # Overflow alerts for current overflow bins
    cur.execute("SELECT bin_id, fill_level FROM smart_bin WHERE status = 'Overflow'")
    for row in cur.fetchall():
        cur.execute(
            """INSERT INTO alert (alert_type, reference_id, message, severity, status)
               VALUES ('Overflow', ?, ?, 'High', ?)""",
            (row["bin_id"], f"Bin #{row['bin_id']} overflowing at {row['fill_level']}%",
             random.choice(["New", "Seen"])),
        )

    conn.commit()

    # --- Initial hotspot predictions ---
    import sys
    sys.path.insert(0, BASE_DIR)
    import logic  # noqa: E402
    logic.save_hotspot_predictions(conn)

    conn.commit()
    conn.close()

    print(f"Database created at {DB_PATH}")
    print("\nDemo login accounts (all seeded, ready to use):")
    print("  Administrator      admin@swms.gov.in       / admin123")
    print("  Government Operator operator@swms.gov.in   / operator123")
    print("  Analyst            analyst@swms.gov.in      / analyst123")
    print("  Citizen            citizen@example.com      / citizen123")
    print("  (Driver accounts:  driver1@swms.gov.in ... driver6@swms.gov.in / driver123)")


if __name__ == "__main__":
    main()
