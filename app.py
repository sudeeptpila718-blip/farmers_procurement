import os
import sqlite3
import random
import string
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

ADMIN_USER = {"username": "admin", "password": "admin123"}
PROCUREMENT_USER = {"username": "procurement", "password": "procure123"}

STATE_DISTRICTS = {
    "West Bengal": ["Kolkata", "Howrah", "Nadia", "Murshidabad", "Bardhaman", "Malda"],
    "Bihar": ["Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Darbhanga"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Agra", "Meerut"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar", "Patiala"],
    "Maharashtra": ["Pune", "Nagpur", "Nashik", "Aurangabad", "Kolhapur"],
    "Odisha": ["Bhubaneswar", "Cuttack", "Puri", "Sambalpur"],
    "Assam": ["Guwahati", "Dibrugarh", "Silchar", "Jorhat"],
}

STATUS_STEPS = [
    "Kishan Seva Kendra",
    "Procurement Centre",
    "Verification Officer Assigned",
    "Verified",
    "Social Point Assigned",
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
            kishan_id TEXT,
            kishan_doc TEXT,
            aadhar TEXT,
            aadhar_doc TEXT,
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
            name_ok INTEGER, mobile_ok INTEGER, state_ok INTEGER,
            district_ok INTEGER, village_ok INTEGER, land_ok INTEGER,
            aadhar_doc_ok INTEGER, land_doc_ok INTEGER, kishan_doc_ok INTEGER,
            preference_crop TEXT,
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

        CREATE TABLE IF NOT EXISTS harvesting (
            farmer_app_no TEXT PRIMARY KEY,
            quantity TEXT,
            quality TEXT,
            amount TEXT,
            status TEXT DEFAULT 'Pending'
        );

        CREATE TABLE IF NOT EXISTS crop_analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_app_no TEXT,
            season TEXT,
            crop TEXT,
            quantity REAL
        );
        """
    )
    # Ensure transferred_at column exists if table already existed
    try:
        db.execute("ALTER TABLE farmers ADD COLUMN transferred_at TEXT")
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
    return {
        "total": total,
        "registration_done": total,
        "pending": pending,
        "done": done,
        "total_land": round(land_row["s"] or 0, 2),
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
            "register.html", states=STATE_DISTRICTS, banks=["State Bank of India", "Punjab National Bank",
                                                              "Bank of Baroda", "Canara Bank", "Others"]
        )

    db = get_db()
    form = request.form
    app_no = gen_app_no(db)

    kishan_doc = save_upload(request.files.get("kishan_doc"), "kishan")
    aadhar_doc = save_upload(request.files.get("aadhar_doc"), "aadhar")
    land_doc = save_upload(request.files.get("land_doc"), "land")
    bank_doc = save_upload(request.files.get("bank_doc"), "bank")

    bank_choice = form.get("bank_choice", "")
    bank_name = form.get("bank_other", "").strip() if bank_choice == "Others" else bank_choice

    db.execute(
        """INSERT INTO farmers
        (app_no, name, mobile, kishan_id, kishan_doc, aadhar, aadhar_doc,
         has_land, land_type, land_decimal, land_doc, state, district, village,
         panchayat, bank_account, bank_doc, ifsc, bank_name, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            app_no,
            form.get("name", "").strip(),
            form.get("mobile", "").strip(),
            form.get("kishan_id", "").strip(),
            kishan_doc,
            form.get("aadhar", "").strip(),
            aadhar_doc,
            form.get("has_land", "No"),
            form.get("land_type", ""),
            float(form.get("land_decimal") or 0),
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
    plowing = db.execute("SELECT * FROM plowing WHERE farmer_app_no=?", (app_no,)).fetchone()
    harvesting = db.execute("SELECT * FROM harvesting WHERE farmer_app_no=?", (app_no,)).fetchone()
    analytics = db.execute(
        "SELECT season, crop, quantity FROM crop_analytics WHERE farmer_app_no=? ORDER BY id",
        (app_no,),
    ).fetchall()

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
        plowing=plowing,
        harvesting=harvesting,
        analytics=analytics,
        status_steps=STATUS_STEPS,
        status_index=status_index,
        just_registered=just_registered,
        crops=CROPS,
    )


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
    
    all_history = db.execute(
        "SELECT * FROM farmers ORDER BY created_at DESC"
    ).fetchall()

    all_farmers_count = db.execute("SELECT COUNT(*) c FROM farmers").fetchone()["c"]
    stats = stats_for(db)
    
    return render_template(
        "admin.html", 
        farmers=active_farmers, 
        history=all_history, 
        stats=stats, 
        all_count=all_farmers_count
    )


