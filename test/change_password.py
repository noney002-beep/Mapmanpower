"""
สคริปต์เปลี่ยนรหัสผ่านพนักงาน

วิธีใช้ (แนะนำ - ง่ายและชัวร์ที่สุด):
    python change_password.py EMP0021 mypassword123

หรือรันเฉย ๆ แล้วให้ระบบถามทีละขั้น:
    python change_password.py
"""
import os
import sys
import sqlite3
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "manpower_map.db")


def change_password(emp_id: str, new_password: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    row = cur.execute("SELECT emp_id, full_name FROM employees WHERE emp_id = ?", (emp_id,)).fetchone()
    if row is None:
        print(f"[ผิดพลาด] ไม่พบรหัสพนักงาน '{emp_id}' ในระบบ")
        conn.close()
        return False

    new_hash = generate_password_hash(new_password)
    cur.execute(
        "UPDATE employees SET password_hash = ?, failed_attempts = 0, status = 'active' WHERE emp_id = ?",
        (new_hash, emp_id),
    )
    conn.commit()
    conn.close()

    print(f"[สำเร็จ] เปลี่ยนรหัสผ่านของ {row[0]} ({row[1]}) เรียบร้อยแล้ว")
    print("(บัญชีนี้ถูกปลดล็อกและรีเซ็ตตัวนับรหัสผ่านผิดให้ด้วย)")
    return True


if __name__ == "__main__":
    print("=" * 50)
    print(" สคริปต์เปลี่ยนรหัสผ่านพนักงาน")
    print("=" * 50)
    print(f"กำลังแก้ไขฐานข้อมูลไฟล์นี้: {DB_PATH}")
    print("(เช็คให้แน่ใจว่าเป็นไฟล์เดียวกับที่ app.py ใช้อยู่)")
    print()

    if not os.path.exists(DB_PATH):
        print(f"[ผิดพลาด] ไม่พบไฟล์ฐานข้อมูลที่: {DB_PATH}")
        print("ตรวจสอบว่า change_password.py อยู่โฟลเดอร์เดียวกับ manpower_map.db")
        input("\nกด Enter เพื่อปิดหน้าต่างนี้...")
        sys.exit(1)

    # กรณีที่ 1: พิมพ์รหัสพนักงาน+รหัสผ่านมาพร้อมคำสั่งเลย (แนะนำ)
    if len(sys.argv) == 3:
        emp_id = sys.argv[1].strip()
        new_password = sys.argv[2]

    # กรณีที่ 2: รันเฉย ๆ แล้วให้ถามทีละขั้น (ใช้ input() ธรรมดา เห็นตัวอักษรที่พิมพ์ชัดเจน)
    elif len(sys.argv) == 1:
        print("\nโหมดถามทีละขั้น (จะเห็นตัวอักษรที่พิมพ์ตามปกติ)\n")
        emp_id = input("1) กรอกรหัสพนักงาน (เช่น EMP0021) แล้วกด Enter: ").strip()
        new_password = input("2) กรอกรหัสผ่านใหม่ แล้วกด Enter: ").strip()
        confirm = input("3) กรอกรหัสผ่านใหม่อีกครั้งเพื่อยืนยัน แล้วกด Enter: ").strip()
        if new_password != confirm:
            print("\n[ผิดพลาด] รหัสผ่านทั้งสองครั้งไม่ตรงกัน ยกเลิกการเปลี่ยนรหัสผ่าน")
            input("\nกด Enter เพื่อปิดหน้าต่างนี้...")
            sys.exit(1)
    else:
        print("\nวิธีใช้: python change_password.py <รหัสพนักงาน> <รหัสผ่านใหม่>")
        print("ตัวอย่าง: python change_password.py EMP0021 newpass456")
        input("\nกด Enter เพื่อปิดหน้าต่างนี้...")
        sys.exit(1)

    if not emp_id or not new_password:
        print("\n[ผิดพลาด] รหัสพนักงานหรือรหัสผ่านห้ามเว้นว่าง")
        input("\nกด Enter เพื่อปิดหน้าต่างนี้...")
        sys.exit(1)

    print()
    change_password(emp_id, new_password)
    input("\nกด Enter เพื่อปิดหน้าต่างนี้...")