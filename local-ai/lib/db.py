import sqlite3
from typing import Optional

sqlite3.threadsafety = 3
# Connect to SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect("codebase.db", check_same_thread=False)


def init_sqlite_tables():
    cursor = conn.cursor()
    cursor.execute(
        """
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
    """
    )
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snippet_id TEXT,
        dependency_name TEXT,
        FOREIGN KEY (snippet_id) REFERENCES snippets (id)
    )
    """
    )
    conn.commit()


def cleanup_data(directory):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM snippets WHERE SOURCE LIKE ?", (f"{directory}%",))
    cursor.execute(
        "DELETE FROM dependencies as d WHERE NOT EXISTS (SELECT 1 FROM snippets as s WHERE d.snippet_id = s.id)"
    )
    conn.commit()


def upsert_snippet(
    modulepath: str,
    identifier: Optional[str],
    filepath: str,
    content: str,
    start_line: int,
    end_line: int,
    type: str,
):
    cursor = conn.cursor()
    snippet_id = f"{modulepath}{"." if identifier is not None else ""}{identifier if identifier is not None else ""}"
    cursor.execute(
        """
                    INSERT OR REPLACE INTO snippets (id, source, module, name, content, start_line, end_line, type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
        (
            snippet_id,
            filepath,
            modulepath,
            identifier,
            content,
            start_line,
            end_line,
            type,
        ),
    )


def upsert_dependency(modulepath: str, identifier: Optional[str], dependency_name: str):
    cursor = conn.cursor()
    snippet_id = f"{modulepath}{"." if identifier is not None else ""}{identifier if identifier is not None else ""}"
    cursor.execute(
        "INSERT OR REPLACE INTO dependencies (snippet_id, dependency_name) VALUES (?, ?)",
        (snippet_id, dependency_name),
    )


def get_all_snippets():
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, source, content, start_line, end_line FROM snippets WHERE type = 'code'"
    )
    return cursor.fetchall()


def get_all_dependencies():
    cursor = conn.cursor()
    cursor.execute("SELECT snippet_id, dependency_name FROM dependencies")
    return cursor.fetchall()


def fetch_dependencies(snippet_id):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT d.dependency_name FROM dependencies d INNER JOIN snippets s ON s.id = d.dependency_name WHERE d.snippet_id = ?",
        (snippet_id,),
    )
    snippet_ids = cursor.fetchall()
    return [snippet_id[0] for snippet_id in snippet_ids]


def fetch_dependents(snippet_id):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT snippet_id FROM dependencies WHERE dependency_name = ?", (snippet_id,)
    )
    snippet_ids = cursor.fetchall()
    return [snippet_id[0] for snippet_id in snippet_ids]


def fetch_snippet_ids(directory):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM snippets WHERE source LIKE ? ORDER BY id", (f"{directory}%",)
    )
    snippet_ids = cursor.fetchall()
    return [snippet_id[0] for snippet_id in snippet_ids]


def fetch_snippets_by_source(source):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM snippets WHERE source = ? AND name IS NOT NULL and name != '_imports_' ORDER BY name",
        (source,),
    )
    names = cursor.fetchall()
    return [name[0] for name in names]


def fetch_snippet_by_id(id):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT content, source, start_line, end_line FROM snippets WHERE id = ?",
        (id,),
    )
    snippet = cursor.fetchone()
    return snippet
