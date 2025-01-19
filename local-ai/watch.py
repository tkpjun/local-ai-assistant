import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import sys
from lib.chunking import chunk_python_code
from lib.chunking import chunk_react_code
from lib.chunking import chunk_json_file
from lib.processing import process_imports, get_git_tracked_files
from lib.db import upsert_snippet
from lib.log import log

directory = sys.argv[1]
filepaths = get_git_tracked_files(directory)
source_directory = sys.argv[2]

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
                  .replace("/", ".")
                  .removesuffix(".py")
                  .removesuffix(".ts")
                  .removesuffix(".tsx")
                  .removesuffix(".js"))

    chunks = []

    if filepath.endswith(".py"):
        chunks = chunk_python_code(text)
    elif filepath.endswith((".js", ".ts", ".tsx")):
        chunks = chunk_react_code(text)
    elif filepath.endswith(".json"):
        chunks = chunk_json_file(text)
    else:
        return

    log.info(modulepath)
    upsert_snippet(modulepath, None, filepath, text, 1, text.count("\n") + 1, "file")
    process_imports(filepath, modulepath, None, text, text)

    for identifier, content, first_line, last_line in chunks:
        log.info(modulepath + '.' + identifier)
        upsert_snippet(modulepath, identifier, filepath, content, first_line, last_line, "code")
        process_imports(filepath, modulepath, identifier, text, content)

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