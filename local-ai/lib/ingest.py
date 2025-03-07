import sys
import os

from lib.chunking import chunk_python_code, chunk_js_ts_code
from lib.processing import process_imports, get_git_tracked_files
from lib.log import log
from lib.db import init_sqlite_tables, upsert_snippet, cleanup_data
from lib.qdrant import insert_snippets
from watchdog.events import (
    FileSystemEventHandler,
    DirDeletedEvent,
    FileDeletedEvent,
    DirMovedEvent,
    FileMovedEvent,
)
from watchdog.observers import Observer
import time

config = {
    "file_processors": {
        ".py": chunk_python_code,
        ".js": chunk_js_ts_code,
        ".ts": chunk_js_ts_code,
        ".tsx": chunk_js_ts_code,
    }
}


def read_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError as e:
        log.error(f"Failed to read file {filepath}: {e}")
    except Exception as e:
        log.error(f"An error occurred while reading file {filepath}: {e}")
    return None


def delete_file_snippets(directory, file):
    filepath = f"{directory}/{file}"
    cleanup_data(filepath)


def process_file(directory, source_directory, file):
    filepath = f"{directory}/{file}"
    local_file_path = filepath.removeprefix(f"{directory}/")
    modulepath = local_file_path.removeprefix(f"{source_directory}/").replace("/", ".")
    for ext in config["file_processors"]:
        if filepath.endswith(ext):
            modulepath = modulepath.removesuffix(ext)
            break

    log.info(f"Processing file: {filepath}")
    processor = config["file_processors"].get(os.path.splitext(file)[1])
    if not processor:
        log.info(f"No processor found for file {filepath}. Skipping.")
        return

    text = read_file(filepath)
    if text is None:
        return

    chunks = processor(text)

    log.info(f"Processing snippet: {modulepath}")
    upsert_snippet(modulepath, None, filepath, text, 1, text.count("\n") + 1, "file")

    snippets = []
    for identifier, content, first_line, last_line in chunks:
        log.info(f"Processing snippet: {modulepath + '.' + identifier}")
        upsert_snippet(
            modulepath, identifier, filepath, content, first_line, last_line, "code"
        )
        snippets.append((filepath, identifier, content))

    chunks.append((None, text, 1, text.count("\n") + 1))
    process_imports(filepath, modulepath, text, chunks)

    insert_snippets(snippets)


def ingest_codebase(directory, source_directory):
    cleanup_data(directory)
    filepaths = get_git_tracked_files(directory)
    for file in filepaths:
        process_file(directory, source_directory, file)


# Start the file watcher
def start_watcher(directory, source_directory):
    class CodebaseEventHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if not event.is_directory:
                process_file(
                    directory, source_directory, event.src_path[len(directory) + 1 :]
                )

        def on_created(self, event):
            if not event.is_directory:
                process_file(
                    directory, source_directory, event.src_path[len(directory) + 1 :]
                )

        def on_deleted(self, event: DirDeletedEvent | FileDeletedEvent) -> None:
            if not event.is_directory:
                delete_file_snippets(directory, event.src_path[len(directory) + 1 :])

        def on_moved(self, event: DirMovedEvent | FileMovedEvent) -> None:
            if not event.is_directory:
                process_file(
                    directory, source_directory, event.src_path[len(directory) + 1 :]
                )
                delete_file_snippets(directory, event.src_path[len(directory) + 1 :])

    event_handler = CodebaseEventHandler()
    observer = Observer()
    observer.schedule(event_handler, path=directory, recursive=True)
    observer.start()
    log.info(f"Watching for changes in {directory}...")
