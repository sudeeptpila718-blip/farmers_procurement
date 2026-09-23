import os
import sqlite3
import random
import string
import re
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, jsonify
)
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "farmers.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "pdf", "gif", "webp"}

app = Flask(__name__)
app.secret_key = "farmers-procurement-secret-key-change-me"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def regex_search(value, pattern):
    match = re.search(pattern, str(value or ''))
    return match.group(0) if match else ''

app.jinja_env.filters['regex_search'] = regex_search

ADMIN_USER = {"username": "admin", "password": "admin123"}
PROCUREMENT_USER = {"username": "procurement", "password": "procure123"}

STATE_DISTRICTS = {
    "West Bengal": [
        "Alipurduar", "Bankura", "Birbhum", "Cooch Behar", "Dakshin Dinajpur",
        "Darjeeling", "Hooghly", "Howrah", "Jalpaiguri", "Jhargram",
        "Kalimpong", "Kolkata", "Malda", "Murshidabad", "Nadia",
        "North 24 Parganas", "Paschim Bardhaman", "Paschim Medinipur",
        "Purba Bardhaman", "Purba Medinipur", "Purulia", "South 24 Parganas",
        "Uttar Dinajpur"
    ],
    "Odisha": [
        "Anugola (Angul)", "Balangir", "Baleshwar (Balasore)", "Baragada (Bargarh)",
        "Bhadrak", "Boudh", "Cuttack (Kataka)", "Debagada (Deogarh)", "Dhenkanal",
        "Gajapati", "Ganjam", "Jagatsinghapur", "Jajpur", "Jharsuguda",
        "Kalahandi", "Kandhamala (Kandhamal)", "Kendrapada (Kendrapara)",
        "Kendujhar (Keonjhar)", "Khordha", "Koraput", "Malkangiri", "Mayurbhanj",
        "Nabarangpur", "Nayagada (Nayagarh)", "Nuapada", "Puri", "Rayagada",
        "Sambalpur", "Subarnapur (Sonepur)", "Sundaragada (Sundargarh)"
    ],
    "Bihar": ["Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Darbhanga"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Agra", "Meerut"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar", "Patiala"],
    "Maharashtra": ["Pune", "Nagpur", "Nashik", "Aurangabad", "Kolhapur"],
    "Assam": ["Guwahati", "Dibrugarh", "Silchar", "Jorhat"],
}

STATUS_STEPS = [
    "Kishan Seva Kendra",
    "Verification Officer Assigned",
    "Verified",
    "Transferred to Procurement",
    "Received by Procurement",
    "Seed Distribution Done",
    "Completed",
]

