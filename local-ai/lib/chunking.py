import re
import ast
import tokenize
import io

from typing import List
from lib.types import Chunk


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


def chunk_python_code(source_text):
    """Chunk Python code using AST and tokenize."""
    chunks: List[Chunk] = []
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
def chunk_js_ts_code(text: str) -> List[Chunk]:
    lines = text.splitlines()
    chunks: List[Chunk] = []
    current_chunk: List[str] = []
    preceding_comments: List[str] = []

    # Regular expression to match top-level function, class, var, let, const declarations
    func_class_var_interface_type_pattern = re.compile(
        r"^\s*(export\s+)?(?:async\s+)?(?:function|class|(?:var|let|const)\s+\w+|(interface|type)\s+\w+)"
    )

    import_start_pattern = re.compile(r"^\s*import\b")
    module_exports_pattern = re.compile(r"^\s*module\.exports\b")
    in_comment_block = False
    in_import_block = False
    found_module_exports = False

    current_chunk_start_line = 0
    import_lines = []

    for line_number, line in enumerate(lines):
        stripped_line = line.strip()

        # Check if the line is a comment
        if line.startswith("//") or (
            line.strip().startswith("/*") and not line.strip().endswith("*/")
        ):
            preceding_comments.append(line)
            continue
        elif "/*" in line and "*/" in line:
            preceding_comments.append(line)
            continue
        elif "/*" in line and not line.strip().endswith("*/"):
            preceding_comments.append(line)
            in_comment_block = True
            continue
        elif line.strip().endswith("*/") and in_comment_block:
            preceding_comments.append(line)
            in_comment_block = False
            continue
        elif in_comment_block:
            preceding_comments.append(line)
            continue

        # Check for import lines
        if import_start_pattern.match(stripped_line):
            in_import_block = True

        if in_import_block:
            import_lines.append((line_number, line))
            if "} from" in stripped_line:
                in_import_block = False

        # Check for module.exports
        if module_exports_pattern.search(stripped_line):
            found_module_exports = True
            current_chunk.append(line)
            continue

        # Check for lines with zero indentation (new top-level block)
        if stripped_line and not line.startswith(" "):
            if func_class_var_interface_type_pattern.match(
                stripped_line
            ):  # If a new function/class/var/let/const is found
                if current_chunk:  # Process the previous chunk if it exists
                    full_chunk = "\n".join(current_chunk).strip()

                    # Extract identifier (function, class, var, let, const name)
                    match = re.search(
                        r"\b(function|class|(?:var|let|const|interface|type)\s+)(\w+)",
                        "\n".join(current_chunk),
                    )
                    identifier = match.group(2) if match else None

                    if identifier is not None:
                        chunks.append(
                            Chunk(
                                identifier,
                                full_chunk,
                                current_chunk_start_line,
                                line_number - 1,
                                "code",
                            )
                        )

                    # Reset for the new chunk
                    current_chunk = []
                    preceding_comments = []

                current_chunk_start_line = line_number

        current_chunk.append(line)  # Add line to the current chunk

    # Process the last chunk if it exists
    if found_module_exports:
        exports_chunk_text = "\n".join(current_chunk).strip()
        chunks.append(
            Chunk(
                "_exports_",
                exports_chunk_text,
                current_chunk_start_line,
                line_number - 1,
                "exports",
            )
        )
    elif current_chunk:
        full_chunk = "\n".join(current_chunk).strip()

        # Extract identifier (function, class, var, let, const name)
        match = re.search(
            r"\b(function|class|(?:var|let|const|interface|type)\s+)(\w+)",
            "\n".join(current_chunk),
        )
        identifier = match.group(2) if match else None
        if identifier is not None:
            chunks.append(
                Chunk(
                    identifier,
                    full_chunk,
                    current_chunk_start_line,
                    line_number - 1,
                    "code",
                )
            )

    # Handle import lines
    if import_lines:
        import_chunk_text = "\n".join([line for _, line in import_lines]).strip()
        chunks.insert(0, Chunk("_imports_", import_chunk_text, 1, len(import_lines)))

    return chunks
