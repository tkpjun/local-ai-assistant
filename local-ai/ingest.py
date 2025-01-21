
import sys
import os

from lib.chunking import chunk_python_code, chunk_js_ts_code
from lib.processing import process_imports, get_git_tracked_files
from lib.log import log
from lib.db import init_sqlite_tables, upsert_snippet
from lib.qdrant import insert_snippets

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

def ingest_codebase(directory, source_directory):
    filepaths = get_git_tracked_files(directory)
    for file in filepaths:
        filepath = f"{directory}/{file}"
        local_file_path = filepath.removeprefix(f"{directory}/")
        modulepath = (local_file_path
                      .removeprefix(f"{source_directory}/")
                      .replace("/", "."))
        for ext in config["file_processors"]:
            if filepath.endswith(ext):
                modulepath = modulepath.removesuffix(ext)
                break

        log.info(f"Processing file: {filepath}")
        text = read_file(filepath)
        if text is None:
            continue

        processor = config["file_processors"].get(os.path.splitext(file)[1])
        if not processor:
            log.info(f"No processor found for file {filepath}. Skipping.")
            continue

        chunks = processor(text)

        log.info(f"Processing snippet: {modulepath}")
        upsert_snippet(modulepath, None, filepath, text, 1, text.count("\n") + 1, "file")

        snippets = []
        for identifier, content, first_line, last_line in chunks:
            log.info(f"Processing snippet: {modulepath + '.' + identifier}")
            upsert_snippet(modulepath, identifier, filepath, content, first_line, last_line, "code")
            snippets.append((filepath, identifier, content))

        chunks.append((None, text, 1, text.count("\n") + 1))
        process_imports(filepath, modulepath, text, chunks)

        insert_snippets(snippets)

directory = sys.argv[1]
source_directory = sys.argv[2]
# Create tables
init_sqlite_tables(directory)
ingest_codebase(directory, source_directory)