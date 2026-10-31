-- Smart Waste Management & Prediction System
-- Database schema (matches SRS Section 4: Database Design)
-- Written for SQLite (prototype). Field types map 1:1 to MySQL if you migrate later:
--   INT -> INT, VARCHAR(n) -> VARCHAR(n), DECIMAL -> DECIMAL(10,2), DATETIME -> DATETIME, TEXT -> TEXT

PRAGMA foreign_keys = ON;

-- 4.1 ROLE
CREATE TABLE IF NOT EXISTS role (
    role_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    role_name   VARCHAR(50) NOT NULL UNIQUE   -- Admin, Operator, Driver, Citizen, Analyst
);

-- 4.2 USER
CREATE TABLE IF NOT EXISTS user (
    user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(100) NOT NULL,
    email       VARCHAR(100) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,        -- hashed
    role_id     INTEGER NOT NULL,
    status      VARCHAR(30) NOT NULL DEFAULT 'Active',  -- Active / Inactive
    FOREIGN KEY (role_id) REFERENCES role(role_id)
);

-- 4.3 WARD
CREATE TABLE IF NOT EXISTS ward (
    ward_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ward_name   VARCHAR(100) NOT NULL,
    city        VARCHAR(100) NOT NULL,
    zone        VARCHAR(100)
);

-- 4.4 COMPLAINT
CREATE TABLE IF NOT EXISTS complaint (
    complaint_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    reported_by   INTEGER NOT NULL,
    description   TEXT NOT NULL,
    image_path    VARCHAR(255),
    latitude      DECIMAL(10,7),
    longitude     DECIMAL(10,7),
    ward_id       INTEGER,
    priority      VARCHAR(30) DEFAULT 'Medium',   -- Low / Medium / High / Critical
    status        VARCHAR(30) DEFAULT 'New',      -- New / Assigned / Collected / Resolved
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (reported_by) REFERENCES user(user_id),
    FOREIGN KEY (ward_id) REFERENCES ward(ward_id)
);

-- 4.5 SMART_BIN
CREATE TABLE IF NOT EXISTS smart_bin (
    bin_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ward_id       INTEGER NOT NULL,
    label         VARCHAR(100),
    latitude      DECIMAL(10,7) NOT NULL,
    longitude     DECIMAL(10,7) NOT NULL,
    capacity      DECIMAL(10,2) DEFAULT 100,
    fill_level    DECIMAL(10,2) DEFAULT 0,
    last_reading  DATETIME DEFAULT CURRENT_TIMESTAMP,
    status        VARCHAR(30) DEFAULT 'Normal',   -- Normal / Warning / Overflow
    FOREIGN KEY (ward_id) REFERENCES ward(ward_id)
);

-- 4.6 BIN_READING
CREATE TABLE IF NOT EXISTS bin_reading (
    reading_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    bin_id       INTEGER NOT NULL,
    fill_level   DECIMAL(10,2) NOT NULL,
    recorded_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bin_id) REFERENCES smart_bin(bin_id)
);

-- 4.7 GARBAGE_TRUCK
CREATE TABLE IF NOT EXISTS garbage_truck (
    truck_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_no  VARCHAR(30) NOT NULL UNIQUE,
    driver_id        INTEGER,
    ward_id          INTEGER,
    status           VARCHAR(30) DEFAULT 'Available', -- Available / Active / Maintenance
    latitude         DECIMAL(10,7),
    longitude        DECIMAL(10,7),
    last_update      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (driver_id) REFERENCES user(user_id),
    FOREIGN KEY (ward_id) REFERENCES ward(ward_id)
);

-- 4.8 COLLECTION_TASK
CREATE TABLE IF NOT EXISTS collection_task (
    task_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    truck_id      INTEGER,
    complaint_id  INTEGER,
    bin_id        INTEGER,
    priority      VARCHAR(30) DEFAULT 'Medium',
    route_order   INTEGER,
    status        VARCHAR(30) DEFAULT 'Assigned',  -- Assigned / In Progress / Completed
    assigned_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at  DATETIME,
    FOREIGN KEY (truck_id) REFERENCES garbage_truck(truck_id),
    FOREIGN KEY (complaint_id) REFERENCES complaint(complaint_id),
    FOREIGN KEY (bin_id) REFERENCES smart_bin(bin_id)
);

-- 4.9 WASTE_IMAGE_ANALYSIS
CREATE TABLE IF NOT EXISTS waste_image_analysis (
    analysis_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id  INTEGER NOT NULL,
    waste_type    VARCHAR(50),      -- Plastic / Wet / Dry / Construction / E-Waste / Mixed
    confidence    DECIMAL(5,2),
    severity      VARCHAR(30),      -- Low / Medium / High
    analysed_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (complaint_id) REFERENCES complaint(complaint_id)
);

-- 4.10 HOTSPOT_PREDICTION
CREATE TABLE IF NOT EXISTS hotspot_prediction (
    prediction_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ward_id          INTEGER NOT NULL,
    location         VARCHAR(150),
    risk_score       DECIMAL(5,2) NOT NULL,
    prediction_date  DATE DEFAULT CURRENT_DATE,
    model_version    VARCHAR(30) DEFAULT 'v1.0-heuristic',
    FOREIGN KEY (ward_id) REFERENCES ward(ward_id)
);

-- 4.11 ALERT
CREATE TABLE IF NOT EXISTS alert (
    alert_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type    VARCHAR(50) NOT NULL,   -- Overflow / Dumping / Emergency
    reference_id  INTEGER,
    message       VARCHAR(255),
    severity      VARCHAR(30) DEFAULT 'Medium',
    status        VARCHAR(30) DEFAULT 'New',  -- New / Seen / Resolved
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 4.12 AUDIT_LOG
CREATE TABLE IF NOT EXISTS audit_log (
    log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER,
    action       VARCHAR(150) NOT NULL,
    entity_type  VARCHAR(50),
    entity_id    INTEGER,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(user_id)
);

CREATE INDEX IF NOT EXISTS idx_complaint_status ON complaint(status);
CREATE INDEX IF NOT EXISTS idx_complaint_ward ON complaint(ward_id);
CREATE INDEX IF NOT EXISTS idx_bin_status ON smart_bin(status);
CREATE INDEX IF NOT EXISTS idx_bin_ward ON smart_bin(ward_id);
CREATE INDEX IF NOT EXISTS idx_truck_status ON garbage_truck(status);
CREATE INDEX IF NOT EXISTS idx_task_status ON collection_task(status);
CREATE INDEX IF NOT EXISTS idx_alert_status ON alert(status);