CROPS = ["Rice", "Wheat", "Maize", "Sugarcane", "Jute", "Potato", "Mustard", "Pulses"]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS farmers (
            app_no TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            mobile TEXT NOT NULL,
            gender TEXT,
            category TEXT,
            kishan_id TEXT,
            kishan_doc TEXT,
            aadhar TEXT,
            aadhar_doc TEXT,
            photo_doc TEXT,
            signature_doc TEXT,
            has_land TEXT,
            land_type TEXT,
            land_decimal REAL DEFAULT 0,
            land_doc TEXT,
            state TEXT,
            district TEXT,
            village TEXT,
            panchayat TEXT,
            bank_account TEXT,
            bank_doc TEXT,
            ifsc TEXT,
            bank_name TEXT,
            status TEXT DEFAULT 'Kishan Seva Kendra',
            created_at TEXT,
            transferred_at TEXT
        );

        CREATE TABLE IF NOT EXISTS officers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_app_no TEXT,
            officer_name TEXT,
            officer_contact TEXT,
            confirmed INTEGER DEFAULT 0,
            FOREIGN KEY(farmer_app_no) REFERENCES farmers(app_no)
        );

        CREATE TABLE IF NOT EXISTS verification_results (
            farmer_app_no TEXT PRIMARY KEY,
            land_ok INTEGER,
            aadhar_doc_ok INTEGER,
            land_doc_ok INTEGER,
            kishan_doc_ok INTEGER,
            bank_doc_ok INTEGER,
            officer_name TEXT,
            verified INTEGER DEFAULT 0,
            verified_at TEXT
        );

        CREATE TABLE IF NOT EXISTS slot_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_type TEXT,
            slot_date TEXT,
            slot_time TEXT
        );

        CREATE TABLE IF NOT EXISTS farmer_slots (
            farmer_app_no TEXT,
            slot_type TEXT,
            slot_date TEXT,
            slot_time TEXT,
            PRIMARY KEY (farmer_app_no, slot_type)
        );

        CREATE TABLE IF NOT EXISTS plowing (
            farmer_app_no TEXT PRIMARY KEY,
            crop_name TEXT,
            multiple_crops INTEGER,
            second_crop TEXT,
            quantity_approx TEXT
        );

        CREATE TABLE IF NOT EXISTS seed_giving (
            farmer_app_no TEXT PRIMARY KEY,
            crop_name TEXT,
            approx_quantity TEXT,
            seed_amount_kg REAL,
            price REAL,
            payment_mode TEXT,
            given_at TEXT,
            status TEXT DEFAULT 'Completed',
            FOREIGN KEY(farmer_app_no) REFERENCES farmers(app_no)
        );

        CREATE TABLE IF NOT EXISTS harvesting (
            farmer_app_no TEXT PRIMARY KEY,
            crop1_name TEXT,
            quantity TEXT,
            amount TEXT,
            crop2_name TEXT,
            crop2_quantity TEXT,
            crop2_amount TEXT,
            quality TEXT,
            total_amount TEXT,
            status TEXT DEFAULT 'Pending'
        );

        CREATE TABLE IF NOT EXISTS crop_analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_app_no TEXT,
            season TEXT,
            crop TEXT,
            quantity REAL,
            amount REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS farming_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_app_no TEXT,
            session_number INTEGER,
            seed_name TEXT,
            seed_quantity REAL,
            seed_amount REAL,
            payment_mode TEXT,
            crop1_name TEXT,
            crop1_quantity TEXT,
            crop1_amount TEXT,
            crop2_name TEXT,
            crop2_quantity TEXT,
            crop2_amount TEXT,
            total_harvest_amount TEXT,
            quality TEXT,
            officer_name TEXT,
            completed_at TEXT
        );
        """
    )
    for col_alter in [
        "ALTER TABLE farmers ADD COLUMN photo_doc TEXT",
        "ALTER TABLE farmers ADD COLUMN signature_doc TEXT",
        "ALTER TABLE farmers ADD COLUMN gender TEXT",
        "ALTER TABLE farmers ADD COLUMN category TEXT",
        "ALTER TABLE farmers ADD COLUMN transferred_at TEXT",
        "ALTER TABLE verification_results ADD COLUMN bank_doc_ok INTEGER DEFAULT 1",
        "ALTER TABLE harvesting ADD COLUMN crop1_name TEXT",
        "ALTER TABLE harvesting ADD COLUMN crop2_name TEXT",
        "ALTER TABLE harvesting ADD COLUMN crop2_quantity TEXT",
        "ALTER TABLE harvesting ADD COLUMN crop2_amount TEXT",
        "ALTER TABLE harvesting ADD COLUMN total_amount TEXT",
        "ALTER TABLE crop_analytics ADD COLUMN amount REAL DEFAULT 0"
    ]:
        try:
            db.execute(col_alter)
            db.commit()
        except sqlite3.OperationalError:
            pass

    cur = db.execute("SELECT COUNT(*) c FROM slot_options")
    if cur.fetchone()["c"] == 0:
        demo_slots = [
            ("verification", "2026-09-22", "10:00 AM"),
            ("verification", "2026-09-23", "02:00 PM"),
            ("verification", "2026-09-24", "11:30 AM"),
            ("seed", "2026-10-01", "09:00 AM"),
            ("seed", "2026-10-02", "01:00 PM"),
            ("harvesting", "2026-11-15", "10:00 AM"),
            ("harvesting", "2026-11-16", "02:30 PM"),
        ]
        db.executemany(
            "INSERT INTO slot_options (slot_type, slot_date, slot_time) VALUES (?,?,?)",
            demo_slots,
        )
        db.commit()
    db.close()


def gen_app_no(db):
    for _ in range(50):
        code = "".join(random.choices(string.digits, k=4))
        row = db.execute("SELECT 1 FROM farmers WHERE app_no=?", (code,)).fetchone()
        if not row:
            return code
    raise RuntimeError("Could not generate unique application number")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def save_upload(file_storage, prefix):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None
    fname = secure_filename(f"{prefix}_{int(datetime.now().timestamp())}_{file_storage.filename}")
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], fname))
    return fname


def stats_for(db, min_status_index=0):
    total = db.execute("SELECT COUNT(*) c FROM farmers").fetchone()["c"]
    pending = db.execute(
        "SELECT COUNT(*) c FROM farmers WHERE status NOT IN ('Completed','Declined')"
    ).fetchone()["c"]
    done = db.execute(
        "SELECT COUNT(*) c FROM farmers WHERE status='Completed'"
    ).fetchone()["c"]
    land_row = db.execute(
        "SELECT COALESCE(SUM(land_decimal),0) s FROM farmers WHERE has_land='Yes'"
    ).fetchone()

    collected_row = db.execute("SELECT COALESCE(SUM(price), 0) s FROM seed_giving").fetchone()
    money_collected = round(collected_row["s"] or 0, 2)

    harvest_rows = db.execute("SELECT amount, total_amount, quantity, crop2_quantity FROM harvesting").fetchall()
    money_given = 0.0
    total_crop_qty = 0.0
    for hr in harvest_rows:
        try:
            amt_str = hr["total_amount"] or hr["amount"] or "0"
            val = float(re.sub(r"[^\d.]", "", amt_str))
            money_given += val
        except ValueError:
            pass
        for q_field in ["quantity", "crop2_quantity"]:
            try:
                q_digits = re.findall(r"[\d.]+", hr[q_field] or "")
                if q_digits:
                    total_crop_qty += float(q_digits[0])
            except (ValueError, IndexError):
                pass

    return {
        "total": total,
        "registration_done": total,
        "pending": pending,
        "done": done,
        "total_land": round(land_row["s"] or 0, 2),
        "total_crop_collected": round(total_crop_qty, 1),
        "money_collected": round(money_collected, 2),
        "money_given": round(money_given, 2),
    }


def farmer_login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("farmer_app_no"):
            return redirect(url_for("index"))
        return f(*a, **kw)
    return wrapper


def admin_login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return wrapper


def procurement_login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("is_procurement"):
            return redirect(url_for("procurement_login"))
        return f(*a, **kw)
    return wrapper


def officer_login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("officer_farmer_app_no"):
            return redirect(url_for("officer_login"))
        return f(*a, **kw)
    return wrapper


@app.route("/")
def index():
    if session.get("farmer_app_no"):
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/farmer-login", methods=["POST"])
def farmer_login():
    db = get_db()
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    row = db.execute(
        "SELECT * FROM farmers WHERE LOWER(name)=LOWER(?) AND mobile=?",
        (name, mobile),
    ).fetchone()
    if row:
        session["farmer_app_no"] = row["app_no"]
        return redirect(url_for("dashboard"))
    flash("No matching farmer found. Check your name & mobile number, or register as a new farmer.", "error")
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template(
            "register.html", 
            states=STATE_DISTRICTS, 
            banks=["State Bank of India", "Punjab National Bank", "Bank of Baroda", "Canara Bank", "Others"]
        )

    db = get_db()
    form = request.form
    app_no = gen_app_no(db)

    photo_doc = save_upload(request.files.get("photo_doc"), "photo")
    signature_doc = save_upload(request.files.get("signature_doc"), "signature")
    aadhar_doc = save_upload(request.files.get("aadhar_doc"), "aadhar")
    land_doc = save_upload(request.files.get("land_doc"), "land")
    kishan_doc = save_upload(request.files.get("kishan_doc"), "kishan")
    bank_doc = save_upload(request.files.get("bank_doc"), "bank")

    bank_choice = form.get("bank_choice", "")
    bank_name = form.get("bank_other", "").strip() if bank_choice == "Others" else bank_choice

    has_land = "Yes"
    land_type = form.get("land_type", "Own")
    land_decimal = float(form.get("land_decimal") or 0)

    db.execute(
        """INSERT INTO farmers
        (app_no, name, mobile, gender, category, kishan_id, kishan_doc, aadhar, aadhar_doc,
         photo_doc, signature_doc, has_land, land_type, land_decimal, land_doc, state, district, 
         village, panchayat, bank_account, bank_doc, ifsc, bank_name, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            app_no,
            form.get("name", "").strip(),
            form.get("mobile", "").strip(),
            form.get("gender", "Male"),
            form.get("category", "General"),
            form.get("kishan_id", "").strip(),
            kishan_doc,
            form.get("aadhar", "").strip(),
            aadhar_doc,
            photo_doc,
            signature_doc,
            has_land,
            land_type,
            land_decimal,
            land_doc,
            form.get("state", ""),
            form.get("district", ""),
            form.get("village", "").strip(),
            form.get("panchayat", "").strip(),
            form.get("bank_account", "").strip(),
            bank_doc,
            form.get("ifsc", "").strip(),
            bank_name,
            "Kishan Seva Kendra",
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ),
    )
    db.commit()
    session["farmer_app_no"] = app_no
    session["just_registered"] = True
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@farmer_login_required
def dashboard():
    db = get_db()
    app_no = session["farmer_app_no"]
    farmer = db.execute("SELECT * FROM farmers WHERE app_no=?", (app_no,)).fetchone()
    if not farmer:
        session.clear()
        return redirect(url_for("index"))

    officer = db.execute(
        "SELECT * FROM officers WHERE farmer_app_no=? ORDER BY id DESC LIMIT 1", (app_no,)
    ).fetchone()
    verification = db.execute(
        "SELECT * FROM verification_results WHERE farmer_app_no=?", (app_no,)
    ).fetchone()
    my_slots = {
        r["slot_type"]: r
        for r in db.execute("SELECT * FROM farmer_slots WHERE farmer_app_no=?", (app_no,))
    }
    verification_slot_options = db.execute(
        "SELECT * FROM slot_options WHERE slot_type='verification' ORDER BY slot_date, slot_time"
    ).fetchall()
    seed_slot_options = db.execute(
        "SELECT * FROM slot_options WHERE slot_type='seed' ORDER BY slot_date, slot_time"
    ).fetchall()
    harvesting_slot_options = db.execute(
        "SELECT * FROM slot_options WHERE slot_type='harvesting' ORDER BY slot_date, slot_time"
    ).fetchall()
    plowing = db.execute("SELECT * FROM plowing WHERE farmer_app_no=?", (app_no,)).fetchone()
    seed_giving = db.execute("SELECT * FROM seed_giving WHERE farmer_app_no=?", (app_no,)).fetchone()
    harvesting = db.execute("SELECT * FROM harvesting WHERE farmer_app_no=?", (app_no,)).fetchone()
    
    analytics = [
        dict(r) for r in db.execute(
            "SELECT season, crop, quantity, amount FROM crop_analytics WHERE farmer_app_no=? ORDER BY id",
            (app_no,),
        ).fetchall()
    ]

    just_registered = session.pop("just_registered", False)
    status_index = STATUS_STEPS.index(farmer["status"]) if farmer["status"] in STATUS_STEPS else 0

    return render_template(
        "dashboard.html",
        farmer=farmer,
        officer=officer,
        verification=verification,
        my_slots=my_slots,
        verification_slot_options=verification_slot_options,
        seed_slot_options=seed_slot_options,
        harvesting_slot_options=harvesting_slot_options,
        plowing=plowing,
        seed_giving=seed_giving,
        harvesting=harvesting,
        analytics=analytics,
        status_steps=STATUS_STEPS,
        status_index=status_index,
        just_registered=just_registered,
        crops=CROPS,
    )


