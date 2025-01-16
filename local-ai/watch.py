import os
import re
import json
import sqlite3
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import sys
from lib.chunking import chunk_python_code
from lib.chunking import chunk_react_code
from lib.chunking import chunk_json_file
from lib.processing import process_imports, get_git_tracked_files

# Connect to SQLite database
conn = sqlite3.connect("../codebase.db", check_same_thread=False)
cursor = conn.cursor()

directory = sys.argv[1]
filepaths = get_git_tracked_files(directory)

# Function to process code snippets
def process_file(filepath):
    if not any(filepath == directory + "/" + path for path in filepaths):
        return
    if not os.path.exists(filepath):
        return

    print(f"Processing file: {filepath}")
    try:
        with open(filepath, "r") as f:
            text = f.read()
    except:
        print('Failed to read file')
        return
    chunks = []

    if filepath.endswith(".py"):
        chunks = chunk_python_code(text)
    elif filepath.endswith((".js", ".ts", ".tsx")):
        chunks = chunk_react_code(text)
    elif filepath.endswith(".json"):
        chunks = chunk_json_file(text)
    else:
        return

    cursor.execute("""
                    INSERT OR REPLACE INTO snippets (id, source, content, type)
                    VALUES (?, ?, ?, ?)
                """, (filepath, filepath, text, "file"))
    process_imports(cursor, filepath, "", text, text)

    for identifier, content in chunks:
        cursor.execute("""
                    INSERT OR REPLACE INTO snippets (id, source, name, content, type)
                    VALUES (?, ?, ?, ?, ?)
                """, (filepath + ':' + identifier, filepath, identifier, content, "code"))
        process_imports(cursor, filepath, identifier, text, content)

    conn.commit()

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
start_watcher(directory)