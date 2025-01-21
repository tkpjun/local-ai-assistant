import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import sys
from lib.chunking import chunk_python_code
from lib.chunking import chunk_js_ts_code
from lib.processing import process_imports, get_git_tracked_files
from lib.db import upsert_snippet
from lib.log import log

directory = sys.argv[1]
filepaths = get_git_tracked_files(directory)
source_directory = sys.argv[2]

config = {
    "file_processors": {
        ".py": chunk_python_code,
        ".js": chunk_js_ts_code,
        ".ts": chunk_js_ts_code,
        ".tsx": chunk_js_ts_code
    }
}

def read_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError as e:
        log.error(f'Failed to read file {filepath}: {e}')
    except Exception as e:
        log.error(f'An error occurred while reading file {filepath}: {e}')
    return None

# Function to process code snippets
def process_file(filepath):
    if not any(filepath == directory + "/" + path for path in filepaths):
        return
    if not os.path.exists(filepath):
        return

    log.info(f"Processing file: {filepath}")
    text = read_file(filepath)

    local_file_path = filepath.removeprefix(f"{directory}/")
    modulepath = (local_file_path
                  .removeprefix(f"{source_directory}/")
                  .replace("/", "."))
    for ext in config["file_processors"]:
        if filepath.endswith(ext):
            modulepath = modulepath.removesuffix(ext)
            break

    chunks = []

    processor = config["file_processors"].get(os.path.splitext(filepath)[1])
    if not processor:
        log.info(f"No processor found for file {filepath}. Skipping.")
        return

    log.info(f"Processing snippet: {modulepath}")
    upsert_snippet(modulepath, None, filepath, text, 1, text.count("\n") + 1, "file")

    for identifier, content, first_line, last_line in chunks:
        log.info(f"Processing snippet: {modulepath + '.' + identifier}")
        upsert_snippet(modulepath, identifier, filepath, content, first_line, last_line, "code")

    chunks.append((None, text, 1, text.count("\n") + 1))
    process_imports(filepath, modulepath, text, chunks)

# File system event handler
class CodebaseEventHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if not event.is_directory:
            process_file(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            process_file(event.src_path)

# Start the file watcher
def start_watcher():
    event_handler = CodebaseEventHandler()
    observer = Observer()
    observer.schedule(event_handler, path=directory, recursive=True)
    observer.start()
    log.info(f"Watching for changes in {directory}...")

    try:
        while True:
            pass
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

# Start the watcher
start_watcher()