@app.route("/admin/decide/<app_no>", methods=["POST"])
@admin_login_required
def admin_decide(app_no):
    db = get_db()
    decision = request.form.get("decision")
    if decision == "transfer":
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.execute(
            "UPDATE farmers SET status='Procurement Centre', transferred_at=? WHERE app_no=?",
            (now_str, app_no)
        )
        flash(f"Farmer {app_no} transferred to Procurement Centre (Kishan Seva confirmed).", "success")
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
           WHERE status IN ('Procurement Centre','Verification Officer Assigned',
                             'Verified','Social Point Assigned','Completed')
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
    stats = stats_for(db)
    verification_slots = db.execute(
        "SELECT * FROM slot_options WHERE slot_type='verification' ORDER BY slot_date, slot_time"
    ).fetchall()
    seed_slots = db.execute(
        "SELECT * FROM slot_options WHERE slot_type='seed' ORDER BY slot_date, slot_time"
    ).fetchall()

    now = datetime.now()
    four_days_passed = {}
    pending_farmers = []
    for f in farmers:
        app_no = f["app_no"]
        t_at = f["transferred_at"] or f["created_at"]
        try:
            dt = datetime.strptime(t_at, "%Y-%m-%d %H:%M")
            is_past = (now - dt).total_seconds() >= (4 * 86400)
        except Exception:
            is_past = False
        four_days_passed[app_no] = is_past

        if f["status"] != "Completed":
            pending_farmers.append(f)

    return render_template(
        "procurement.html",
        farmers=farmers,
        officers_by_farmer=officers_by_farmer,
        my_slots=my_slots,
        stats=stats,
        verification_slots=verification_slots,
        seed_slots=seed_slots,
        four_days_passed=four_days_passed,
        pending_farmers=pending_farmers,
    )


@app.route("/procurement/force-slot/<app_no>", methods=["POST"])
@procurement_login_required
def procurement_force_slot(app_no):
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
        flash(f"Verification date & time assigned for farmer {app_no}.", "success")
    return redirect(url_for("procurement"))


@app.route("/procurement/assign-officer/<app_no>", methods=["POST"])
@procurement_login_required
def assign_officer(app_no):
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
        flash(f"Verification officer {officer_name} assigned & confirmed for {app_no}.", "success")
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


@app.route("/procurement/assign-social-point/<app_no>", methods=["POST"])
@procurement_login_required
def assign_social_point(app_no):
    db = get_db()
    db.execute("UPDATE farmers SET status='Social Point Assigned' WHERE app_no=?", (app_no,))
    db.commit()
    flash(f"Social point (seed collection) unlocked for {app_no}.", "success")
    return redirect(url_for("procurement"))


@app.route("/procurement/harvest/<app_no>", methods=["POST"])
@procurement_login_required
def harvest_update(app_no):
    db = get_db()
    db.execute(
        """INSERT INTO harvesting (farmer_app_no, quantity, quality, amount, status)
           VALUES (?,?,?,?,?)
           ON CONFLICT(farmer_app_no) DO UPDATE SET
             quantity=excluded.quantity, quality=excluded.quality,
             amount=excluded.amount, status=excluded.status""",
        (
            app_no,
            request.form.get("quantity", ""),
            request.form.get("quality", ""),
            request.form.get("amount", ""),
            request.form.get("status", "Pending"),
        ),
    )
    if request.form.get("status") == "Transferred":
        db.execute("UPDATE farmers SET status='Completed' WHERE app_no=?", (app_no,))
    db.commit()
    flash(f"Harvesting info updated for {app_no}.", "success")
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

    if request.method == "POST":
        fields = ["name_ok", "mobile_ok", "state_ok", "district_ok", "village_ok",
                  "land_ok", "aadhar_doc_ok", "land_doc_ok", "kishan_doc_ok"]
        values = {f: 1 if request.form.get(f) == "ok" else 0 for f in fields}
        preference_crop = request.form.get("preference_crop", "")
        all_ok = all(values.values())

        db.execute(
            """INSERT INTO verification_results
               (farmer_app_no, name_ok, mobile_ok, state_ok, district_ok, village_ok,
                land_ok, aadhar_doc_ok, land_doc_ok, kishan_doc_ok, preference_crop,
                officer_name, verified, verified_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(farmer_app_no) DO UPDATE SET
                 name_ok=excluded.name_ok, mobile_ok=excluded.mobile_ok,
                 state_ok=excluded.state_ok, district_ok=excluded.district_ok,
                 village_ok=excluded.village_ok, land_ok=excluded.land_ok,
                 aadhar_doc_ok=excluded.aadhar_doc_ok, land_doc_ok=excluded.land_doc_ok,
                 kishan_doc_ok=excluded.kishan_doc_ok, preference_crop=excluded.preference_crop,
                 officer_name=excluded.officer_name, verified=excluded.verified,
                 verified_at=excluded.verified_at""",
            (
                app_no, values["name_ok"], values["mobile_ok"], values["state_ok"],
                values["district_ok"], values["village_ok"], values["land_ok"],
                values["aadhar_doc_ok"], values["land_doc_ok"], values["kishan_doc_ok"],
                preference_crop, session.get("officer_name"), 1 if all_ok else 0,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )
        if all_ok:
            db.execute("UPDATE farmers SET status='Verified' WHERE app_no=?", (app_no,))
            flash("All checks passed — farmer marked as Verified!", "success")
        else:
            flash("Verification saved. Some checks failed, farmer not yet fully verified.", "error")
        db.commit()
        return redirect(url_for("officer_form"))

    existing = db.execute("SELECT * FROM verification_results WHERE farmer_app_no=?", (app_no,)).fetchone()
    return render_template("officer_form.html", farmer=farmer, existing=existing, crops=CROPS)


@app.route("/api/districts/<state>")
def api_districts(state):
    return jsonify(STATE_DISTRICTS.get(state, []))


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)