@app.route("/start-new-cycle", methods=["POST"])
@farmer_login_required
def start_new_cycle():
    db = get_db()
    app_no = session["farmer_app_no"]

    farmer = db.execute("SELECT * FROM farmers WHERE app_no=?", (app_no,)).fetchone()
    if not farmer or farmer["status"] != "Completed":
        flash("You can only start a new crop cycle after completing your current harvest.", "error")
        return redirect(url_for("dashboard"))

    db.execute("DELETE FROM plowing WHERE farmer_app_no=?", (app_no,))
    db.execute("DELETE FROM seed_giving WHERE farmer_app_no=?", (app_no,))
    db.execute("DELETE FROM harvesting WHERE farmer_app_no=?", (app_no,))
    db.execute("DELETE FROM farmer_slots WHERE farmer_app_no=? AND slot_type IN ('seed', 'harvesting')", (app_no,))

    db.execute("UPDATE farmers SET status='Received by Procurement' WHERE app_no=?", (app_no,))
    db.commit()

    flash("New seasonal crop cycle initiated! Land verification retained. You can proceed with plowing and seed booking.", "success")
    return redirect(url_for("dashboard"))


@app.route("/book-slot", methods=["POST"])
@farmer_login_required
def book_slot():
    db = get_db()
    app_no = session["farmer_app_no"]
    slot_type = request.form.get("slot_type")
    slot_id = request.form.get("slot_id")
    slot = db.execute("SELECT * FROM slot_options WHERE id=?", (slot_id,)).fetchone()
    if slot:
        db.execute(
            """INSERT INTO farmer_slots (farmer_app_no, slot_type, slot_date, slot_time)
               VALUES (?,?,?,?)
               ON CONFLICT(farmer_app_no, slot_type)
               DO UPDATE SET slot_date=excluded.slot_date, slot_time=excluded.slot_time""",
            (app_no, slot_type, slot["slot_date"], slot["slot_time"]),
        )
        db.commit()
        flash("Slot booked successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/plowing", methods=["POST"])
