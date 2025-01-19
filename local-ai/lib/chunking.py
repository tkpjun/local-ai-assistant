import json
import re

def chunk_python_code(text):
    lines = text.splitlines()
    chunk_first_line = 1
    line_number = 0
    chunks = []
    current_chunk = []
    preceding_comments = []

    # Regular expression to match top-level variable assignments
    var_assignment_pattern = re.compile(r"^\s*(\w+)\s*=")

    import_lines = []
    seen_non_import_line = False

    for line in lines:
        line_number += 1
        stripped_line = line.strip()

        if not seen_non_import_line and (line.startswith("import ") or line.startswith("from ")):
            import_lines.append(line)
            continue
        elif line:
            seen_non_import_line = True

        # Check for lines with zero indentation (new top-level block)
        if stripped_line and not line.startswith(" "):  # Indentation level 0
            if current_chunk:  # If a chunk is being built, process it
                # Process the previous chunk
                chunk_text = "\n".join(current_chunk).strip()
                full_chunk = "\n".join(preceding_comments + [chunk_text]).strip()

                if chunk_text.startswith(("class ", "def ")):  # Only keep class/def
                    # Extract identifier
                    match = re.match(r"(class|def)\s+(\w+)", chunk_text)
                    identifier = match.group(2) if match else None
                    chunks.append((identifier, full_chunk, chunk_first_line, line_number - 1))
                    preceding_comments.clear()  # Clear comments after processing
                elif var_assignment_pattern.match(chunk_text):  # Check for variable assignment
                    # Extract the variable name as the identifier
                    match = var_assignment_pattern.match(chunk_text)
                    identifier = match.group(1) if match else None
                    chunks.append((identifier, full_chunk, chunk_first_line, line_number - 1))
                    preceding_comments.clear()  # Clear comments after processing

                chunk_first_line = line_number
                current_chunk = []  # Reset for the new chunk

        if line.startswith('#'):
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
        chunks.insert(0, ('_imports_', import_chunk_text, 1, len(import_lines)))

    return chunks

# Chunker for React and JS/TS files
def chunk_react_code(text):
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    preceding_comments = []

    # Regular expression to match top-level function and class declarations
    func_class_pattern = re.compile(r"^\s*(export\s+(?:default\s+)?(?:function|class)\s+\w+|\b(function|class)\s+\w+)")

    for line in lines:
        stripped_line = line.strip()

        # Check for lines with zero indentation (new top-level block)
        if stripped_line and not line.startswith(" "):  # Indentation level 0
            if func_class_pattern.match(stripped_line):  # If a new function/class is found
                if current_chunk:  # Process the previous chunk if it exists
                    full_chunk = "\n".join(preceding_comments + current_chunk).strip()

                    # Extract identifier (function or class name)
                    match = re.search(r"\b(function|class)\s+(\w+)", "\n".join(current_chunk))
                    identifier = match.group(2) if match else None

                    chunks.append((identifier, full_chunk))
                    preceding_comments.clear()  # Clear comments after processing
                    current_chunk = []  # Reset for the new chunk

        if line.startswith('#') or line.startswith('//'):
            preceding_comments.append(line)
        else:
            current_chunk.append(line)  # Add line to the current chunk

    # Process the last chunk if it exists
    if current_chunk:
        full_chunk = "\n".join(preceding_comments + current_chunk).strip()

        # Extract identifier (function or class name)
        match = re.search(r"\b(function|class)\s+(\w+)", "\n".join(current_chunk))
        identifier = match.group(2) if match else None

        chunks.append((identifier, full_chunk))

    return chunks

# Chunker for JSON files
def chunk_json_file(text):
    data = json.load(text)
    chunks = []
    if isinstance(data, dict):
        for key, value in data.items():
            chunks.append(json.dumps({key: value}, indent=2))
    elif isinstance(data, list):
        for item in data:
            chunks.append(json.dumps(item, indent=2))

    return chunks