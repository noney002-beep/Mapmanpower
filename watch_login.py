# -*- coding: utf-8 -*-
"""
watch_login.py — เครื่องมือช่วยทดสอบ login ใน Browser ควบคู่กับ Python

วิธีใช้:
    1. เปิด terminal ที่ 1: รัน app.py ตามปกติ
         set FLASK_SECRET_KEY=สุ่มข้อความยาวๆ
         set COOKIE_SECURE=0
         python app.py
    2. เปิด terminal ที่ 2 (โฟลเดอร์เดียวกัน): รันไฟล์นี้
         python watch_login.py
    3. เปิดเบราว์เซอร์ไปที่ http://127.0.0.1:5000/  (ห้ามดับเบิลคลิกไฟล์ html โดยตรง)
       แล้วลอง login ด้วยบัญชีที่มีอยู่ เช่น Emp_ID = EMP0001, password = 0001
    4. ดูที่ terminal ที่ 2 — ถ้า login ผ่านจริง จะเห็นแถวใหม่ขึ้นทันทีทั้งใน
       "login_logs" (บันทึกทุกครั้งที่พยายาม login ทั้งสำเร็จ/ไม่สำเร็จ)
       และ "sessions" (สร้างขึ้นเฉพาะตอน login สำเร็จเท่านั้น)

    กด Ctrl+C เพื่อหยุดสคริปต์นี้เมื่อทดสอบเสร็จ
"""

import os
import sqlite3
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "manpower_map.db")

POLL_SECONDS = 1.5


def fetch_state(db):
    logs = db.execute(
        "SELECT log_id, emp_id, success, ip_address, logged_at FROM login_logs ORDER BY log_id"
    ).fetchall()
    sessions = db.execute(
        "SELECT session_token, emp_id, created_at, expires_at FROM sessions ORDER BY created_at"
    ).fetchall()
    return logs, sessions


def main():
    if not os.path.exists(DB_PATH):
        print(f"[ผิดพลาด] ไม่พบไฟล์ฐานข้อมูลที่: {DB_PATH}")
        print("ตรวจสอบว่าไฟล์นี้อยู่โฟลเดอร์เดียวกับ manpower_map.db")
        return

    print("=" * 70)
    print(f"[watch_login] กำลังเฝ้าดูไฟล์: {DB_PATH}")
    print("[watch_login] เปิดเบราว์เซอร์ไปที่ http://127.0.0.1:5000/ แล้วลอง login ได้เลย")
    print("=" * 70)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    seen_log_ids = set()
    seen_session_tokens = set()

    # โหลดของเดิมที่มีอยู่ก่อนไว้ก่อน จะได้ไม่ print ซ้ำของเก่า
    logs, sessions = fetch_state(db)
    for row in logs:
        seen_log_ids.add(row["log_id"])
    for row in sessions:
        seen_session_tokens.add(row["session_token"])

    try:
        while True:
            time.sleep(POLL_SECONDS)
            logs, sessions = fetch_state(db)

            for row in logs:
                if row["log_id"] not in seen_log_ids:
                    seen_log_ids.add(row["log_id"])
                    status = "สำเร็จ ✅" if row["success"] else "ไม่สำเร็จ ❌"
                    print(
                        f"[LOGIN LOG] emp_id={row['emp_id']}  ผลลัพธ์={status}  "
                        f"ip={row['ip_address']}  เวลา={row['logged_at']}"
                    )

            for row in sessions:
                if row["session_token"] not in seen_session_tokens:
                    seen_session_tokens.add(row["session_token"])
                    print(
                        f"[SESSION ใหม่] emp_id={row['emp_id']}  สร้างเมื่อ={row['created_at']}  "
                        f"หมดอายุ={row['expires_at']}"
                    )
                    print("   -> แปลว่า login ผ่าน browser สำเร็จจริง และ server สร้าง session ให้แล้ว")

    except KeyboardInterrupt:
        print("\n[watch_login] หยุดการเฝ้าดูแล้ว")
    finally:
        db.close()


if __name__ == "__main__":
    main()