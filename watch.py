import os
import re
import json
import sqlite3
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Connect to SQLite database
conn = sqlite3.connect("codebase.db")
cursor = conn.cursor()

# Function to process code snippets
def process_file(filepath):
    if not os.path.exists(filepath):
        return

    print(f"Processing file: {filepath}")
    chunks = []

    if filepath.endswith((".js", ".ts", ".tsx")):
        chunks = chunk_react_code(filepath)
    elif filepath.endswith(".json"):
        chunks = chunk_json_file(filepath)
    else:
        return

    for identifier, content in chunks:
        cursor.execute("""
            INSERT OR IGNORE INTO snippets (source, identifier, content, type)
            VALUES (?, ?, ?, ?)
        """, (filepath, identifier, content, "code"))

    # Process imports
    with open(filepath, "r") as f:
        content = f.read()
        process_imports(filepath, content)

    conn.commit()

# Chunker for React and JS/TS files
def chunk_react_code(filepath):
    with open(filepath, "r") as f:
        text = f.read()

    pattern = r"(export\s+(?:default\s+)?(?:function|class)\s+\w+|\bfunction\s+\w+|\bclass\s+\w+)"
    matches = [m.start() for m in re.finditer(pattern, text)]

    chunks = []
    for i, start in enumerate(matches):
        end = matches[i + 1] if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        identifier = chunk.split()[1]  # Extract function or class name
        chunks.append((identifier, chunk))

    return chunks

# Chunker for JSON files
def chunk_json_file(filepath):
    with open(filepath, "r") as f:
        data = json.load(f)

    chunks = []
    if isinstance(data, dict):
        for key, value in data.items():
            chunks.append((key, json.dumps({key: value}, indent=2)))
    elif isinstance(data, list):
        for item in data:
            chunks.append((None, json.dumps(item, indent=2)))

    return chunks

# Function to process imports
def process_imports(filepath, content):
    imports = re.findall(r'import\s+.*?from\s+["\'](.*?)["\']', content)
    for imp in imports:
        cursor.execute("SELECT id FROM snippets WHERE identifier = ?", (imp,))
        dependency = cursor.fetchone()
        if dependency:
            cursor.execute("INSERT INTO dependencies (snippet_id, dependency_id) VALUES (?, ?)", (filepath, dependency[0]))

# File system event handler
class CodebaseEventHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if not event.is_directory:
            process_file(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            process_file(event.src_path)

# Start the file watcher
def start_watcher(directory):
    event_handler = CodebaseEventHandler()
    observer = Observer()
    observer.schedule(event_handler, path=directory, recursive=True)
    observer.start()
    print(f"Watching for changes in {directory}...")

    try:
        while True:
            pass
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

# Start the watcher
start_watcher("path/to/codebase")