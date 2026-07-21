# -*- coding: utf-8 -*-
"""
app.py — (W) Manpower Map backend

วิธีรัน (พัฒนา/ทดสอบในเครื่อง):
    pip install -r requirements.txt
    set FLASK_SECRET_KEY=<random string ยาวๆ>      (Windows: set, macOS/Linux: export)
    set COOKIE_SECURE=0                              (ใส่เฉพาะตอนทดสอบผ่าน http:// เท่านั้น)
    python app.py
    เปิด http://127.0.0.1:5000/

วิธีรันจริง (production):
    - ต้องตั้งค่า FLASK_SECRET_KEY เป็นค่าสุ่มที่คาดเดาไม่ได้ (ห้ามใช้ค่า default)
    - ต้องรันผ่าน HTTPS เท่านั้น (เช่นผ่าน reverse proxy อย่าง nginx + certbot)
    - อย่ารันด้วย `python app.py` ตรงๆ ให้ใช้ WSGI server เช่น:
        gunicorn -w 4 -b 0.0.0.0:8000 app:app
    - ต้องรัน migrate_db.py ก่อนใช้งานครั้งแรก เพื่อสร้างตาราง staff / manpower_nodes

ก่อนรันต้องมีไฟล์เหล่านี้อยู่โฟลเดอร์เดียวกัน:
    app.py, login.html, main.html, manpower_map.db (ผ่าน migrate_db.py แล้ว)
"""

import os
import sys

def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        try:
            text = kwargs.get('sep', ' ').join(str(a) for a in args)
            end = kwargs.get('end', '\n')
            sys.stdout.buffer.write((text + end).encode('utf-8'))
        except Exception:
            try:
                # last resort: ascii-only fallback
                ascii_text = ' '.join(str(a).encode('ascii', errors='replace').decode('ascii') for a in args)
                sys.stdout.write(ascii_text + kwargs.get('end', '\n'))
            except Exception:
                pass
import re
import json 
import sqlite3
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, g, send_from_directory, session, abort, make_response
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.realpath(os.path.join(BASE_DIR, "manpower_map.db"))
IMG_DIR = os.path.realpath(os.path.join(BASE_DIR, "img"))

# พิมพ์ path เต็มของไฟล์ DB ตอนเริ่มโปรแกรม เพื่อให้เช็คง่ายๆ ว่า
# ไฟล์ที่ app.py ใช้จริง ตรงกับไฟล์ที่เรากำลังเปิดดู/ตรวจสอบอยู่หรือไม่
# (สาเหตุที่พบบ่อยที่สุดของ "สมัครแล้วดูเหมือนสำเร็จแต่ไม่มีข้อมูลใน DB"
#  คือมีไฟล์ manpower_map.db ซ้ำกันหลายที่ในเครื่อง แล้วไปเปิดดูผิดไฟล์)
def _safe_print_db_info():
    try:
        print("=" * 70)
        print(f"[DB] ไฟล์ฐานข้อมูลที่ app.py จะใช้งานจริง (path เต็ม): {DB_PATH}")
        print(f"[DB] ไฟล์นี้มีอยู่จริงหรือไม่ตอนเริ่มโปรแกรม: {os.path.exists(DB_PATH)}")
        print("=" * 70)
    except UnicodeEncodeError:
        # stdout may not support these characters on some Windows consoles (cp1252)
        try:
            out = sys.stdout.buffer
            out.write(("=" * 70 + "\n").encode("utf-8"))
            out.write((f"[DB] ไฟล์ฐานข้อมูลที่ app.py จะใช้งานจริง (path เต็ม): {DB_PATH}\n").encode("utf-8"))
            out.write((f"[DB] ไฟล์นี้มีอยู่จริงหรือไม่ตอนเริ่มโปรแกรม: {os.path.exists(DB_PATH)}\n").encode("utf-8"))
            out.write(("=" * 70 + "\n").encode("utf-8"))
        except Exception:
            # final fallback: ASCII-only
            print("[DB] PATH:", DB_PATH)
            print("[DB] EXISTS:", os.path.exists(DB_PATH))


_safe_print_db_info()

MAX_FAILED_ATTEMPTS = 5          # ล็อกบัญชีชั่วคราวถ้าใส่รหัสผิดเกินจำนวนนี้
SESSION_HOURS = 8
SESSION_HOURS_REMEMBER = 24 * 30
LOGIN_RATE_LIMIT = 10            # จำนวนครั้งที่ยอมให้ลอง login ต่อ IP
LOGIN_RATE_WINDOW_SECONDS = 300  # ต่อช่วงเวลา 5 นาที
REGISTER_RATE_LIMIT = 5          # จำนวนครั้งที่ยอมให้สมัครบัญชีต่อ IP
REGISTER_RATE_WINDOW_SECONDS = 600  # ต่อช่วงเวลา 10 นาที
# สิทธิ์แก้ไขข้อมูลต้องพิจารณาทั้งตำแหน่งและฝ่ายจากฐานข้อมูล ไม่เชื่อค่า
# ใน session/cookie เพราะสามารถเก่า หรือถูกแก้ไขได้จากฝั่ง browser
#
# ให้สิทธิ์เฉพาะตำแหน่งที่ได้รับมอบหมายเท่านั้น:
# - พนักงานฝ่าย IT
# - หัวหน้างาน
# - เจ้าหน้าที่ฝ่ายบุคคล
# - ฝ่าย ES
# - หัวหน้าฝ่าย IT
#
# เก็บตำแหน่งและฝ่ายแยกกัน จึงตรวจเป็นคู่เพื่อไม่ให้ "พนักงาน" ของฝ่ายอื่น
# ได้สิทธิ์ไปด้วยโดยไม่ได้ตั้งใจ
IT_DEPARTMENT = "ฝ่าย IT"
HR_DEPARTMENT = "ฝ่ายทรัพยากรบุคคล"
ES_DEPARTMENT = "ฝ่าย ES"
EDITABLE_ROLES = ("หัวหน้างาน", "เจ้าหน้าที่ฝ่ายบุคคล", "ฝ่าย ES", "หัวหน้าฝ่าย IT")
EDITABLE_DEPARTMENTS = (IT_DEPARTMENT, HR_DEPARTMENT, ES_DEPARTMENT)
EDITABLE_ROLE_DEPARTMENT_PAIRS = frozenset({
    ("พนักงาน", IT_DEPARTMENT),
    # ระบบเดิมบันทึกเจ้าหน้าที่ฝ่ายบุคคลและฝ่าย ES เป็น role "พนักงาน"
    # ร่วมกับชื่อฝ่าย จึงรองรับรูปแบบข้อมูลนี้ด้วย
    ("พนักงาน", HR_DEPARTMENT),
    ("พนักงาน", ES_DEPARTMENT),
    ("เจ้าหน้าที่ฝ่ายบุคคล", HR_DEPARTMENT),
    ("ฝ่าย ES", ES_DEPARTMENT),
    ("หัวหน้าฝ่าย IT", IT_DEPARTMENT),
})
MIN_PASSWORD_LENGTH = 8


