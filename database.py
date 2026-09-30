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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                system_name TEXT,
                data TEXT
            )
        ''')
        
        conn.commit()
        conn.close()

db = Database()