@farmer_login_required
def plowing_submit():
    db = get_db()
    app_no = session["farmer_app_no"]
    multiple = 1 if request.form.get("multiple_crops") == "on" else 0
    db.execute(
        """INSERT INTO plowing (farmer_app_no, crop_name, multiple_crops, second_crop, quantity_approx)
           VALUES (?,?,?,?,?)
           ON CONFLICT(farmer_app_no) DO UPDATE SET
             crop_name=excluded.crop_name, multiple_crops=excluded.multiple_crops,
             second_crop=excluded.second_crop, quantity_approx=excluded.quantity_approx""",
        (
            app_no,
            request.form.get("crop_name", ""),
            multiple,
            request.form.get("second_crop", ""),
            request.form.get("quantity_approx", ""),
        ),
    )
    db.commit()
    flash("Plowing details saved.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET":
        return render_template("staff_login.html", portal="Kishan Seva Kendra", action=url_for("admin_login"))
    u, p = request.form.get("username"), request.form.get("password")
    if u == ADMIN_USER["username"] and p == ADMIN_USER["password"]:
        session["is_admin"] = True
        return redirect(url_for("admin"))
    flash("Invalid credentials.", "error")
    return redirect(url_for("admin_login"))


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@admin_login_required
def admin():
    db = get_db()
    active_farmers = db.execute(
        """SELECT * FROM farmers 
           WHERE status NOT IN ('Completed', 'Declined') 
           ORDER BY created_at DESC"""
    ).fetchall()
    
    my_slots = {}
    for r in db.execute("SELECT * FROM farmer_slots"):
        my_slots.setdefault(r["farmer_app_no"], {})[r["slot_type"]] = r

    officers = {
        r["farmer_app_no"]: r
        for r in db.execute("SELECT * FROM officers WHERE id IN (SELECT MAX(id) FROM officers GROUP BY farmer_app_no)")
    }
    verifications = {r["farmer_app_no"]: r for r in db.execute("SELECT * FROM verification_results")}

    now = datetime.now()
    four_days_passed = {}
    for f in active_farmers:
        app_no = f["app_no"]
        t_at = f["created_at"]
        try:
            dt = datetime.strptime(t_at, "%Y-%m-%d %H:%M")
            is_past = (now - dt).total_seconds() >= (4 * 86400)
        except Exception:
            is_past = False
        four_days_passed[app_no] = is_past

    stats = stats_for(db)
    
    return render_template(
        "admin.html", 
        farmers=active_farmers, 
        my_slots=my_slots,
        officers=officers,
        verifications=verifications,
        four_days_passed=four_days_passed,
        stats=stats
    )


@app.route("/admin/assign-officer/<app_no>", methods=["POST"])
@admin_login_required
def admin_assign_officer(app_no):
    db = get_db()
    officer_name = request.form.get("officer_name", "").strip()
    officer_contact = request.form.get("officer_contact", "").strip()
    if officer_name and officer_contact:
        db.execute(
            "INSERT INTO officers (farmer_app_no, officer_name, officer_contact, confirmed) VALUES (?,?,?,1)",
            (app_no, officer_name, officer_contact),
        )
        db.execute("UPDATE farmers SET status='Verification Officer Assigned' WHERE app_no=?", (app_no,))
        db.commit()
        flash(f"Verification officer {officer_name} assigned for Application {app_no}.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/force-slot/<app_no>", methods=["POST"])
@admin_login_required
def admin_force_slot(app_no):
    db = get_db()
    slot_date = request.form.get("slot_date")
    slot_time = request.form.get("slot_time")
    if slot_date and slot_time:
        db.execute(
            """INSERT INTO farmer_slots (farmer_app_no, slot_type, slot_date, slot_time)
               VALUES (?, 'verification', ?, ?)
               ON CONFLICT(farmer_app_no, slot_type)
               DO UPDATE SET slot_date=excluded.slot_date, slot_time=excluded.slot_time""",
            (app_no, slot_date, slot_time),
        )
        db.commit()
        flash(f"Verification date & time set for farmer {app_no}.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/decide/<app_no>", methods=["POST"])
@admin_login_required
def admin_decide(app_no):
    db = get_db()
    decision = request.form.get("decision")
    if decision == "transfer":
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.execute(
            "UPDATE farmers SET status='Transferred to Procurement', transferred_at=? WHERE app_no=?",
            (now_str, app_no)
        )
        flash(f"Farmer {app_no} transferred to Procurement Centre.", "success")
    elif decision == "decline":
        db.execute("UPDATE farmers SET status='Declined' WHERE app_no=?", (app_no,))
        flash(f"Farmer {app_no} registration declined.", "error")
    db.commit()
    return redirect(url_for("admin"))


@app.route("/procurement/login", methods=["GET", "POST"])
def procurement_login():
    if request.method == "GET":
        return render_template("staff_login.html", portal="Procurement Center", action=url_for("procurement_login"))
    u, p = request.form.get("username"), request.form.get("password")
    if u == PROCUREMENT_USER["username"] and p == PROCUREMENT_USER["password"]:
        session["is_procurement"] = True
        return redirect(url_for("procurement"))
    flash("Invalid procurement credentials.", "error")
    return redirect(url_for("procurement_login"))


@app.route("/procurement/logout")
def procurement_logout():
    session.pop("is_procurement", None)
    return redirect(url_for("index"))


@app.route("/procurement")
@procurement_login_required
def procurement():
    db = get_db()
    farmers = db.execute(
        """SELECT * FROM farmers
           WHERE status IN ('Transferred to Procurement', 'Received by Procurement', 'Seed Distribution Done')
           ORDER BY created_at DESC"""
    ).fetchall()
    officers_by_farmer = {
        r["farmer_app_no"]: r
        for r in db.execute(
            "SELECT * FROM officers WHERE id IN (SELECT MAX(id) FROM officers GROUP BY farmer_app_no)"
        )
    }
    my_slots = {}
    for r in db.execute("SELECT * FROM farmer_slots"):
        my_slots.setdefault(r["farmer_app_no"], {})[r["slot_type"]] = r

    verifications = {r["farmer_app_no"]: r for r in db.execute("SELECT * FROM verification_results")}
    plowing_records = {r["farmer_app_no"]: r for r in db.execute("SELECT * FROM plowing")}
    harvesting_records = {r["farmer_app_no"]: r for r in db.execute("SELECT * FROM harvesting")}
    seed_records = {r["farmer_app_no"]: r for r in db.execute("SELECT * FROM seed_giving")}

    stats = stats_for(db)
    verification_slots = db.execute(
        "SELECT * FROM slot_options WHERE slot_type='verification' ORDER BY slot_date, slot_time"
    ).fetchall()
    seed_slots = db.execute(
        "SELECT * FROM slot_options WHERE slot_type='seed' ORDER BY slot_date, slot_time"
    ).fetchall()
    harvesting_slots = db.execute(
        "SELECT * FROM slot_options WHERE slot_type='harvesting' ORDER BY slot_date, slot_time"
    ).fetchall()

    return render_template(
        "procurement.html",
        farmers=farmers,
        officers_by_farmer=officers_by_farmer,
        my_slots=my_slots,
        verifications=verifications,
        plowing_records=plowing_records,
        harvesting_records=harvesting_records,
        seed_records=seed_records,
        stats=stats,
        verification_slots=verification_slots,
        seed_slots=seed_slots,
        harvesting_slots=harvesting_slots,
    )


@app.route("/procurement/receive/<app_no>", methods=["POST"])
@procurement_login_required
def procurement_receive(app_no):
    db = get_db()
    db.execute("UPDATE farmers SET status='Received by Procurement' WHERE app_no=?", (app_no,))
    db.commit()
    flash(f"Farmer {app_no} received successfully! Seed Collection slot booking is now unlocked for this farmer.", "success")
    return redirect(url_for("procurement"))


@app.route("/api/districts/<state>")
def api_districts(state):
    return jsonify(STATE_DISTRICTS.get(state, []))


@app.route("/api/farmer-details/<app_no>")
@app.route("/api/procurement/farmer-details/<app_no>")
def api_farmer_details(app_no):
    if not session.get("is_admin") and not session.get("is_procurement"):
        return jsonify({"success": False, "error": "Unauthorized access. Please login."}), 403

    db = get_db()
    app_no = str(app_no).strip()
    farmer = db.execute("SELECT * FROM farmers WHERE app_no=?", (app_no,)).fetchone()
    if not farmer:
        return jsonify({"success": False, "error": f"Farmer not found with Application Number '{app_no}'."})

    officer = db.execute("SELECT * FROM officers WHERE farmer_app_no=? ORDER BY id DESC LIMIT 1", (app_no,)).fetchone()
    verification = db.execute("SELECT * FROM verification_results WHERE farmer_app_no=?", (app_no,)).fetchone()
    plowing = db.execute("SELECT * FROM plowing WHERE farmer_app_no=?", (app_no,)).fetchone()
    seed_giving = db.execute("SELECT * FROM seed_giving WHERE farmer_app_no=?", (app_no,)).fetchone()
    harvesting = db.execute("SELECT * FROM harvesting WHERE farmer_app_no=?", (app_no,)).fetchone()
    slots = {
        r["slot_type"]: f"{r['slot_date']} at {r['slot_time']}"
        for r in db.execute("SELECT * FROM farmer_slots WHERE farmer_app_no=?", (app_no,)).fetchall()
    }

    past_sessions = [
        dict(r) for r in db.execute(
            "SELECT * FROM farming_sessions WHERE farmer_app_no=? ORDER BY session_number DESC",
            (app_no,)
        ).fetchall()
    ]
    
    # Exact calculation: match the number of completed sessions without double counting
    total_sessions_count = max(1, len(past_sessions)) if (past_sessions or (harvesting and harvesting["status"] == "Transferred")) else 0

    auto_seed_kg = 50.0
    if plowing and plowing["quantity_approx"]:
        digits = re.findall(r"\d+", plowing["quantity_approx"])
        if digits:
            auto_seed_kg = round(float(digits[0]) * 0.05, 2)

    return jsonify({
        "success": True,
        "farmer": {
            "app_no": farmer["app_no"],
            "name": farmer["name"],
            "mobile": farmer["mobile"],
            "gender": farmer["gender"] or "—",
            "category": farmer["category"] or "—",
            "aadhar": "[Aadhaar on File]",
            "kishan_id": farmer["kishan_id"] or "—",
            "state": farmer["state"],
            "district": farmer["district"],
            "village": farmer["village"],
            "panchayat": farmer["panchayat"],
            "has_land": farmer["has_land"],
            "land_type": farmer["land_type"],
            "land_decimal": farmer["land_decimal"],
            "status": farmer["status"],
            "created_at": farmer["created_at"],
            "transferred_at": farmer["transferred_at"],
        },
        "docs": {
            "photo": farmer["photo_doc"],
            "signature": farmer["signature_doc"],
            "kishan": farmer["kishan_doc"],
            "aadhar": farmer["aadhar_doc"],
            "land": farmer["land_doc"],
            "bank": farmer["bank_doc"],
        },
        "officer": dict(officer) if officer else None,
        "verification": dict(verification) if verification else None,
        "plowing": dict(plowing) if plowing else None,
        "seed_giving": dict(seed_giving) if seed_giving else None,
        "harvesting": dict(harvesting) if harvesting else None,
        "past_sessions": past_sessions,
        "total_sessions": total_sessions_count,
        "slots": slots,
        "auto_seed_kg": auto_seed_kg,
    })


@app.route("/procurement/seed-giving-save/<app_no>", methods=["POST"])
@procurement_login_required
def seed_giving_save(app_no):
    db = get_db()
    seed_amount_kg = request.form.get("seed_amount_kg", "0").strip()
    price = request.form.get("price", "0").strip()
    payment_mode = request.form.get("payment_mode", "Cash")

    plow = db.execute("SELECT crop_name, quantity_approx FROM plowing WHERE farmer_app_no=?", (app_no,)).fetchone()
    crop_name = plow["crop_name"] if plow else ""
    approx_qty = plow["quantity_approx"] if plow else ""

    db.execute(
        """INSERT INTO seed_giving 
           (farmer_app_no, crop_name, approx_quantity, seed_amount_kg, price, payment_mode, given_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'Completed')
           ON CONFLICT(farmer_app_no) DO UPDATE SET
             crop_name=excluded.crop_name,
             approx_quantity=excluded.approx_quantity,
             seed_amount_kg=excluded.seed_amount_kg,
             price=excluded.price,
             payment_mode=excluded.payment_mode,
             given_at=excluded.given_at,
             status='Completed'""",
        (
            app_no,
            crop_name,
            approx_qty,
            float(seed_amount_kg or 0),
            float(price or 0),
            payment_mode,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ),
    )
    db.execute("UPDATE farmers SET status='Seed Distribution Done' WHERE app_no=?", (app_no,))
    db.commit()
    flash(f"Seed distribution saved for Application {app_no}.", "success")
    return redirect(url_for("procurement"))


@app.route("/procurement/add-slot", methods=["POST"])
@procurement_login_required
def add_slot():
    db = get_db()
    slot_type = request.form.get("slot_type")
    slot_date = request.form.get("slot_date")
    slot_time = request.form.get("slot_time")
    if slot_type and slot_date and slot_time:
        db.execute(
            "INSERT INTO slot_options (slot_type, slot_date, slot_time) VALUES (?,?,?)",
            (slot_type, slot_date, slot_time),
        )
        db.commit()
        flash("New slot option added.", "success")
    return redirect(url_for("procurement"))


@app.route("/procurement/harvest-save", methods=["POST"])
@procurement_login_required
def harvest_save():
    db = get_db()
    app_no = request.form.get("farmer_app_no", "").strip()
    crop1_name = request.form.get("crop1_name", "").strip()
    quantity1 = request.form.get("quantity", "").strip()
    amount1 = request.form.get("amount", "").strip()
    
    crop2_name = request.form.get("crop2_name", "").strip()
    crop2_quantity = request.form.get("crop2_quantity", "").strip()
    crop2_amount = request.form.get("crop2_amount", "").strip()
    quality = request.form.get("quality", "Grade A (Premium)").strip()

    amt1_val = float(re.sub(r"[^\d.]", "", amount1 or "0") or 0)
    amt2_val = float(re.sub(r"[^\d.]", "", crop2_amount or "0") or 0)
    total_amt = str(amt1_val + amt2_val)

    db.execute(
        """INSERT INTO harvesting 
           (farmer_app_no, crop1_name, quantity, amount, crop2_name, crop2_quantity, crop2_amount, quality, total_amount, status)
           VALUES (?,?,?,?,?,?,?,?,?,'Transferred')
           ON CONFLICT(farmer_app_no) DO UPDATE SET
             crop1_name=excluded.crop1_name,
             quantity=excluded.quantity,
             amount=excluded.amount,
             crop2_name=excluded.crop2_name,
             crop2_quantity=excluded.crop2_quantity,
             crop2_amount=excluded.crop2_amount,
             quality=excluded.quality,
             total_amount=excluded.total_amount,
             status='Transferred'""",
        (app_no, crop1_name, quantity1, amount1, crop2_name, crop2_quantity, crop2_amount, quality, total_amt),
    )

    sess_row = db.execute("SELECT COUNT(*) c FROM farming_sessions WHERE farmer_app_no=?", (app_no,)).fetchone()
    session_num = (sess_row["c"] or 0) + 1

    seed_row = db.execute("SELECT * FROM seed_giving WHERE farmer_app_no=?", (app_no,)).fetchone()
    v_row = db.execute("SELECT * FROM verification_results WHERE farmer_app_no=?", (app_no,)).fetchone()
    now_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    db.execute(
        """INSERT INTO farming_sessions
           (farmer_app_no, session_number, seed_name, seed_quantity, seed_amount, payment_mode,
            crop1_name, crop1_quantity, crop1_amount, crop2_name, crop2_quantity, crop2_amount,
            total_harvest_amount, quality, officer_name, completed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            app_no,
            session_num,
            seed_row["crop_name"] if seed_row else crop1_name,
            seed_row["seed_amount_kg"] if seed_row else 0,
            seed_row["price"] if seed_row else 0,
            seed_row["payment_mode"] if seed_row else 'Cash',
            crop1_name,
            quantity1,
            amount1,
            crop2_name,
            crop2_quantity,
            crop2_amount,
            total_amt,
            quality,
            v_row["officer_name"] if v_row else "Field Officer",
            now_time
        )
    )

    season_tag = f"Season {session_num}"
    q1_val = float(re.findall(r"[\d.]+", quantity1)[0]) if re.findall(r"[\d.]+", quantity1) else 15.0
    db.execute(
        "INSERT INTO crop_analytics (farmer_app_no, season, crop, quantity, amount) VALUES (?, ?, ?, ?, ?)",
        (app_no, season_tag, crop1_name, q1_val, amt1_val)
    )

    if crop2_name and crop2_quantity:
        q2_val = float(re.findall(r"[\d.]+", crop2_quantity)[0]) if re.findall(r"[\d.]+", crop2_quantity) else 8.0
        db.execute(
            "INSERT INTO crop_analytics (farmer_app_no, season, crop, quantity, amount) VALUES (?, ?, ?, ?, ?)",
            (app_no, season_tag, crop2_name, q2_val, amt2_val)
        )

    db.execute("UPDATE farmers SET status='Completed' WHERE app_no=?", (app_no,))
    db.commit()
    flash(f"Session {session_num} harvest recorded and finalized for Farmer {app_no}.", "success")
    return redirect(url_for("procurement"))


@app.route("/officer/login", methods=["GET", "POST"])
def officer_login():
    if request.method == "GET":
        return render_template("officer_login.html")
    db = get_db()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    row = db.execute(
        """SELECT o.*, f.app_no as f_app_no, f.name as f_name
           FROM officers o JOIN farmers f ON f.app_no = o.farmer_app_no
           WHERE LOWER(o.officer_name)=LOWER(?) AND LOWER(f.name)=LOWER(?)
           ORDER BY o.id DESC LIMIT 1""",
        (username, password),
    ).fetchone()

    if row:
        v = db.execute("SELECT verified FROM verification_results WHERE farmer_app_no=?", (row["f_app_no"],)).fetchone()
        if v and v["verified"] == 1:
            flash("Verification Done", "error")
            return redirect(url_for("officer_login"))

        session["officer_farmer_app_no"] = row["f_app_no"]
        session["officer_name"] = row["officer_name"]
        return redirect(url_for("officer_form"))

    flash("Invalid officer login. User ID = assigned officer name, Password = farmer's name.", "error")
    return redirect(url_for("officer_login"))


@app.route("/officer/logout")
def officer_logout():
    session.pop("officer_farmer_app_no", None)
    session.pop("officer_name", None)
    return redirect(url_for("index"))


@app.route("/officer/form", methods=["GET", "POST"])
@officer_login_required
def officer_form():
    db = get_db()
    app_no = session["officer_farmer_app_no"]
    farmer = db.execute("SELECT * FROM farmers WHERE app_no=?", (app_no,)).fetchone()

    existing = db.execute("SELECT * FROM verification_results WHERE farmer_app_no=?", (app_no,)).fetchone()
    if existing and existing["verified"] == 1:
        session.pop("officer_farmer_app_no", None)
        session.pop("officer_name", None)
        flash("Verification Done", "error")
        return redirect(url_for("officer_login"))

    if request.method == "POST":
        land_ok = 1 if request.form.get("land_ok") == "ok" else 0
        aadhar_doc_ok = 1 if request.form.get("aadhar_doc_ok") == "ok" else 0
        land_doc_ok = 1 if request.form.get("land_doc_ok") == "ok" else 0
        kishan_doc_ok = 1 if request.form.get("kishan_doc_ok") == "ok" else 0
        bank_doc_ok = 1 if request.form.get("bank_doc_ok") == "ok" else 0

        if not land_ok:
            corrected_land = request.form.get("corrected_land_decimal", "").strip()
            if corrected_land:
                try:
                    db.execute("UPDATE farmers SET land_decimal=? WHERE app_no=?", (float(corrected_land), app_no))
                except ValueError:
                    pass

        if not aadhar_doc_ok and request.files.get("corrected_aadhar_doc"):
            new_file = save_upload(request.files.get("corrected_aadhar_doc"), "aadhar")
            if new_file:
                db.execute("UPDATE farmers SET aadhar_doc=? WHERE app_no=?", (new_file, app_no))

        if not land_doc_ok and request.files.get("corrected_land_doc"):
            new_file = save_upload(request.files.get("corrected_land_doc"), "land")
            if new_file:
                db.execute("UPDATE farmers SET land_doc=? WHERE app_no=?", (new_file, app_no))

        if not kishan_doc_ok and request.files.get("corrected_kishan_doc"):
            new_file = save_upload(request.files.get("corrected_kishan_doc"), "kishan")
            if new_file:
                db.execute("UPDATE farmers SET kishan_doc=? WHERE app_no=?", (new_file, app_no))

        if not bank_doc_ok and request.files.get("corrected_bank_doc"):
            new_file = save_upload(request.files.get("corrected_bank_doc"), "bank")
            if new_file:
                db.execute("UPDATE farmers SET bank_doc=? WHERE app_no=?", (new_file, app_no))

        cursor = db.execute("PRAGMA table_info(verification_results)")
        existing_cols = {row["name"] for row in cursor.fetchall()}

        now_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        officer_name = session.get("officer_name")

        data_map = {
            "farmer_app_no": app_no,
            "land_ok": land_ok,
            "aadhar_doc_ok": aadhar_doc_ok,
            "land_doc_ok": land_doc_ok,
            "kishan_doc_ok": kishan_doc_ok,
            "bank_doc_ok": bank_doc_ok,
            "name_ok": 1,
            "mobile_ok": 1,
            "state_ok": 1,
            "district_ok": 1,
            "village_ok": 1,
            "preference_crop": "",
            "officer_name": officer_name,
            "verified": 1,
            "verified_at": now_time
        }

        active_cols = [c for c in data_map.keys() if c in existing_cols]
        col_sql = ", ".join(active_cols)
        val_placeholders = ", ".join(["?"] * len(active_cols))
        update_assignments = ", ".join([f"{c}=excluded.{c}" for c in active_cols if c != "farmer_app_no"])
        values = [data_map[c] for c in active_cols]

        insert_sql = f"""
            INSERT INTO verification_results ({col_sql})
            VALUES ({val_placeholders})
            ON CONFLICT(farmer_app_no) DO UPDATE SET {update_assignments}
        """
        db.execute(insert_sql, values)

        db.execute("UPDATE farmers SET status='Verified' WHERE app_no=?", (app_no,))
        db.commit()

        session.pop("officer_farmer_app_no", None)
        session.pop("officer_name", None)

        flash("Verification Completed! You have been logged out.", "success")
        return redirect(url_for("officer_login"))

    return render_template("officer_form.html", farmer=farmer)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)