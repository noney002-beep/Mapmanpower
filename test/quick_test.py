# -*- coding: utf-8 -*-
"""
quick_test.py

สคริปต์ทดสอบเบื้องต้นสำหรับโปรแกรม Manpower Map
- สร้างผู้ใช้งานชั่วคราว
- เข้าสู่ระบบ
- บันทึกตำแหน่ง manpower node
- ดึงข้อมูลจาก server

วิธีใช้:
    python quick_test.py
"""

import os
import sqlite3
import time
from flask import json

# ต้องตั้งค่า COOKIE_SECURE=0 สำหรับการรันผ่าน HTTP ในเครื่อง
os.environ.setdefault('COOKIE_SECURE', '0')

import app

TMP_EMP_ID = f'TMPTEST{int(time.time()) % 1000000:06d}'
TMP_NODE_ID = f'tmp_node_{int(time.time())}'

print('DB path:', app.DB_PATH)
print('Temp employee id:', TMP_EMP_ID)

client = app.app.test_client()
client.testing = True

headers = {'X-Requested-With': 'XMLHttpRequest'}

print('\n1) Register temporary user...')
resp = client.post(
    '/api/register',
    json={
        'Emp_ID': TMP_EMP_ID,
        'FullName': 'Quick Test User',
        'password': 'quicktest123',
        'confirmPassword': 'quicktest123',
        'ProcessName': 'CAB3 and Fr. Floor'
    },
    headers=headers,
)
print('status:', resp.status_code)
print(resp.get_data(as_text=True))

print('\n2) Login temporary user...')
resp = client.post(
    '/api/login',
    json={'Emp_ID': TMP_EMP_ID, 'password': 'quicktest123', 'remember': False},
    headers=headers,
)
print('status:', resp.status_code)
print(resp.get_data(as_text=True))

if resp.status_code != 200:
    raise SystemExit('Login failed, aborting test')

print('\n3) Save manpower node...')
node_data = [
    {
        'id': TMP_NODE_ID,
        'x': 120,
        'y': 130,
        'type': 'staff',
        'staffId': TMP_EMP_ID,
        'staffName': 'Quick Test User',
        'zoneId': 'Z1',
    }
]
resp = client.post('/api/save_manpower', json=node_data, headers=headers)
print('status:', resp.status_code)
print(resp.get_data(as_text=True))

print('\n4) Load manpower nodes...')
resp = client.get('/api/get_manpower')
print('status:', resp.status_code)
print(resp.get_data(as_text=True))

print('\n5) Verify DB row...')
conn = sqlite3.connect(app.DB_PATH)
cur = conn.cursor()
row = cur.execute(
    'SELECT node_id, x, y, type, staff_id, staff_name, zone_id FROM manpower_nodes WHERE node_id = ?',
    (TMP_NODE_ID,),
).fetchone()
conn.close()
print('db row:', row)
