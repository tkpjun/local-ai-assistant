import sqlite3
from typing import Optional

# Connect to SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect("../codebase.db", check_same_thread=False)
cursor = conn.cursor()

def init_sqlite_tables(directory):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS snippets (
        id TEXT PRIMARY KEY,
        source TEXT,
        module TEXT,
        name TEXT,
        content TEXT,
        start_line INTEGER,
        end_line INTEGER,
        type TEXT
    )
    """)
    cursor.execute("DELETE FROM snippets WHERE SOURCE LIKE ?", (f"{directory}%",))
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snippet_id TEXT,
        dependency_name TEXT,
        FOREIGN KEY (snippet_id) REFERENCES snippets (id)
    )
    """)
    cursor.execute("DELETE FROM dependencies as d WHERE NOT EXISTS (SELECT 1 FROM snippets as s WHERE d.snippet_id = s.id)")
    conn.commit()

def upsert_snippet(modulepath: str,
                   identifier: Optional[str],
                   filepath: str,
                   content: str,
                   start_line: int,
                   end_line: int,
                   type: str):
    snippet_id = f"{modulepath}{"." if identifier is not None else ""}{identifier if identifier is not None else ""}"
    cursor.execute("""
                    INSERT OR REPLACE INTO snippets (id, source, module, name, content, start_line, end_line, type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (snippet_id, filepath, modulepath, identifier, content, start_line, end_line, type))
    conn.commit()

def upsert_dependency(modulepath: str, identifier: Optional[str], dependency_name: str):
    snippet_id = f"{modulepath}{"." if identifier is not None else ""}{identifier if identifier is not None else ""}"
    cursor.execute("INSERT OR REPLACE INTO dependencies (snippet_id, dependency_name) VALUES (?, ?)", (snippet_id, dependency_name))
    conn.commit()

def get_all_snippets():
    cursor.execute("SELECT id, source, content, start_line, end_line FROM snippets")
    return cursor.fetchall()

def get_all_dependencies():
    cursor.execute("SELECT snippet_id, dependency_name FROM dependencies")
    return cursor.fetchall()