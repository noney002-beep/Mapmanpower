# -*- coding: utf-8 -*-
"""
clear_employees.py — ลบชื่อพนักงานทั้งหมดออกจากระบบ
เพื่อให้สามารถใส่ชื่อและข้อมูลจริงของพนักงานได้
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "manpower_map.db")

def clear_employees():
    if not os.path.exists(DB_PATH):
        print(f"[ผิดพลาด] ไม่พบไฟล์ฐานข้อมูลที่: {DB_PATH}")
        return False

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    try:
        # ลบข้อมูลทั้งหมดจากตาราง staff
        cur.execute("DELETE FROM staff")
        staff_deleted = cur.rowcount
        print(f"[สำเร็จ] ลบข้อมูลพนักงานจากตาราง staff: {staff_deleted} รายการ")

        # ลบข้อมูล manpower_nodes ที่อ้างอิงไปยัง staff (ถ้ามี)
        cur.execute("DELETE FROM manpower_nodes WHERE staff_id IN (SELECT emp_id FROM staff)")
        print(f"[สำเร็จ] ลบข้อมูล manpower_nodes ที่เกี่ยวข้อง")

        # ลบข้อมูลพนักงานจากตาราง employees (เฉพาะผู้ที่สมัครบัญชีเอง)
        # เก็บผู้ดูแลระบบไว้
        cur.execute("DELETE FROM employees WHERE role != 'ผู้ดูแลระบบ'")
        emp_deleted = cur.rowcount
        print(f"[สำเร็จ] ลบข้อมูลพนักงานจากตาราง employees: {emp_deleted} รายการ (เก็บ admin ไว้)")

        # ลบข้อมูลการขาดงานที่เกี่ยวข้อง (ลบข้อมูลการขาดทั้งหมด)
        cur.execute("DELETE FROM attendance")
        att_deleted = cur.rowcount
        print(f"[สำเร็จ] ลบข้อมูลการขาดงาน/ลา: {att_deleted} รายการ")

        conn.commit()
        print("\n[เสร็จสิ้น] ลบชื่อพนักงานและข้อมูลที่เกี่ยวข้องทั้งหมดเรียบร้อยแล้ว")
        print("คุณสามารถใส่ชื่อและข้อมูลจริงของพนักงานได้แล้ว")
        return True

    except Exception as e:
        print(f"[ผิดพลาด] เกิดข้อผิดพลาด: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    import sys
    print("=" * 70)
    print("เครื่องมือลบชื่อพนักงานทั้งหมด")
    print("=" * 70)
    print(f"\nไฟล์ฐานข้อมูล: {DB_PATH}")
    print(f"มีอยู่จริง: {os.path.exists(DB_PATH)}\n")

    if not os.path.exists(DB_PATH):
        print("[ผิดพลาด] ไม่พบไฟล์ฐานข้อมูล กรุณาตรวจสอบการติดตั้งโปรแกรม")
        sys.exit(1)

    # ตรวจสอบว่ามีการส่ง --confirm flag มาหรือไม่
    force_confirm = '--confirm' in sys.argv or '--yes' in sys.argv
    
    if force_confirm:
        print("⚠️  ค่าที่ยืนยันแล้ว: จะดำเนินการลบข้อมูล...\n")
        success = clear_employees()
        sys.exit(0 if success else 1)
    else:
        response = input("⚠️  คำเตือน: การดำเนินการนี้จะลบชื่อพนักงานทั้งหมด และข้อมูลการขาดงานทั้งหมดออกจากระบบ\n"
                        "คุณแน่ใจหรือว่าต้องการดำเนินการต่อ? (พิมพ์ 'ใช่' เพื่อยืนยัน): ")

        if response.strip().lower() in ['ใช่', 'yes', 'y']:
            success = clear_employees()
            sys.exit(0 if success else 1)
        else:
            print("ยกเลิก: ไม่ได้ลบข้อมูลใด ๆ")
            sys.exit(0)
