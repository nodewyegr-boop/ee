import sqlite3

class Database:
    def __init__(self, db_name="bot_data.db"):
        self.db_name = db_name
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
        cursor = conn.cursor()
        cursor.execute('''
            SELECT channel_id, role_id FROM verify_panels
            WHERE guild_id = ? AND system_type = ?
        ''', (guild_id, system_type))
        row = cursor.fetchone()
        conn.close()
        return row # ส่งคืน (channel_id, role_id)

db = Database()
