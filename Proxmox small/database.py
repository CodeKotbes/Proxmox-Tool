import sqlite3

DB_NAME = "data.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    """Create the table if it does not already exist"""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            content TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def add_script(name, description, content):
    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO scripts (name, description, content) VALUES (?, ?, ?)',
        (name, description, content)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def get_script_content(script_id):
    conn = get_db()
    try:
        script_id = int(script_id)
    except:
        return None
        
    row = conn.execute('SELECT content FROM scripts WHERE id = ?', (script_id,)).fetchone()
    conn.close()
    return row['content'] if row else None

def get_all_scripts():
    conn = get_db()
    rows = conn.execute('SELECT id, name, description FROM scripts').fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_script(script_id):
    conn = get_db()
    conn.execute('DELETE FROM scripts WHERE id = ?', (script_id,))
    conn.commit()
    conn.close()