import re
import ast
import tokenize
import io
import subprocess
import json
import os
import sys

from typing import List
from lib.types import Snippet, Dependency
from lib.log import log

directory = os.path.abspath(sys.argv[1])
source_directory = sys.argv[2]


def read_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError as e:
        log.error(f"Failed to read file {filepath}: {e}")
    except Exception as e:
        log.error(f"An error occurred while reading file {filepath}: {e}")
    return None


def get_comments(source):
    """Extract comments from source code using tokenize."""
    comments = []
    try:
        tokens = tokenize.tokenize(io.BytesIO(source.encode("utf-8")).readline)
        for toktype, tokval, start, end, line in tokens:
            if toktype == tokenize.COMMENT:
                comments.append((start[0], tokval))
    except tokenize.TokenError:
        pass  # Handle syntax errors if needed
    return comments


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

    return dependencies


def chunk_python_code(source_file: str) -> (List[Snippet], List[Dependency]):
    """Chunk Python code using AST and tokenize."""
    modulepath = (
        source_file.removeprefix(f"{directory}/")
        .removeprefix(f"{source_directory}/")
        .replace("/", ".")
        .removesuffix(".py")
    )
    source_text = read_file(source_file)
    if source_text is None:
        return
    snippets: List[Snippet] = [
        Snippet(
            modulepath,
            source_file,
            modulepath,
            None,
            source_text,
            1,
            source_text.count("\n") + 1,
            "file",
        )
    ]
    module = ast.parse(source_text)
    top_level_nodes = module.body
    comments = get_comments(source_text)

    # Process imports first
    import_nodes = [
        n for n in top_level_nodes if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    if import_nodes:
        first_import = import_nodes[0]
        preceding_comments = [
            (line, c) for line, c in comments if line < first_import.lineno
        ]
        preceding_str = "\n".join(
            c[1] for c in sorted(preceding_comments, key=lambda x: x[0])
        )
        imports_code = "\n".join(
            ast.get_source_segment(source_text, node) for node in import_nodes
        )
        content = f"{preceding_str}\n{imports_code}" if preceding_str else imports_code
        start_line = first_import.lineno
        end_line = import_nodes[-1].lineno + len(imports_code.split("\n")) - 1
        snippets.append(
            Snippet(
                f"{modulepath}._imports_",
                source_file,
                modulepath,
                "_imports_",
                content,
                start_line,
                end_line,
                "imports",
            )
        )

    # Process non-import nodes
    non_import_nodes = [
        n for n in top_level_nodes if not isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    previous_end = 0  # Track end line of previous node

    for node in non_import_nodes:
        node_code = ast.get_source_segment(source_text, node)
        if not node_code:
            continue  # Skip if code couldn't be retrieved

        start_line = node.lineno
        lines = node_code.count("\n") + 1
        end_line = start_line + lines - 1

        # Find preceding comments between previous_end and start_line
        preceding = [c for c in comments if previous_end < c[0] < start_line]
        preceding_str = "\n".join(c[1] for c in sorted(preceding, key=lambda x: x[0]))

        # Determine node name
        name = ""
        type = ""
        if isinstance(node, ast.FunctionDef):
            name = node.name
            type = "function"
        elif isinstance(node, ast.ClassDef):
            name = node.name
            type = "class"
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = getattr(node, "targets", [None])[0] or getattr(
                node, "target", None
            )
            if isinstance(target, ast.Name):
                name = target.id
                type = "variable"
            else:
                name = f"{start_line}"
                type = "assignment"
        else:
            name = f"{start_line}"
            type = "other"

        content = f"{preceding_str}\n{node_code}" if preceding_str else node_code
        snippets.append(
            Snippet(
                f"{modulepath}.{name}",
                source_file,
                modulepath,
                name,
                content,
                start_line,
                end_line,
                type,
            )
        )
        previous_end = end_line

    dependencies = process_python_imports(source_text, source_file, snippets)
    return (snippets, dependencies)


# Chunker for React and JS/TS files
def chunk_js_ts_code(source_file: str) -> (List[Snippet], List[Dependency]):
    result = subprocess.run(
        [
            f"node parsers/typescript/parser.js {source_file} {directory}/{source_directory}"
        ],
        capture_output=True,
        shell=True,
        text=True,
    )
    data = json.loads(result.stdout)
    snippets: List[Snippet] = []
    dependencies: List[Dependency] = []
    for dict in data["chunks"]:
        snippets.append(
            Snippet(
                dict["id"],
                dict["source"],
                dict["module"],
                dict["name"],
                dict["content"],
                dict["start_line"],
                dict["end_line"],
                dict["type"],
            )
        )
    for dict in data["dependencies"]:
        dependencies.append(Dependency(dict["snippet_id"], dict["dependency_name"]))

    return (snippets, dependencies)
