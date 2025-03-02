import json
import re


def chunk_python_code(text):
    lines = text.splitlines()
    chunk_first_line = 1
    chunks = []
    current_chunk = []
    preceding_comments = []

    # Regular expression to match top-level variable assignments
    var_assignment_pattern = re.compile(r"^\s*(\w+)\s*=")

    import_lines = []
    seen_non_import_line = False

    for line_number, line in enumerate(lines):
        stripped_line = line.strip()

        if not seen_non_import_line and (
            line.startswith("import ") or line.startswith("from ")
        ):
            import_lines.append(line)
            continue
        elif line:
            seen_non_import_line = True

        # Check for lines with zero indentation (new top-level block)
        if stripped_line and not line.startswith(" ") and not line.startswith(")"):  # Indentation level 0
            if current_chunk:  # If a chunk is being built, process it
                # Process the previous chunk
                chunk_text = "\n".join(current_chunk).strip()
                full_chunk = "\n".join(preceding_comments + [chunk_text]).strip()

                if chunk_text.startswith(("class ", "def ")):  # Only keep class/def
                    # Extract identifier
                    match = re.match(r"(class|def)\s+(\w+)", chunk_text)
                    identifier = match.group(2) if match else None
                    chunks.append(
                        (identifier, full_chunk, chunk_first_line, line_number - 1)
                    )
                    preceding_comments.clear()  # Clear comments after processing
                elif var_assignment_pattern.match(
                    chunk_text
                ):  # Check for variable assignment
                    # Extract the variable name as the identifier
                    match = var_assignment_pattern.match(chunk_text)
                    identifier = match.group(1) if match else None
                    chunks.append(
                        (identifier, full_chunk, chunk_first_line, line_number - 1)
                    )
                    preceding_comments.clear()  # Clear comments after processing

                chunk_first_line = line_number
                current_chunk = []  # Reset for the new chunk

        if line.startswith("#"):
            preceding_comments.append(line)
        else:
            current_chunk.append(line)  # Add line to the current chunk

    # Process the last chunk if it exists
    if current_chunk:
        chunk_text = "\n".join(current_chunk).strip()
        full_chunk = "\n".join(preceding_comments + [chunk_text]).strip()

        if chunk_text.startswith(("class ", "def ")):
            match = re.match(r"(class|def)\s+(\w+)", chunk_text)
            identifier = match.group(2) if match else None
            chunks.append((identifier, full_chunk, chunk_first_line, line_number - 1))
        elif var_assignment_pattern.match(chunk_text):  # Check for variable assignment
            match = var_assignment_pattern.match(chunk_text)
            identifier = match.group(1) if match else None
            chunks.append((identifier, full_chunk, chunk_first_line, line_number - 1))

    # Add imports as the first chunk with identifier _imports_
    if import_lines:
        import_chunk_text = "\n".join(import_lines).strip()
        chunks.insert(0, ("_imports_", import_chunk_text, 1, len(import_lines)))

    return chunks


# Chunker for React and JS/TS files
def chunk_js_ts_code(text):
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    preceding_comments = []

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
                            (
                                identifier,
                                full_chunk,
                                current_chunk_start_line,
                                line_number - 1,
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
            ("_exports_", exports_chunk_text, current_chunk_start_line, line_number - 1)
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
                (identifier, full_chunk, current_chunk_start_line, line_number - 1)
            )

    # Handle import lines
    if import_lines:
        import_chunk_text = "\n".join([line for _, line in import_lines]).strip()
        chunks.insert(0, ("_imports_", import_chunk_text, 1, len(import_lines)))

    return chunks
