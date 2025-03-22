import re
import ast
import tokenize
import io
import subprocess
import json
import os
import sys

from typing import List
from lib.types import Chunk
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


def chunk_python_code(source_file: str):
    """Chunk Python code using AST and tokenize."""
    source_text = read_file(source_file)
    if source_text is None:
        return
    chunks: List[Chunk] = [
        Chunk(
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
        chunks.append(Chunk("_imports_", content, start_line, end_line, "imports"))

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
        chunks.append(Chunk(name, content, start_line, end_line, type))
        previous_end = end_line

    return chunks


# Chunker for React and JS/TS files
def chunk_js_ts_code(source_file: str) -> List[Chunk]:
    result = subprocess.run(
        [
            f"node parsers/typescript/parser.js {source_file} {directory}/{source_directory}"
        ],
        capture_output=True,
        shell=True,
        text=True,
    )
    data = json.loads(result.stdout)
    chunks: List[Chunk] = []
    for dict in data["chunks"]:
        chunks.append(
            Chunk(
                dict["name"],
                dict["content"],
                dict["start_line"],
                dict["end_line"],
                dict["type"],
            )
        )
    return chunks
