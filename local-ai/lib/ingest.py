import os
import ast
import re

from lib.chunking import chunk_python_code, chunk_js_ts_code
from lib.context import get_git_tracked_files
from lib.log import log
from lib.db import upsert_snippet, upsert_dependency, cleanup_data
from lib.qdrant import insert_snippets
from watchdog.events import (
    FileSystemEventHandler,
    DirDeletedEvent,
    FileDeletedEvent,
    DirMovedEvent,
    FileMovedEvent,
)
from watchdog.observers import Observer

from lib.types import Dependency, Snippet, Chunk
from typing import List

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


def resolve_relative_import(file_path, module, level):
    """
    Resolve a relative import (e.g., '.utils') to an absolute path.

    Args:
        file_path: Path to the current file.
        module: The module name from the import (e.g., 'utils' for 'from .utils import x').
        level: The relative import level (e.g., 1 for 'from .utils import x').

    Returns:
        The resolved module path (e.g., 'my_package.utils').
    """
    if level == 0:
        return module

    # Get the directory of the current file
    current_dir = os.path.dirname(file_path)

    # Calculate the package path (assuming it's a Python package)
    # Note: This requires the file to be part of a package with __init__.py files
    package_path = current_dir.replace(os.path.sep, ".")
    parent_package = package_path.rsplit(".", level)[0] if level else package_path

    # Combine with the module name
    if module:
        return f"{parent_package}.{module}"
    else:
        return parent_package


# TODO handle dependencies internal to the file
def process_python_imports(
    source_code, file_path, snippets: List[Snippet]
) -> List[Dependency]:
    tree = ast.parse(source_code)
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                # Handle 'import x as y' style
                for alias in node.names:
                    module_name = alias.name
                    asname = alias.asname or module_name
                    imports.append(
                        {
                            "module": module_name,
                            "name": asname,
                            "type": "import",
                            "lineno": node.lineno,
                        }
                    )
            elif isinstance(node, ast.ImportFrom):
                # Handle 'from module import x as y' style
                module = node.module
                level = node.level
                resolved_module = resolve_relative_import(file_path, module, level)
                for alias in node.names:
                    imported_name = alias.name
                    asname = alias.asname or imported_name
                    imports.append(
                        {
                            "module": resolved_module,
                            "name": asname,
                            "type": "from_import",
                            "lineno": node.lineno,
                        }
                    )

    dependencies: List[Dependency] = []

    for snippet in snippets:
        if snippet.type == "imports":
            continue
        content = snippet.content
        for imp in imports:
            if imp["name"] in content:
                dependency_name = (
                    imp["name"]
                    if imp["module"] == imp["name"]
                    else f"{imp['module']}.{imp['name']}"
                )
                dependencies.append(Dependency(snippet.id, dependency_name))

    # Process internal dependencies between chunks
    snippet_names = {s.name: s.id for s in snippets if s.type != "file"}

    for current_snippet in snippets:
        if current_snippet.type == "imports":
            continue
        current_id = current_snippet.id
        content = current_snippet.content
        tree = ast.parse(content)
        used_names = set()

        # Collect names used in function calls
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    used_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    # Handle cases like obj.method() by checking the attribute's value
                    value = func.value
                    if isinstance(value, ast.Name):
                        used_names.add(f"{value.id}.{func.attr}")

        # Check for dependencies on other chunks
        for name in used_names:
            if name in snippet_names:
                dependency_id = snippet_names[name]
                if dependency_id != current_id:
                    dependencies.append(Dependency(current_id, dependency_id))
        dependencies.append(
            Dependency(current_id, f"{current_snippet.module}._imports_")
        )

    print(dependencies)
    return dependencies


# Function to process imports and store dependencies
def process_imports(snippets: List[Snippet]):
    filepath = snippets[0].source
    full_content = snippets[0].content
    if filepath.endswith(".py"):
        dependencies = process_python_imports(full_content, filepath, snippets)
        for dependency in dependencies:
            upsert_dependency(dependency)
        return

    # Detect imports at the beginning of the file (Python and JS/TS)
    # TODO fix Python multiline imports
    regex_py = r"^(?:import\s+\S+(?:\s+as\s+\S+)?|from\s+\S+\s+import\s+[^,\n]+(?:,\s*[^,\n]+)*)"
    regex_js_ts = r'^(?:import\s+(?:\*\s+as\s+\S+|{[^}]+}|[\w$]+)\s+from\s+[\'"][^\'"]+[\'"]|import\s+[\'"][^\'"]+[\'"]|export\s+{[^}]+}\s+from\s+[\'"][^\'"]+[\'"])'
    regex = regex_py if filepath.endswith(".py") else regex_js_ts
    import_lines = re.findall(regex, full_content, re.MULTILINE)
    dependencies_from_same_file = [
        snippet.module for snippet in snippets if snippet.module is not None
    ]

    for snippet in snippets:
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
                    if re.search(rf"\b{re.escape(obj)}\b", snippet.content):
                        amount = module_path.count("../")
                        if module_path.startswith("./"):
                            amount += 1
                        elif amount > 0:
                            amount += 1

                        modified_module_path = module_path
                        if "./" in module_path:
                            modified_module_path = snippet.module.replace(".", "/")
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
                    if re.search(rf"\b{re.escape(obj)}\b", snippet.content):
                        relevant_imports.append(
                            f"{module_path}.{obj}"
                            if module_path != obj
                            else module_path
                        )

        for dependency in dependencies_from_same_file:
            if (
                snippet.name is not None
                and snippet.name != dependency
                and dependency in snippet.content
            ):
                relevant_imports.append(f"{snippet.module}.{dependency}")
        if snippet.name is not None and snippet.name != "_imports_":
            relevant_imports.append(f"{snippet.module}._imports_")

        log.debug(all_imports)
        log.debug(relevant_imports)

        # Insert dependencies into the database
        for dependency_name in relevant_imports:
            upsert_dependency(Dependency(snippet.id, dependency_name))


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
    snippet_id = modulepath
    snippets: List[Snippet] = [
        Snippet(
            snippet_id,
            filepath,
            modulepath,
            None,
            text,
            1,
            text.count("\n") + 1,
            "file",
        )
    ]
    upsert_snippet(snippets[0])
    for chunk in chunks:
        snippet_id = f"{modulepath}.{chunk.name}"
        log.info(f"Processing snippet: {snippet_id}")
        snippet = Snippet(
            snippet_id,
            filepath,
            modulepath,
            chunk.name,
            chunk.content,
            chunk.start_line,
            chunk.end_line,
            chunk.type,
        )
        upsert_snippet(snippet)
        snippets.append(snippet)
    process_imports(snippets)

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