def can_edit_manpower(user):
    """Return whether a database user may edit manpower data.

    Permissions are deliberately allow-listed.  A department on its own never
    grants edit access: the user's job role must be one of the assigned roles.
    """
    if not user:
        return False
    role = user.get("role")
    department = user.get("dept_name")

    # หัวหน้างานได้รับสิทธิ์ตามตำแหน่ง โดยไม่จำกัดฝ่าย
    if role == "หัวหน้างาน":
        return True

    return (role, department) in EDITABLE_ROLE_DEPARTMENT_PAIRS

# ── ต้องตั้งค่าจริงผ่าน environment variable เสมอใน production ──
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
if not SECRET_KEY:
    # โหมดพัฒนา/เดโมเท่านั้น: สุ่มคีย์ใหม่ทุกครั้งที่รีสตาร์ท (ผู้ใช้จะหลุด session ทุกครั้งที่รีสตาร์ท)
    # ห้ามปล่อยแบบนี้ไปใช้งานจริง — ให้ตั้ง FLASK_SECRET_KEY เป็นค่าคงที่ที่สุ่มไว้ล่วงหน้า
    _safe_print("[คำเตือน] ไม่พบ FLASK_SECRET_KEY ใน environment — ใช้คีย์สุ่มชั่วคราว (ห้ามใช้ใน production)")
    SECRET_KEY = secrets.token_hex(32)

COOKIE_SECURE_ENV = os.environ.get("COOKIE_SECURE")
if COOKIE_SECURE_ENV is None:
    # ถ้าไม่ได้ตั้งค่าตัวแปร COOKIE_SECURE ไว้ และกำลังรันในโหมดทดสอบ/พัฒนา
    # จะใช้ session cookie แบบ non-secure เพื่อให้แอปทำงานผ่าน HTTP บน localhost ได้
    COOKIE_SECURE = False
    _safe_print("[INFO] COOKIE_SECURE ไม่ได้ตั้งค่าไว้ — ใช้ session cookie แบบ non-secure สำหรับการพัฒนา HTTP ท้องถิ่น")
else:
    COOKIE_SECURE = COOKIE_SECURE_ENV != "0"

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,        # กัน JavaScript อ่าน cookie (กัน XSS ขโมย session)
    SESSION_COOKIE_SAMESITE="Lax",       # กัน CSRF ข้ามเว็บไซต์เบื้องต้น
    SESSION_COOKIE_SECURE=COOKIE_SECURE, # ส่ง cookie เฉพาะผ่าน HTTPS (ปิดได้เฉพาะตอน dev ผ่าน http)
    PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
    JSON_SORT_KEYS=False,
)

# static_folder=None โดยตั้งใจ: ถ้าเปิดไว้พร้อม static_folder=BASE_DIR จะทำให้ทุกไฟล์ในโฟลเดอร์นี้
# (app.py, manpower_map.db ฯลฯ) ถูกเข้าถึงผ่าน URL ได้โดยตรง เราจึงเปิดเฉพาะไฟล์ที่ตั้งใจผ่าน route ด้านล่าง


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

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


def log_attempt(db, emp_id, success):
    db.execute(
        "INSERT INTO login_logs (emp_id, success, ip_address, user_agent) VALUES (?, ?, ?, ?)",
        (emp_id, 1 if success else 0, request.remote_addr, request.headers.get("User-Agent", "")[:255]),
    )
    db.commit()


# ---------------------------------------------------------------------------
# ป้องกันการยิงลอง login ถี่ๆ (brute force) แบบง่าย ๆ ต่อ IP — เสริมจากตัวล็อกบัญชีใน DB
# หมายเหตุ: ถ้า deploy หลาย process/หลายเครื่อง ให้เปลี่ยนไปใช้ Redis แทน dict ในหน่วยความจำนี้
# ---------------------------------------------------------------------------
_login_attempts_by_ip = defaultdict(deque)
_register_attempts_by_ip = defaultdict(deque)


def _rate_limited(bucket, ip, limit, window_seconds):
    now = time.time()
    dq = bucket[ip]
    while dq and now - dq[0] > window_seconds:
        dq.popleft()
    if len(dq) >= limit:
        return True
    dq.append(now)
    return False


def rate_limited(ip):
    return _rate_limited(_login_attempts_by_ip, ip, LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW_SECONDS)


def register_rate_limited(ip):
    return _rate_limited(_register_attempts_by_ip, ip, REGISTER_RATE_LIMIT, REGISTER_RATE_WINDOW_SECONDS)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def create_session(db, emp_id, role, full_name, remember):
    token = secrets.token_hex(32)
    hours = SESSION_HOURS_REMEMBER if remember else SESSION_HOURS
    expires = datetime.utcnow() + timedelta(hours=hours)
    db.execute(
        "INSERT INTO sessions (session_token, emp_id, expires_at) VALUES (?, ?, ?)",
        (token, emp_id, expires.isoformat()),
    )
    db.commit()

    session.clear()
    session.permanent = True
    app.permanent_session_lifetime = timedelta(hours=hours)
    session["emp_id"] = emp_id
    session["token"] = token
    session["role"] = role
    session["name"] = full_name


def destroy_session(db):
    token = session.get("token")
    if token:
        db.execute("DELETE FROM sessions WHERE session_token = ?", (token,))
        db.commit()
    session.clear()


