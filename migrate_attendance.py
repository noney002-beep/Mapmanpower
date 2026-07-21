# -*- coding: utf-8 -*-
"""
migrate_attendance.py — สร้างตาราง 'attendance' (ข้อมูลการขาด/ลา/สาย ของพนักงาน)
เพิ่มเข้าไปใน manpower_map.db ที่มีอยู่แล้ว โดยไม่กระทบตาราง/ข้อมูลเดิมเลย

วิธีใช้:
    python migrate_attendance.py

รันได้ซ้ำหลายครั้งอย่างปลอดภัย (ใช้ CREATE TABLE IF NOT EXISTS)
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "manpower_map.db")


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"[ผิดพลาด] ไม่พบไฟล์ฐานข้อมูลที่: {DB_PATH}")
        return False

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            att_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id      TEXT NOT NULL,                 -- รหัสพนักงาน (อ้างอิง staff.emp_id)
            att_date    TEXT NOT NULL,                  -- วันที่ขาด/ลา รูปแบบ YYYY-MM-DD
            att_type    TEXT NOT NULL DEFAULT 'ขาดงาน'
                        CHECK (att_type IN ('ขาดงาน', 'ลาป่วย', 'ลากิจ', 'ลาพักร้อน', 'มาสาย', 'อื่นๆ')),
            reason      TEXT,                           -- หมายเหตุ/สาเหตุ (ไม่บังคับ)
            recorded_by TEXT,                            -- emp_id ของผู้บันทึกรายการนี้ (audit trail)
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (emp_id) REFERENCES staff(emp_id)
        )
    """)

    # ทำ index ให้ query สรุปรายเดือน/รายคนเร็วขึ้น
    cur.execute("CREATE INDEX IF NOT EXISTS idx_attendance_emp_id ON attendance(emp_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(att_date)")

    conn.commit()

    # ตรวจว่าตารางถูกสร้างจริง
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='attendance'"
    ).fetchone()
    conn.close()

    if row:
        print("[สำเร็จ] สร้างตาราง 'attendance' เรียบร้อยแล้ว (หรือมีอยู่แล้วก่อนหน้านี้)")
        return True
    else:
        print("[ผิดพลาด] สร้างตารางไม่สำเร็จ")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print(f"กำลังแก้ไขฐานข้อมูลไฟล์นี้: {DB_PATH}")
    print("=" * 60)
    migrate()
