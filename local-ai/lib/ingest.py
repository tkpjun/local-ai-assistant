import sys
import os
import re

from lib.chunking import chunk_python_code, chunk_js_ts_code
from lib.context import get_git_tracked_files
from lib.log import log
from lib.db import init_sqlite_tables, upsert_snippet, upsert_dependency, cleanup_data
from lib.qdrant import insert_snippets
from watchdog.events import (
    FileSystemEventHandler,
    DirDeletedEvent,
    FileDeletedEvent,
    DirMovedEvent,
    FileMovedEvent,
)
from watchdog.observers import Observer

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


# Function to process imports and store dependencies
def process_imports(filepath, modulepath, full_content, snippets):
    # Detect imports at the beginning of the file (Python and JS/TS)
    regex_py = r"^(?:import\s+\S+(?:\s+as\s+\S+)?|from\s+\S+\s+import\s+[^,\n]+(?:,\s*[^,\n]+)*)"
    regex_js_ts = r'^(?:import\s+(?:\*\s+as\s+\S+|{[^}]+}|[\w$]+)\s+from\s+[\'"][^\'"]+[\'"]|import\s+[\'"][^\'"]+[\'"]|export\s+{[^}]+}\s+from\s+[\'"][^\'"]+[\'"])'
    regex = regex_py if filepath.endswith(".py") else regex_js_ts
    import_lines = re.findall(regex, full_content, re.MULTILINE)
    dependencies_from_same_file = [
        snippet[0] for snippet in snippets if snippet[0] is not None
    ]

    for identifier, snippet_content, _, _ in snippets:
        # Extract only the import paths and their contents
        all_imports = {}
        for line in import_lines:
            if filepath.endswith((".js", ".ts", ".tsx")):
                # For JS/TS files
                keyword_match = re.search(
                    r"import\s*{\s*([^}]*)\s*}.*", line, re.DOTALL
                )
                imports = []
                if keyword_match:
                    # Get the matched group and split by commas, then strip whitespace
                    imports = [
                        item.strip()
                        for item in keyword_match.group(1).split(",")
                        if item.strip()
                    ]
                module_match = re.search(r'from\s+["\'](.*?)["\']', line, re.MULTILINE)
                if module_match:
                    path = module_match.group(1)
                    all_imports[path] = imports
            elif filepath.endswith(".py"):
                # For Python files
                matches = re.findall(
                    r"(?:from\s+(\w+(?:\.\w+)*)\s+import\s+([\w,\s]+))|(?:import\s+(\w+(?:\.\w+)*))",
                    line,
                )
                for match in matches:
                    if match[0] and match[1]:  # from X import Y, Z
                        module_path = match[0]
                        imported_objects = [obj.strip() for obj in match[1].split(",")]
                        if module_path not in all_imports:
                            all_imports[module_path] = []
                        all_imports[module_path].extend(imported_objects)
                    elif match[2]:  # import X
                        module_name = match[2]
                        if module_name not in all_imports:
                            all_imports[module_name] = []
                        all_imports[module_name].append(module_name)

        # Determine which imports are used in the snippet
        relevant_imports = []
        for module_path, objects in all_imports.items():
            if filepath.endswith((".js", ".ts", ".tsx")):
                for obj in objects:
                    if re.search(rf"\b{re.escape(obj)}\b", snippet_content):
                        amount = module_path.count("../")
                        if module_path.startswith("./"):
                            amount += 1
                        elif amount > 0:
                            amount += 1

                        modified_module_path = module_path
                        if "./" in module_path:
                            modified_module_path = modulepath.replace(".", "/")
                            for _ in range(amount):
                                modified_module_path = os.path.dirname(
                                    modified_module_path
                                )
                            modified_module_path = (
                                f"{modified_module_path}/{module_path}".replace(
                                    "../", ""
                                ).replace("./", "")
                            )
                        if modified_module_path.startswith("/"):
                            modified_module_path = modified_module_path[1:]
                        modified_module_path = modified_module_path.replace("/", ".")
                        relevant_imports.append(f"{modified_module_path}.{obj}")
            elif filepath.endswith(".py"):
                for obj in objects:
                    if re.search(rf"\b{re.escape(obj)}\b", snippet_content):
                        relevant_imports.append(
                            f"{module_path}.{obj}"
                            if module_path != obj
                            else module_path
                        )

        for dependency in dependencies_from_same_file:
            if (
                identifier is not None
                and identifier != dependency
                and dependency in snippet_content
            ):
                relevant_imports.append(f"{modulepath}.{dependency}")
        if identifier is not None and identifier != "_imports_":
            relevant_imports.append(f"{modulepath}._imports_")

        log.debug(all_imports)
        log.debug(relevant_imports)

        # Insert dependencies into the database
        for imp in relevant_imports:
            upsert_dependency(modulepath, identifier, imp)


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