def current_user():
    """คืนค่า dict ผู้ใช้ปัจจุบันถ้า session ยังใช้ได้จริง (ตรวจกับตาราง sessions ทุกครั้ง
    เพื่อให้ revoke/หมดอายุได้จริงฝั่ง server ไม่ใช่เชื่อ cookie เพียงอย่างเดียว), คืน None ถ้าไม่ใช่
    """
    emp_id = session.get("emp_id")
    token = session.get("token")
    if not emp_id or not token:
        return None

    db = get_db()
    row = db.execute(
        """SELECT s.emp_id, s.expires_at, e.full_name, e.role, e.dept_id,
                  d.dept_name
           FROM sessions s
           JOIN employees e ON e.emp_id = s.emp_id
           LEFT JOIN departments d ON d.dept_id = e.dept_id
           WHERE s.session_token = ? AND s.emp_id = ?""",
        (token, emp_id),
    ).fetchone()
    if row is None:
        session.clear()
        return None

    if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
        db.execute("DELETE FROM sessions WHERE session_token = ?", (token,))
        db.commit()
        session.clear()
        return None

    # อ่าน role/department ใหม่จาก DB ทุก request เพื่อให้การเปลี่ยนสิทธิ์มีผลทันที
    return {
        "emp_id": emp_id,
        "role": row["role"],
        "name": row["full_name"],
        "dept_id": row["dept_id"],
        "dept_name": row["dept_name"],
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify(success=False, message="กรุณาเข้าสู่ระบบก่อนใช้งาน"), 401
        g.current_user = user
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = getattr(g, "current_user", None) or current_user()
            if user is None:
                return jsonify(success=False, message="กรุณาเข้าสู่ระบบก่อนใช้งาน"), 401
            if user["role"] not in roles:
                return jsonify(success=False, message="คุณไม่มีสิทธิ์ทำรายการนี้"), 403
            g.current_user = user
            return view(*args, **kwargs)
        return wrapped
    return decorator


def edit_permission_required(view):
    """อนุญาตให้แก้ไขข้อมูลเฉพาะตำแหน่งที่ได้รับสิทธิ์เท่านั้น."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = getattr(g, "current_user", None) or current_user()
        if user is None:
            return jsonify(success=False, message="กรุณาเข้าสู่ระบบก่อนใช้งาน"), 401
        if not can_edit_manpower(user):
            return jsonify(
                success=False,
                message="คุณไม่มีสิทธิ์แก้ไขข้อมูลพนักงานสำหรับตำแหน่งของคุณ",
            ), 403
        g.current_user = user
        return view(*args, **kwargs)
    return wrapped


def require_ajax(view):
    """เช็ค header แบบง่ายๆ เพื่อลดความเสี่ยง CSRF สำหรับ endpoint ที่แก้ไขข้อมูล
    (ใช้ร่วมกับ SameSite=Lax cookie และ Content-Type: application/json ที่บังคับ CORS preflight อยู่แล้ว)
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return jsonify(success=False, message="คำขอไม่ถูกต้อง"), 403
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

EMP_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")
# Newcomer is recorded together with the shift they belong to.  Keeping this
# in the existing shift column avoids requiring a database migration.
ALLOWED_SHIFTS = ("White", "Yellow", "Day", "Newcomer", "Newcomer-White", "Newcomer-Yellow", "")
ALLOWED_NODE_TYPES = ("staff", "object")
# ประเภทการขาดงาน/ลา ต้องตรงกับ CHECK constraint ในตาราง attendance (migrate_attendance.py) เป๊ะ ๆ
ALLOWED_ATTENDANCE_TYPES = ("ขาดงาน", "ลาป่วย", "ลากิจ", "ลาพักร้อน", "มาสาย", "อื่นๆ")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# รายชื่อ Process ต้องตรงกับปุ่มกรองใน main.html (#processSelector) เป๊ะ ๆ เพื่อให้พนักงานที่สมัคร
# ผ่านหน้านี้ถูกจัดกลุ่ม/กรองถูกต้องทันทีในหน้ารายชื่อพนักงานและแผนผังโรงงาน
PROCESS_NAMES = (
    "CAB3 and Fr. Floor",
    "Rr. Floor",
    "Side Menber",
    "Deck",
    "Slat",
    "Shell3",
    "Shell3 Roller Hem",
    "Logistics",
    "Inspection",
)


def clean_text(value, max_len=255):
    if value is None:
        return ""
    text = str(value).strip()[:max_len]
    # ตัดอักขระที่ใช้ฝัง HTML/script ออกตั้งแต่ฝั่ง server (defense-in-depth, front-end escape ด้วยแล้ว)
    text = re.sub(r"[<>]", "", text)
    return text


# ---------------------------------------------------------------------------
# Page routes — เปิดเฉพาะไฟล์ที่ตั้งใจเท่านั้น ไม่เปิดทั้งโฟลเดอร์
# ---------------------------------------------------------------------------

@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "login.html")


@app.route("/login.html")
def serve_login_page():
    return send_from_directory(BASE_DIR, "login.html")


@app.route("/main.html")
def serve_main_page():
    return send_from_directory(BASE_DIR, "main.html")


@app.route("/register.html")
def serve_register_page():
    return send_from_directory(BASE_DIR, "register.html")


@app.route("/attendance.html")
def serve_attendance_page():
    return send_from_directory(BASE_DIR, "attendance.html")


