import os
import sqlite3
import tempfile
import unittest

import app as app_module


class DeleteEmployeeTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_manpower_map.db")
        app_module.DB_PATH = self.db_path

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE employees (
                emp_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                dept_id INTEGER,
                status TEXT NOT NULL,
                failed_attempts INTEGER DEFAULT 0,
                last_login_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE departments (
                dept_id INTEGER PRIMARY KEY,
                dept_name TEXT NOT NULL UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE staff (
                emp_id TEXT PRIMARY KEY,
                tm_name TEXT,
                process_name TEXT,
                han_tm TEXT,
                process_rank_s TEXT,
                process_rank_q TEXT,
                process_rank_p TEXT,
                current_skill INTEGER,
                shift TEXT,
                start_date TEXT,
                remark TEXT,
                created_by TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE manpower_nodes (
                node_id TEXT PRIMARY KEY,
                x REAL,
                y REAL,
                type TEXT,
                staff_id TEXT,
                staff_name TEXT,
                zone_id TEXT,
                updated_by TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE sessions (
                session_token TEXT PRIMARY KEY,
                emp_id TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE attendance (
                att_id INTEGER PRIMARY KEY AUTOINCREMENT,
                emp_id TEXT NOT NULL,
                att_date TEXT NOT NULL,
                att_type TEXT NOT NULL,
                reason TEXT,
                recorded_by TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE login_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                emp_id TEXT,
                success INTEGER,
                ip_address TEXT,
                user_agent TEXT,
                logged_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO departments (dept_id, dept_name) VALUES (?, ?)", (1, "ฝ่าย IT"))
        conn.execute("INSERT INTO employees (emp_id, full_name, password_hash, role, dept_id, status) VALUES (?, ?, ?, ?, ?, ?)", ("E001", "Test User", "hash", "หัวหน้างาน", 1, "active"))
        conn.execute("INSERT INTO staff (emp_id, tm_name, process_name, created_by) VALUES (?, ?, ?, ?)", ("E001", "Test User", "Process A", "admin"))
        conn.execute("INSERT INTO manpower_nodes (node_id, x, y, type, staff_id, staff_name, zone_id, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("N1", 1.0, 2.0, "staff", "E001", "Test User", "Z1", "admin"))
        conn.execute("INSERT INTO sessions (session_token, emp_id, expires_at) VALUES (?, ?, ?)", ("tok1", "E001", "2099-01-01T00:00:00"))
        conn.execute("INSERT INTO attendance (emp_id, att_date, att_type, reason, recorded_by) VALUES (?, ?, ?, ?, ?)", ("E001", "2026-07-16", "ขาดงาน", "Test absence", "admin"))
        conn.execute("INSERT INTO login_logs (emp_id, success, ip_address, user_agent) VALUES (?, ?, ?, ?)", ("E001", 1, "127.0.0.1", "pytest"))
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.close()
        except sqlite3.Error:
            pass
        self.tmp_dir.cleanup()

    def test_update_staff_updates_fields(self):
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["emp_id"] = "E001"
            sess["token"] = "tok1"
            sess["role"] = "หัวหน้างาน"
            sess["name"] = "Admin"

        response = client.post(
            "/api/update_staff",
            json={
                "Emp_ID": "E001",
                "TM_Name": "Updated Name",
                "Process_Name": "CAB3 and Fr. Floor",
                "Han_TM": "New Han",
                "Process_Rank_S": "S+",
                "Process_Rank_Q": "Q+",
                "Process_Rank_P": "P+",
                "Current_Skill": 99,
                "Shift": "Day",
                "StartDate": "2026-07-16",
                "Remark": "Updated remark",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["staff"]["tm_name"], "Updated Name")
        self.assertEqual(data["staff"]["process_name"], "CAB3 and Fr. Floor")
        self.assertEqual(data["staff"]["shift"], "Day")
        self.assertEqual(data["staff"]["current_skill"], 99)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT tm_name, process_name, shift, current_skill FROM staff WHERE emp_id = ?", ("E001",)).fetchone()
        self.assertEqual(row[0], "Updated Name")
        self.assertEqual(row[1], "CAB3 and Fr. Floor")
        self.assertEqual(row[2], "Day")
        self.assertEqual(row[3], 99)
        conn.close()

    def test_save_manpower_persists_positions_for_other_users(self):
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["emp_id"] = "E001"
            sess["token"] = "tok1"

        response = client.post(
            "/api/save_manpower",
            json=[{
                "id": "N-shared",
                "x": 321.5,
                "y": 654.25,
                "type": "staff",
                "staffId": "E001",
                "staffName": "Test User",
                "zoneId": "cab3_fr_floor",
            }],
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT node_id, x, y, staff_id, zone_id FROM manpower_nodes"
        ).fetchall()
        self.assertEqual(rows, [("N-shared", 321.5, 654.25, "E001", "cab3_fr_floor")])
        conn.close()

    def test_save_manpower_rejects_duplicate_staff_markers(self):
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["emp_id"] = "E001"
            sess["token"] = "tok1"

        response = client.post(
            "/api/save_manpower",
            json=[
                {"id": "N-1", "x": 10, "y": 20, "type": "staff", "staffId": "E001"},
                {"id": "N-2", "x": 30, "y": 40, "type": "staff", "staffId": "E001"},
            ],
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.get_json()["success"])

    def test_map_summary_counts_every_saved_staff_marker(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO manpower_nodes (node_id, x, y, type, staff_id, staff_name, zone_id, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("N-no-process", 10, 20, "staff", "NEW001", "New staff", "Z2", "E001"),
        )
        conn.commit()
        conn.close()

        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["emp_id"] = "E001"
            sess["token"] = "tok1"

        response = client.get("/api/manpower_summary")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["placed_count"], 2)

    def test_department_name_stored_as_a_role_does_not_grant_edit_access(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE employees SET role = ? WHERE emp_id = ?",
            (app_module.EDITABLE_DEPARTMENTS[0], "E001"),
        )
        conn.commit()
        conn.close()

        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["emp_id"] = "E001"
            sess["token"] = "tok1"

        response = client.get("/api/session")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["user"]["canEdit"])

    def test_only_assigned_role_and_department_combinations_can_edit(self):
        allowed_users = (
            {"role": "พนักงาน", "dept_name": "ฝ่าย IT"},
            {"role": "พนักงาน", "dept_name": "ฝ่ายทรัพยากรบุคคล"},
            {"role": "พนักงาน", "dept_name": "ฝ่าย ES"},
            {"role": "หัวหน้างาน", "dept_name": None},
            {"role": "เจ้าหน้าที่ฝ่ายบุคคล", "dept_name": "ฝ่ายทรัพยากรบุคคล"},
            {"role": "ฝ่าย ES", "dept_name": "ฝ่าย ES"},
            {"role": "หัวหน้าฝ่าย IT", "dept_name": "ฝ่าย IT"},
        )
        denied_users = (
            {"role": "พนักงาน", "dept_name": "ฝ่ายผลิต"},
            {"role": "เจ้าหน้าที่ฝ่ายบุคคล", "dept_name": "ฝ่าย IT"},
            {"role": "ฝ่าย ES", "dept_name": "ฝ่าย IT"},
            {"role": "หัวหน้าฝ่าย IT", "dept_name": "ฝ่าย ES"},
            {"role": "ผู้ดูแลระบบ", "dept_name": "ฝ่าย IT"},
        )

        for user in allowed_users:
            self.assertTrue(app_module.can_edit_manpower(user), user)
        for user in denied_users:
            self.assertFalse(app_module.can_edit_manpower(user), user)

    def test_delete_staff_removes_employee_account_and_related_data(self):
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["emp_id"] = "E001"
            sess["token"] = "tok1"
            sess["role"] = "หัวหน้างาน"
            sess["name"] = "Admin"

        response = client.post(
            "/api/delete_staff",
            json={"Emp_ID": "E001"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        conn = sqlite3.connect(self.db_path)
        self.assertIsNone(conn.execute("SELECT 1 FROM employees WHERE emp_id = ?", ("E001",)).fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM staff WHERE emp_id = ?", ("E001",)).fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM manpower_nodes WHERE staff_id = ?", ("E001",)).fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM sessions WHERE emp_id = ?", ("E001",)).fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM attendance WHERE emp_id = ?", ("E001",)).fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM login_logs WHERE emp_id = ?", ("E001",)).fetchone())
        conn.close()

    def test_unassigned_employee_cannot_update_staff(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE employees SET role = ?, dept_id = NULL WHERE emp_id = ?", ("พนักงาน", "E001"))
        conn.commit()
        conn.close()

        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["emp_id"] = "E001"
            sess["token"] = "tok1"

        response = client.post(
            "/api/update_staff",
            json={"Emp_ID": "E001"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
