import sqlite3
import json
from typing import Optional, List
from lib.types import Assistant, Snippet, Dependency, UIState
from gradio import ChatMessage
from dataclasses import astuple

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
        snippet_id TEXT,
        dependency_name TEXT,
        PRIMARY KEY (snippet_id, dependency_name)
        FOREIGN KEY (snippet_id) REFERENCES snippets (id)
    )
    """
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS messages (
        ordinal INTEGER PRIMARY KEY,
        role TEXT,
        content TEXT,
        metadata TEXT
    )"""
    )
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS assistants (
        name TEXT PRIMARY KEY,
        llm TEXT,
        prompt TEXT,
        context_limit INTEGER,
        response_size_limit INTEGER
    )
    """
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS ui_state (
            assistant_name TEXT,
            extra_content_options TEXT,
            selected_snippets TEXT,
            PRIMARY KEY (assistant_name)
        )"""
    )
    conn.commit()


def cleanup_data(directory: str):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM snippets WHERE SOURCE LIKE ?", (f"{directory}%",))
    cursor.execute(
        "DELETE FROM dependencies as d WHERE NOT EXISTS (SELECT 1 FROM snippets as s WHERE d.snippet_id = s.id)"
    )
    conn.commit()


def upsert_snippet(snippet: Snippet):
    cursor = conn.cursor()
    # snippet_id = f"{modulepath}{"." if identifier is not None else ""}{identifier if identifier is not None else ""}"
    cursor.execute(
        """
                    INSERT OR REPLACE INTO snippets (id, source, module, name, content, start_line, end_line, type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
        astuple(snippet),
    )


def upsert_dependency(dependency: Dependency):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO dependencies (snippet_id, dependency_name) VALUES (?, ?)",
        astuple(dependency),
    )


def get_all_snippets() -> List[Snippet]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, source, module, name, content, start_line, end_line, type FROM snippets WHERE type = 'code'"
    )
    return [Snippet(*row) for row in cursor.fetchall()]


def get_all_dependencies() -> List[Dependency]:
    cursor = conn.cursor()
    cursor.execute("SELECT id, snippet_id, dependency_name FROM dependencies")
    return [Dependency(*row) for row in cursor.fetchall()]


def fetch_dependencies(snippet_id: str) -> List[Dependency]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT d.snippet_id, d.dependency_name FROM dependencies d INNER JOIN snippets s ON s.id = d.dependency_name WHERE d.snippet_id = ?",
        (snippet_id,),
    )
    return [Dependency(*row) for row in cursor.fetchall()]


def fetch_dependents(snippet_id: str) -> List[Dependency]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT snippet_id, d.dependency_name FROM dependencies WHERE dependency_name = ?",
        (snippet_id,),
    )
    return [Dependency(*row) for row in cursor.fetchall()]


def fetch_snippets_by_directory(directory: str) -> List[Snippet]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, source, module, name, content, start_line, end_line, type FROM snippets WHERE source LIKE ? ORDER BY id",
        (f"{directory}%",),
    )
    return [Snippet(*row) for row in cursor.fetchall()]


def fetch_snippets_by_source(source: str) -> List[Snippet]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, source, module, name, content, start_line, end_line, type FROM snippets WHERE source = ? AND name IS NOT NULL and name != '_imports_' ORDER BY name",
        (source,),
    )
    return [Snippet(*row) for row in cursor.fetchall()]


def fetch_snippet_by_id(id: str) -> Optional[Snippet]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, source, module, name, content, start_line, end_line, type FROM snippets WHERE id = ?",
        (id,),
    )
    snippet = cursor.fetchone()
    return Snippet(*snippet)


def load_chat_history() -> List[ChatMessage]:
    cursor = conn.cursor()
    cursor.execute("SELECT role, content, metadata FROM messages ORDER BY ordinal")
    return [
        ChatMessage(row[0], row[1], json.loads(row[2])) for row in cursor.fetchall()
    ]


def upsert_message(message: ChatMessage, ordinal: int):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO messages (ordinal, role, content, metadata) VALUES (?, ?, ?, ?)",
        (ordinal, message.role, message.content, json.dumps(message.metadata)),
    )


def clear_chat_history():
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages")


def upsert_assistant(assistant: Assistant):
    cursor = conn.cursor()
    cursor.execute(
        """
                    INSERT OR REPLACE INTO assistants (name, llm, context_limit, response_size_limit, prompt)
                    VALUES (?, ?, ?, ?, ?)
                """,
        astuple(assistant),
    )
    conn.commit()


def delete_assistant(name: str):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM assistants WHERE name = ?", (name,))
    conn.commit()


def fetch_all_assistants() -> List[Assistant]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, llm, context_limit, response_size_limit, prompt FROM assistants"
    )
    return [Assistant(*row) for row in cursor.fetchall()]


def fetch_assistant_by_name(name: str) -> Optional[Assistant]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, llm, context_limit, response_size_limit, prompt FROM assistants WHERE name = ?",
        (name,),
    )
    row = cursor.fetchone()
    if row:
        return Assistant(*row)
    return None


def upsert_ui_state(ui_state: UIState):
    cursor = conn.cursor()
    cursor.execute(
        """
            INSERT OR REPLACE INTO ui_state (assistant_name, extra_content_options, selected_snippets)
            VALUES (?, ?, ?)
        """,
        (
            ui_state.assistant_name,
            json.dumps(ui_state.extra_content_options),
            json.dumps(ui_state.selected_snippets),
        ),
    )
    conn.commit()


def fetch_ui_state() -> Optional[UIState]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT assistant_name, extra_content_options, selected_snippets FROM ui_state"
    )
    state = cursor.fetchone()
    if state:
        return UIState(
            assistant_name=state[0],
            extra_content_options=json.loads(state[1]),
            selected_snippets=json.loads(state[2]),
        )
    return None