@app.route("/img/<path:filename>")
def serve_image(filename):
    """เสิร์ฟรูปแผนผังโรงงาน/โซนต่างๆ ให้ main.html
    ถ้าไม่มีไฟล์ภาพจริง จะคืน SVG placeholder เพื่อให้ตอนทดสอบยังเห็นแผนผังได้
    """
    os.makedirs(IMG_DIR, exist_ok=True)

    full_path = os.path.realpath(os.path.join(IMG_DIR, filename))
    if os.path.commonpath([IMG_DIR, full_path]) != IMG_DIR:
        abort(404)

    if os.path.isfile(full_path):
        return send_from_directory(IMG_DIR, filename)

    label = os.path.splitext(os.path.basename(filename))[0] or "layout"
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900' viewBox='0 0 1600 900'>
      <rect width='1600' height='900' fill='#f8fafc'/>
      <rect x='30' y='30' width='1540' height='840' rx='24' fill='#ffffff' stroke='#cbd5e1' stroke-width='3'/>
      <rect x='70' y='70' width='1460' height='120' rx='16' fill='#800000' opacity='0.08'/>
      <text x='800' y='430' text-anchor='middle' font-family='Segoe UI, Arial, sans-serif' font-size='48' font-weight='700' fill='#800000'>{label}</text>
      <text x='800' y='490' text-anchor='middle' font-family='Segoe UI, Arial, sans-serif' font-size='24' fill='#64748b'>ภาพแผนผังจะถูกแสดงที่นี่เมื่อมีไฟล์จริง</text>
      <text x='800' y='535' text-anchor='middle' font-family='Segoe UI, Arial, sans-serif' font-size='20' fill='#94a3b8'>ระบบกำลังใช้ placeholder แบบอัตโนมัติ</text>
    </svg>"""
    return make_response(svg, 200, {"Content-Type": "image/svg+xml"})


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------

@app.route("/api/login", methods=["POST"])
def api_login():
    ip = request.remote_addr or "unknown"
    if rate_limited(ip):
        return jsonify(success=False, message="พยายามเข้าสู่ระบบถี่เกินไป กรุณารอสักครู่แล้วลองใหม่"), 429

    data = request.get_json(silent=True) or {}
    emp_id = (data.get("Emp_ID") or "").strip()
    password = data.get("password") or ""
    remember = bool(data.get("remember"))

    if not emp_id or not password:
        return jsonify(success=False, message="กรุณากรอกรหัสพนักงานและรหัสผ่านให้ครบถ้วน"), 400

    db = get_db()
    row = db.execute("SELECT * FROM employees WHERE emp_id = ?", (emp_id,)).fetchone()

    # ไม่พบผู้ใช้ -> ตอบข้อความกลาง ๆ เพื่อไม่ให้เดารหัสพนักงานได้ (ป้องกัน user enumeration)
    if row is None:
        log_attempt(db, emp_id, success=False)
        return jsonify(success=False, message="รหัสพนักงานหรือรหัสผ่านไม่ถูกต้อง"), 401

    if row["status"] == "locked":
        log_attempt(db, emp_id, success=False)
        return jsonify(success=False, message="บัญชีนี้ถูกล็อก กรุณาติดต่อฝ่าย IT"), 403

    if row["status"] == "inactive":
        log_attempt(db, emp_id, success=False)
        return jsonify(success=False, message="บัญชีนี้ถูกระงับการใช้งาน"), 403

    if not check_password_hash(row["password_hash"], password):
        new_failed = row["failed_attempts"] + 1
        new_status = "locked" if new_failed >= MAX_FAILED_ATTEMPTS else row["status"]
        db.execute(
            "UPDATE employees SET failed_attempts = ?, status = ? WHERE emp_id = ?",
            (new_failed, new_status, emp_id),
        )
        db.commit()
        log_attempt(db, emp_id, success=False)
        return jsonify(success=False, message="รหัสพนักงานหรือรหัสผ่านไม่ถูกต้อง"), 401

    # ล็อกอินสำเร็จ: รีเซ็ตตัวนับ, บันทึกเวลา, สร้าง session (server-side, httpOnly cookie)
    db.execute(
        "UPDATE employees SET failed_attempts = 0, last_login_at = ? WHERE emp_id = ?",
        (datetime.utcnow().isoformat(), emp_id),
    )
    db.commit()
    create_session(db, row["emp_id"], row["role"], row["full_name"], remember)
    log_attempt(db, emp_id, success=True)

    return jsonify(
        success=True,
        redirect="main.html",
        user={"empId": row["emp_id"], "name": row["full_name"], "role": row["role"]},
    )


@app.route("/api/logout", methods=["POST"])
@login_required
def api_logout():
    destroy_session(get_db())
    return jsonify(success=True)


@app.route("/api/session", methods=["GET"])
def api_session():
    """ให้ main.html ใช้ตรวจสอบสถานะ login กับ server จริง แทนการเชื่อ localStorage อย่างเดียว"""
    user = current_user()
    if user is None:
        return jsonify(success=False), 401
    can_edit = can_edit_manpower(user)
    return jsonify(
        success=True,
        user={
            "empId": user["emp_id"],
            "name": user["name"],
            "role": user["role"],
            "department": user["dept_name"],
            "canEdit": can_edit,
        },
    )


@app.route("/api/departments", methods=["GET"])
def api_departments():
    """รายชื่อแผนก — ใช้แสดงใน dropdown ตอนสมัครบัญชี (ไม่ต้อง login เพราะเป็นข้อมูลทั่วไป ไม่กระทบความปลอดภัย)"""
    db = get_db()
    rows = db.execute("SELECT dept_id, dept_name FROM departments ORDER BY dept_name").fetchall()
    return jsonify(success=True, departments=[{"deptId": r["dept_id"], "deptName": r["dept_name"]} for r in rows])


@app.route("/api/processes", methods=["GET"])
def api_processes():
    """รายชื่อ Process ทั้งหมด (ตรงกับตัวกรองใน main.html) — ใช้แสดงใน dropdown ตอนสมัครบัญชี"""
    return jsonify(success=True, processes=list(PROCESS_NAMES))


@app.route("/api/register", methods=["POST"])
@require_ajax
def api_register():
    """สมัครบัญชีพนักงานใหม่ด้วยตัวเอง (สำหรับทดสอบ/ใช้งานจริงเบื้องต้น)

    ข้อควรระวังด้านความปลอดภัยที่ตั้งใจไว้:
    - ยอมรับเฉพาะ role จากฟอร์มสมัครที่เป็น 'พนักงาน' หรือ 'หัวหน้างาน'
      เพื่อป้องกันการตั้งสิทธิ์สูงกว่าที่อนุญาต
    - จำกัดจำนวนครั้งการสมัครต่อ IP กันสแปม/สคริปต์ยิงสมัครรัว ๆ
    - ตรวจรูปแบบรหัสพนักงานและความยาวรหัสผ่านขั้นต่ำฝั่ง server เสมอ (ไม่เชื่อฝั่ง client อย่างเดียว)
    - แจ้งข้อความกลาง ๆ ถ้ารหัสพนักงานซ้ำ (ไม่บอกรายละเอียดเกินจำเป็น)
    """
    ip = request.remote_addr or "unknown"
    if register_rate_limited(ip):
        return jsonify(success=False, message="พยายามสมัครบัญชีถี่เกินไป กรุณารอสักครู่แล้วลองใหม่"), 429

    data = request.get_json(silent=True) or {}
    emp_id = (data.get("Emp_ID") or "").strip()
    full_name = clean_text(data.get("FullName"), 100)
    password = data.get("password") or ""
    confirm_password = data.get("confirmPassword") or ""
    role_name = (data.get("Role") or "").strip() or "พนักงาน"
    dept_id = data.get("DeptId")
    process_name = (data.get("ProcessName") or "").strip()

    if not emp_id or not full_name or not password:
        return jsonify(success=False, message="กรุณากรอกรหัสพนักงาน ชื่อ-นามสกุล และรหัสผ่านให้ครบถ้วน"), 400

    if not EMP_ID_RE.match(emp_id):
        return jsonify(success=False, message="รหัสพนักงานต้องเป็นตัวอักษร/ตัวเลข ความยาวไม่เกิน 32 ตัวอักษร"), 400

    if len(password) < MIN_PASSWORD_LENGTH:
        return jsonify(success=False, message=f"รหัสผ่านต้องมีความยาวอย่างน้อย {MIN_PASSWORD_LENGTH} ตัวอักษร"), 400

    if password != confirm_password:
        return jsonify(success=False, message="รหัสผ่านทั้งสองช่องไม่ตรงกัน"), 400

    if role_name not in ("พนักงาน", "หัวหน้างาน"):
        return jsonify(success=False, message="ตำแหน่งที่เลือกไม่ถูกต้อง"), 400

    # Process เป็นทางเลือก แต่ถ้าส่งมาต้องตรงกับรายชื่อ Process ที่มีจริงเท่านั้น (ป้องกันข้อมูลมั่ว/แปลกปลอม)
    if process_name and process_name not in PROCESS_NAMES:
        return jsonify(success=False, message="Process ที่เลือกไม่ถูกต้อง"), 400

    # dept_id เป็นทางเลือก แต่ถ้าส่งมาต้องเป็นแผนกที่มีอยู่จริงเท่านั้น
    clean_dept_id = None
    if dept_id not in (None, "", "null"):
        try:
            clean_dept_id = int(dept_id)
        except (TypeError, ValueError):
            return jsonify(success=False, message="แผนกที่เลือกไม่ถูกต้อง"), 400

    db = get_db()

    if clean_dept_id is not None:
        dept_row = db.execute("SELECT dept_id FROM departments WHERE dept_id = ?", (clean_dept_id,)).fetchone()
        if dept_row is None:
            return jsonify(success=False, message="แผนกที่เลือกไม่ถูกต้อง"), 400

    existing = db.execute("SELECT emp_id FROM employees WHERE emp_id = ?", (emp_id,)).fetchone()
    if existing is not None:
        return jsonify(success=False, message="มีรหัสพนักงานนี้ในระบบอยู่แล้ว กรุณาใช้รหัสพนักงานอื่นหรือเข้าสู่ระบบ"), 409

    # role ยอมรับเฉพาะ 'พนักงาน' หรือ 'หัวหน้างาน' ที่เลือกได้จากฟอร์มสมัคร
    password_hash = generate_password_hash(password)
    try:
        db.execute("BEGIN")
        db.execute(
            """INSERT INTO employees (emp_id, full_name, password_hash, role, dept_id, status)
               VALUES (?, ?, ?, ?, ?, 'active')""",
            (emp_id, full_name, password_hash, role_name, clean_dept_id),
        )
        db.commit()
    except sqlite3.Error as e:
        db.rollback()
        _safe_print(f"[REGISTER][ผิดพลาด] emp_id={emp_id} ลงทะเบียนไม่สำเร็จ: {e}")
        return jsonify(success=False, message="สมัครบัญชีไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"), 500

    # ยืนยันซ้ำอีกครั้งหลัง commit ว่าแถวถูกเขียนลงไฟล์ DB จริงๆ ก่อนบอกว่าสำเร็จ
    # (กันกรณีสับสนไฟล์ DB คนละไฟล์ หรือ silent failure อื่นๆ ที่ไม่ throw exception)
    check_row = db.execute("SELECT emp_id FROM employees WHERE emp_id = ?", (emp_id,)).fetchone()
    if check_row is None:
        _safe_print(f"[REGISTER][ผิดพลาด] emp_id={emp_id} commit แล้วแต่หาแถวไม่เจอ — เช็คว่าไฟล์ DB ถูกต้องหรือไม่: {DB_PATH}")
        return jsonify(success=False, message="สมัครบัญชีไม่สำเร็จ กรุณาลองใหม่อีกครั้ง (บันทึกลง DB ไม่สำเร็จ)"), 500

    _safe_print(f"[REGISTER][สำเร็จ] emp_id={emp_id} full_name={full_name!r} บันทึกลง {DB_PATH} เรียบร้อยแล้ว")
    return jsonify(success=True, message="สมัครบัญชีสำเร็จ กรุณาเข้าสู่ระบบ")


# ---------------------------------------------------------------------------
# Manpower map node API (ตำแหน่งหมุดบนผังโรงงาน)
# ---------------------------------------------------------------------------

@app.route("/api/get_manpower", methods=["GET"])
@login_required
def api_get_manpower():
    db = get_db()
    rows = db.execute("SELECT node_id, x, y, type, staff_id, staff_name, zone_id FROM manpower_nodes").fetchall()
    result = [
        {
            "id": r["node_id"],
            "x": r["x"],
            "y": r["y"],
            "type": r["type"],
            "staffId": r["staff_id"],
            "staffName": r["staff_name"],
            "zoneId": r["zone_id"],
        }
        for r in rows
    ]
    revision = db.execute(
        "SELECT COUNT(*) AS count, COALESCE(MAX(rowid), 0) AS last_rowid FROM manpower_nodes"
    ).fetchone()
    response = jsonify(result)
    response.headers["X-Manpower-Revision"] = f"{revision['last_rowid']}:{revision['count']}"
    return response


@app.route("/api/manpower_revision", methods=["GET"])
@login_required
def api_manpower_revision():
    """Small polling endpoint used to refresh the shared map for other users."""
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS count, COALESCE(MAX(rowid), 0) AS last_rowid FROM manpower_nodes"
    ).fetchone()
    return jsonify(revision=f"{row['last_rowid']}:{row['count']}")


@app.route("/api/manpower_summary", methods=["GET"])
@login_required
def api_manpower_summary():
    db = get_db()
    # A placed marker is the source of truth for the map count.  Do not filter
    # by process_name: newly added staff may not have a process yet, but their
    # marker still has to remain visible in the shared real-time total.
    placed_row = db.execute(
        "SELECT COUNT(*) AS cnt FROM manpower_nodes WHERE type = 'staff'"
    ).fetchone()
    # Total: count distinct staff who have a non-empty process_name
    total_row = db.execute(
        "SELECT COUNT(DISTINCT emp_id) AS cnt FROM staff WHERE COALESCE(process_name, '') != ''"
    ).fetchone()
    return jsonify(
        success=True,
        placed_count=int(placed_row["cnt"] if placed_row else 0),
        total_count=int(total_row["cnt"] if total_row else 0),
    )


@app.route("/api/manpower_shift_summary", methods=["GET"])
@login_required
def api_manpower_shift_summary():
    """คืนค่าจำนวนพนักงานบนแผนที่และจำนวนพนักงานในระบบ แยกตามกะ (shift)
    Response example:
    {
      "success": true,
      "placed_by_shift": {"White": 5, "Yellow": 3, "": 2},
      "staff_by_shift": {"White": 12, "Yellow": 8, "Newcomer": 1, "": 0},
      "white_yellow_total": 20
    }
    """
    db = get_db()
    # placed nodes grouped by shift (join manpower_nodes -> staff)
    rows = db.execute(
        "SELECT COALESCE(s.shift, '') AS shift, COUNT(*) AS cnt"
        " FROM manpower_nodes m JOIN staff s ON m.staff_id = s.emp_id"
        " WHERE m.type = 'staff' AND COALESCE(s.process_name, '') != '' GROUP BY COALESCE(s.shift, '')"
    ).fetchall()
    placed_by_shift = {r["shift"]: int(r["cnt"]) for r in rows}

    # total staff in system grouped by shift (merge employees + staff similar to api_get_employee_list)
    # Count only staff entries that have a process assigned
    rows2 = db.execute(
        "SELECT COALESCE(shift, '') AS shift, COUNT(DISTINCT emp_id) AS cnt "
        "FROM staff WHERE COALESCE(process_name, '') != '' GROUP BY COALESCE(shift, '')"
    ).fetchall()
    staff_by_shift = {r["shift"]: int(r["cnt"]) for r in rows2}

    # Always expose both keys so clients can render a stable White/Yellow summary
    # while all employees remain in the same staff table.
    placed_by_shift = {
        "White": placed_by_shift.get("White", 0),
        "Yellow": placed_by_shift.get("Yellow", 0),
        **{key: value for key, value in placed_by_shift.items() if key not in ("White", "Yellow")},
    }
    staff_by_shift = {
        "White": staff_by_shift.get("White", 0),
        "Yellow": staff_by_shift.get("Yellow", 0),
        **{key: value for key, value in staff_by_shift.items() if key not in ("White", "Yellow")},
    }
    white_yellow_total = staff_by_shift["White"] + staff_by_shift["Yellow"]

    return jsonify(
        success=True,
        placed_by_shift=placed_by_shift,
        staff_by_shift=staff_by_shift,
        white_yellow_total=white_yellow_total,
    )


@app.route("/api/save_manpower", methods=["POST"])
@login_required
@edit_permission_required
def api_save_manpower():
    data = None
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        data = request.get_json(silent=True)
    else:
        # request จาก sendBeacon อาจไม่มี header แบบ AJAX
        try:
            data = json.loads(request.get_data(as_text=True) or "null")
        except json.JSONDecodeError:
            data = None

    if not isinstance(data, list):
        return jsonify(success=False, message="รูปแบบข้อมูลไม่ถูกต้อง"), 400
    if len(data) > 5000:
        return jsonify(success=False, message="ข้อมูลมากเกินไป"), 400

    cleaned = []
    placed_staff_ids = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        node_id = clean_text(item.get("id"), 64)
        node_type = item.get("type") if item.get("type") in ALLOWED_NODE_TYPES else "staff"
        try:
            x = float(item.get("x"))
            y = float(item.get("y"))
        except (TypeError, ValueError):
            continue
        if not node_id:
            continue
        staff_id = clean_text(item.get("staffId"), 32)
        if node_type == "staff" and staff_id:
            if staff_id in placed_staff_ids:
                return jsonify(
                    success=False,
                    message=f"พนักงานรหัส '{staff_id}' ถูกวางซ้ำในแผนผังแล้ว",
                ), 409
            placed_staff_ids.add(staff_id)
        cleaned.append((
            node_id, x, y, node_type,
            staff_id or None,
            clean_text(item.get("staffName"), 100) or None,
            clean_text(item.get("zoneId"), 100) or None,
            g.current_user["emp_id"],
        ))

    db = get_db()
    try:
        db.execute("BEGIN")
        db.execute("DELETE FROM manpower_nodes")
        db.executemany(
            "INSERT INTO manpower_nodes (node_id, x, y, type, staff_id, staff_name, zone_id, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            cleaned,
        )
        db.commit()
    except sqlite3.Error as e:
        db.rollback()
        return jsonify(success=False, message=f"บันทึกไม่สำเร็จ: {e}"), 500

    revision = db.execute(
        "SELECT COUNT(*) AS count, COALESCE(MAX(rowid), 0) AS last_rowid FROM manpower_nodes"
    ).fetchone()
    return jsonify(success=True, saved=len(cleaned), revision=f"{revision['last_rowid']}:{revision['count']}")


# ---------------------------------------------------------------------------
# Staff list API (รายชื่อพนักงาน)
# ---------------------------------------------------------------------------

def row_to_staff_dict(r):
    return {
        "Emp_ID": r["emp_id"],
        "TM_Name": r["tm_name"],
        "Process_Name": r["process_name"],
        "Han_TM": r["han_tm"],
        "Process_Rank_S": r["process_rank_s"],
        "Process_Rank_Q": r["process_rank_q"],
        "Process_Rank_P": r["process_rank_p"],
        "Current_Skill": r["current_skill"],
        "Shift": r["shift"],
        "StartDate": r["start_date"],
        "Remark": r["remark"],
    }


@app.route("/api/get_staff_list", methods=["GET"])
@login_required
def api_get_staff_list():
    shift = request.args.get("shift", "").strip()
    db = get_db()
    if shift and shift != "All":
        if shift not in ALLOWED_SHIFTS:
            return jsonify([])
        rows = db.execute("SELECT * FROM staff WHERE shift = ?", (shift,)).fetchall()
        return jsonify([row_to_staff_dict(r) for r in rows])
    rows = db.execute("SELECT * FROM staff").fetchall()
    return jsonify([row_to_staff_dict(r) for r in rows])


@app.route("/api/get_employee_list", methods=["GET"])
@login_required
def api_get_employee_list():
    db = get_db()
    # Merge employees + staff rows; include role when available to categorise
    rows = db.execute(
        "SELECT combined.emp_id, combined.full_name, combined.process_name, combined.shift, e.role "
        "FROM ("
        "  SELECT e.emp_id, e.full_name, s.process_name, s.shift, 1 as from_emp "
        "  FROM employees e LEFT JOIN staff s ON e.emp_id = s.emp_id "
        "  UNION ALL "
        "  SELECT s.emp_id, s.tm_name AS full_name, s.process_name, s.shift, 0 as from_emp "
        "  FROM staff s WHERE s.emp_id NOT IN (SELECT emp_id FROM employees)"
        ") AS combined LEFT JOIN employees e ON combined.emp_id = e.emp_id"
        " ORDER BY combined.full_name"
    ).fetchall()

    def category_for(row):
        # If there is a role in employees table, use it; otherwise assume line worker
        role = row["role"]
        if not role or role == "พนักงาน":
            return "line"
        return "officer"

    return jsonify([
        {
            "Emp_ID": r["emp_id"],
            "TM_Name": r["full_name"],
            "Process_Name": r["process_name"] or "",
            "Shift": r["shift"] or "",
            "Category": category_for(r),
        }
        for r in rows
    ])


@app.route("/api/add_staff", methods=["POST"])
@login_required
@edit_permission_required
@require_ajax
def api_add_staff():
    data = request.get_json(silent=True) or {}

    emp_id = clean_text(data.get("Emp_ID"), 32)
    tm_name = clean_text(data.get("TM_Name"), 150)

    if not emp_id or not tm_name:
        return jsonify(success=False, message="กรุณากรอกรหัสพนักงานและชื่อ"), 400
    if not EMP_ID_RE.match(emp_id):
        return jsonify(success=False, message="รูปแบบรหัสพนักงานไม่ถูกต้อง"), 400

    shift = data.get("Shift") or ""
    if shift not in ALLOWED_SHIFTS:
        shift = ""

    try:
        current_skill = int(data.get("Current_Skill") or 0)
    except (TypeError, ValueError):
        current_skill = 0
    current_skill = max(0, min(100, current_skill))

    db = get_db()
    exists = db.execute("SELECT 1 FROM staff WHERE emp_id = ?", (emp_id,)).fetchone()
    if exists:
        return jsonify(success=False, message=f"มีรหัสพนักงาน '{emp_id}' อยู่ในรายชื่อแล้ว"), 409

    db.execute(
        "INSERT INTO staff (emp_id, tm_name, process_name, han_tm, process_rank_s, process_rank_q, "
        "process_rank_p, current_skill, shift, start_date, remark, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            emp_id, tm_name,
            clean_text(data.get("Process_Name"), 100),
            clean_text(data.get("Han_TM"), 100),
            clean_text(data.get("Process_Rank_S"), 20),
            clean_text(data.get("Process_Rank_Q"), 20),
            clean_text(data.get("Process_Rank_P"), 20),
            current_skill,
            shift,
            clean_text(data.get("StartDate"), 20),
            clean_text(data.get("Remark"), 500),
            g.current_user["emp_id"],
        ),
    )
    db.commit()
    return jsonify(success=True)


@app.route("/api/delete_staff", methods=["POST"])
@login_required
@edit_permission_required
@require_ajax
def api_delete_staff():
    data = request.get_json(silent=True) or {}
    emp_id = clean_text(data.get("Emp_ID"), 32)
    if not emp_id:
        return jsonify(success=False, message="ไม่พบรหัสพนักงาน"), 400

    db = get_db()
    db.execute("BEGIN")
    try:
        # ลบข้อมูลที่เกี่ยวข้องกับพนักงานนี้ให้หมด (staff, nodes, sessions, employees)
        # เพิ่มลบตารางข้อมูลเสริม เช่น attendance และ login_logs
        staff_deleted = db.execute("DELETE FROM staff WHERE emp_id = ?", (emp_id,)).rowcount
        node_deleted = db.execute("DELETE FROM manpower_nodes WHERE staff_id = ?", (emp_id,)).rowcount
        attendance_deleted = db.execute("DELETE FROM attendance WHERE emp_id = ?", (emp_id,)).rowcount
        login_logs_deleted = db.execute("DELETE FROM login_logs WHERE emp_id = ?", (emp_id,)).rowcount
        session_deleted = db.execute("DELETE FROM sessions WHERE emp_id = ?", (emp_id,)).rowcount
        employee_deleted = db.execute("DELETE FROM employees WHERE emp_id = ?", (emp_id,)).rowcount
        db.commit()
    except sqlite3.Error as e:
        db.rollback()
        print(f"[DELETE][ผิดพลาด] emp_id={emp_id} ลบพนักงานไม่สำเร็จ: {e}")
        return jsonify(success=False, message="ลบพนักงานไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"), 500

    if staff_deleted == 0 and node_deleted == 0 and attendance_deleted == 0 and login_logs_deleted == 0 and session_deleted == 0 and employee_deleted == 0:
        return jsonify(success=False, message="ไม่พบพนักงานคนนี้ในระบบ"), 404

    return jsonify(success=True, message="ลบพนักงานออกจากระบบเรียบร้อยแล้ว")


@app.route("/api/update_staff", methods=["POST"])
@login_required
@edit_permission_required
@require_ajax
def api_update_staff():
    """อัพเดทข้อมูลพนักงานบางฟิลด์ เช่น ชื่อ, process, shift, skill, remark"""
    data = request.get_json(silent=True) or {}
    emp_id = clean_text(data.get("Emp_ID"), 32)
    if not emp_id or not EMP_ID_RE.match(emp_id):
        return jsonify(success=False, message="รหัสพนักงานไม่ถูกต้อง"), 400

    # ฟิลด์ที่อนุญาตให้แก้ไข
    tm_name = clean_text(data.get("TM_Name"), 200)
    process_name = clean_text(data.get("Process_Name"), 100)
    han_tm = clean_text(data.get("Han_TM"), 100)
    pr_s = clean_text(data.get("Process_Rank_S"), 20)
    pr_q = clean_text(data.get("Process_Rank_Q"), 20)
    pr_p = clean_text(data.get("Process_Rank_P"), 20)
    try:
        current_skill = int(data.get("Current_Skill") or 0)
    except Exception:
        return jsonify(success=False, message="Current_Skill ต้องเป็นตัวเลข"), 400
    shift = clean_text(data.get("Shift"), 20)
    start_date = clean_text(data.get("StartDate"), 20)
    remark = clean_text(data.get("Remark"), 500)

    if process_name and process_name not in PROCESS_NAMES:
        return jsonify(success=False, message="Process ไม่ถูกต้อง"), 400
    if shift and shift not in ALLOWED_SHIFTS:
        return jsonify(success=False, message="Shift ไม่ถูกต้อง"), 400

    db = get_db()
    try:
        cur = db.execute(
            "UPDATE staff SET tm_name = ?, process_name = ?, han_tm = ?, process_rank_s = ?, process_rank_q = ?, process_rank_p = ?, current_skill = ?, shift = ?, start_date = ?, remark = ? WHERE emp_id = ?",
            (tm_name, process_name, han_tm, pr_s, pr_q, pr_p, current_skill, shift, start_date, remark, emp_id),
        )
        db.commit()
    except sqlite3.Error as e:
        db.rollback()
        print(f"[UPDATE][ผิดพลาด] emp_id={emp_id} อัพเดทไม่สำเร็จ: {e}")
        return jsonify(success=False, message="อัพเดทข้อมูลไม่สำเร็จ กรุณาลองใหม่"), 500

    if cur.rowcount == 0:
        return jsonify(success=False, message="ไม่พบพนักงานที่จะอัพเดท"), 404

    # คืนข้อมูลล่าสุดของพนักงานที่อัพเดทแล้ว
    row = db.execute("SELECT emp_id, tm_name, process_name, han_tm, process_rank_s, process_rank_q, process_rank_p, current_skill, shift, start_date, remark FROM staff WHERE emp_id = ?", (emp_id,)).fetchone()
    result = dict(row) if row else {}
    return jsonify(success=True, staff=result)


# ---------------------------------------------------------------------------
# Attendance API (ข้อมูลการขาดงาน/ลา/สาย ของพนักงาน)
# ---------------------------------------------------------------------------

def row_to_attendance_dict(r):
    return {
        "AttId": r["att_id"],
        "Emp_ID": r["emp_id"],
        "Date": r["att_date"],
        "Type": r["att_type"],
        "Reason": r["reason"],
        "RecordedBy": r["recorded_by"],
        "CreatedAt": r["created_at"],
    }


@app.route("/api/attendance/types", methods=["GET"])
@login_required
def api_attendance_types():
    """รายชื่อประเภทการขาด/ลา ที่ใช้งานได้ — ใช้แสดงใน dropdown ฝั่งหน้าเว็บ"""
    return jsonify(success=True, types=list(ALLOWED_ATTENDANCE_TYPES))


@app.route("/api/attendance/list", methods=["GET"])
@login_required
def api_attendance_list():
    """ดึงรายการขาดงาน กรองได้ด้วย emp_id, process, shift, ค้นหา และ/หรือช่วงเดือน (YYYY-MM ผ่าน ?month=)"""
    emp_id = clean_text(request.args.get("emp_id", ""), 32)
    process_name = clean_text(request.args.get("process", ""), 100)
    shift = clean_text(request.args.get("shift", ""), 20)
    query_text = clean_text(request.args.get("q", ""), 100)
    month = clean_text(request.args.get("month", ""), 7)  # เช่น '2026-07'

    query = "SELECT a.* FROM attendance a"
    query += " LEFT JOIN staff s ON s.emp_id = a.emp_id"
    query += " LEFT JOIN employees e ON e.emp_id = a.emp_id"
    query += " WHERE 1=1"
    params = []
    if emp_id:
        query += " AND a.emp_id = ?"
        params.append(emp_id)
    if process_name:
        query += " AND lower(s.process_name) = lower(?)"
        params.append(process_name)
    if shift:
        if shift not in ALLOWED_SHIFTS:
            return jsonify(success=False, message="Shift ไม่ถูกต้อง"), 400
        query += " AND s.shift = ?"
        params.append(shift)
    if query_text:
        query += " AND (lower(COALESCE(s.tm_name, e.full_name)) LIKE lower(?) OR lower(a.emp_id) LIKE lower(?))"
        like = f"%{query_text}%"
        params.extend([like, like])
    if month and re.match(r"^\d{4}-\d{2}$", month):
        query += " AND substr(a.att_date, 1, 7) = ?"
        params.append(month)
    query += " ORDER BY a.att_date DESC, a.att_id DESC"

    db = get_db()
    rows = db.execute(query, params).fetchall()
    return jsonify(success=True, records=[row_to_attendance_dict(r) for r in rows])


@app.route("/api/attendance/summary", methods=["GET"])
@login_required
def api_attendance_summary():
    """สรุปจำนวนวันขาด/ลา แยกตามพนักงานและประเภท (ใช้แสดงเป็นตาราง/กราฟสรุป)
    รองรับกรองตาม process, shift, ค้นหา, เดือนด้วย ?process=&shift=&q=&month=YYYY-MM
    """
    process_name = clean_text(request.args.get("process", ""), 100)
    shift = clean_text(request.args.get("shift", ""), 20)
    query_text = clean_text(request.args.get("q", ""), 100)
    month = clean_text(request.args.get("month", ""), 7)

    query = """
        SELECT a.emp_id, COALESCE(s.tm_name, e.full_name) AS tm_name,
               COALESCE(s.process_name, '') AS process_name, a.att_type, COUNT(*) as cnt
        FROM attendance a
        LEFT JOIN staff s ON s.emp_id = a.emp_id
        LEFT JOIN employees e ON e.emp_id = a.emp_id
        WHERE 1=1
    """
    params = []
    if process_name:
        query += " AND lower(s.process_name) = lower(?)"
        params.append(process_name)
    if shift:
        if shift not in ALLOWED_SHIFTS:
            return jsonify(success=False, message="Shift ไม่ถูกต้อง"), 400
        query += " AND s.shift = ?"
        params.append(shift)
    if query_text:
        query += " AND (lower(COALESCE(s.tm_name, e.full_name)) LIKE lower(?) OR lower(a.emp_id) LIKE lower(?))"
        like = f"%{query_text}%"
        params.extend([like, like])
    if month and re.match(r"^\d{4}-\d{2}$", month):
        query += " AND substr(a.att_date, 1, 7) = ?"
        params.append(month)
    query += " GROUP BY a.emp_id, a.att_type ORDER BY s.tm_name, a.att_type"

    db = get_db()
    rows = db.execute(query, params).fetchall()

    summary = {}
    for r in rows:
        emp_id = r["emp_id"]
        if emp_id not in summary:
            summary[emp_id] = {
                "empId": emp_id,
                "name": r["tm_name"] or emp_id,
                "processName": r["process_name"],
                "byType": {},
                "total": 0,
            }
        summary[emp_id]["byType"][r["att_type"]] = r["cnt"]
        summary[emp_id]["total"] += r["cnt"]

    result = sorted(summary.values(), key=lambda x: -x["total"])
    return jsonify(success=True, month=month or None, summary=result)


@app.route("/api/attendance/add", methods=["POST"])
@login_required
@edit_permission_required
@require_ajax
def api_attendance_add():
    data = request.get_json(silent=True) or {}

    emp_id = clean_text(data.get("Emp_ID"), 32)
    att_date = clean_text(data.get("Date"), 10)
    att_type = data.get("Type") or "ขาดงาน"
    reason = clean_text(data.get("Reason"), 500)

    if not emp_id or not att_date:
        return jsonify(success=False, message="กรุณาเลือกพนักงานและระบุวันที่"), 400

    if not DATE_RE.match(att_date):
        return jsonify(success=False, message="รูปแบบวันที่ไม่ถูกต้อง (ต้องเป็น YYYY-MM-DD)"), 400

    if att_type not in ALLOWED_ATTENDANCE_TYPES:
        return jsonify(success=False, message="ประเภทการขาด/ลาไม่ถูกต้อง"), 400

    db = get_db()
    staff_row = db.execute(
        "SELECT emp_id FROM employees WHERE emp_id = ? UNION SELECT emp_id FROM staff WHERE emp_id = ?",
        (emp_id, emp_id),
    ).fetchone()
    if staff_row is None:
        return jsonify(success=False, message=f"ไม่พบรหัสพนักงาน '{emp_id}' ในระบบ"), 404

    db.execute(
        "INSERT INTO attendance (emp_id, att_date, att_type, reason, recorded_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (emp_id, att_date, att_type, reason or None, g.current_user["emp_id"]),
    )
    db.commit()
    return jsonify(success=True)


@app.route("/api/attendance/delete", methods=["POST"])
@login_required
@edit_permission_required
@require_ajax
def api_attendance_delete():
    data = request.get_json(silent=True) or {}
    try:
        att_id = int(data.get("AttId"))
    except (TypeError, ValueError):
        return jsonify(success=False, message="ไม่พบรายการที่ต้องการลบ"), 400

    db = get_db()
    cur = db.execute("DELETE FROM attendance WHERE att_id = ?", (att_id,))
    db.commit()

    if cur.rowcount == 0:
        return jsonify(success=False, message="ไม่พบรายการนี้"), 404
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# Error handlers — ไม่โชว์ stack trace / รายละเอียดภายในให้ผู้ใช้เห็น
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return jsonify(success=False, message="ไม่พบหน้าที่ต้องการ"), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify(success=False, message="เกิดข้อผิดพลาดภายในระบบ"), 500


if __name__ == "__main__":
    print("=" * 60)
    print(f"กำลังใช้ฐานข้อมูลไฟล์นี้: {DB_PATH}")
    print(f"ไฟล์นี้มีอยู่จริงหรือไม่: {os.path.exists(DB_PATH)}")
    if not os.environ.get("FLASK_SECRET_KEY"):
        print("!! ยังไม่ได้ตั้งค่า FLASK_SECRET_KEY — โหมดนี้ใช้ทดสอบเท่านั้น ห้ามใช้ใน production !!")
    print("=" * 60)
    # debug=False เสมอ: ห้ามเปิด debug mode ใน production (จะเปิดช่องให้รันโค้ดจากภายนอกได้ผ่าน debugger)
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
