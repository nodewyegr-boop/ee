import os
import sqlite3

# ที่เก็บไฟล์ฐานข้อมูล
#  - ตั้งตัวแปร DB_PATH ได้ (เช่น /data/bot_data.db ถ้าโฮสต์มี Volume/Disk ถาวร)
#  - ถ้าไม่ตั้ง จะใช้ไฟล์ bot_data.db ข้างๆ ไฟล์นี้ (ไม่ขึ้นกับโฟลเดอร์ที่สั่งรัน)
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.db")


class Database:
    def __init__(self, db_name=None):
        self.db_name = db_name or os.getenv("DB_PATH") or DEFAULT_PATH
        folder = os.path.dirname(self.db_name)
        if folder:
            os.makedirs(folder, exist_ok=True)
        print(f"[database] ใช้ไฟล์ข้อมูล: {self.db_name}")
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # ตารางสำหรับบันทึกการตั้งค่าระบบ Verify
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS verify_panels (
                guild_id INTEGER,
                system_type TEXT,
                channel_id INTEGER,
                role_id INTEGER,
                PRIMARY KEY (guild_id, system_type)
            )
        ''')
        conn.commit()
        conn.close()

    def save_panel(self, guild_id: int, system_type: str, channel_id: int, role_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO verify_panels (guild_id, system_type, channel_id, role_id)
            VALUES (?, ?, ?, ?)
        ''', (guild_id, system_type, channel_id, role_id))
        conn.commit()
        conn.close()

    def get_panel(self, guild_id: int, system_type: str):
        conn = self.get_connection()