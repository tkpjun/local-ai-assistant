import json
import re

# TODO
#  - also make chunks out of top-level values
#  - attach comments right above the definition
def chunk_python_code(text):
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    preceding_comments = []

    # Regular expression to match top-level variable assignments
    var_assignment_pattern = re.compile(r"^\s*(\w+)\s*=")

    for line in lines:
        stripped_line = line.strip()

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
                    chunks.append((identifier, full_chunk))
                    preceding_comments.clear()  # Clear comments after processing
                elif var_assignment_pattern.match(chunk_text):  # Check for variable assignment
                    # Extract the variable name as the identifier
                    match = var_assignment_pattern.match(chunk_text)
                    identifier = match.group(1) if match else None
                    chunks.append((identifier, full_chunk))
                    preceding_comments.clear()  # Clear comments after processing

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
            chunks.append((identifier, full_chunk))
        elif var_assignment_pattern.match(chunk_text):  # Check for variable assignment
            match = var_assignment_pattern.match(chunk_text)
            identifier = match.group(1) if match else None
            chunks.append((identifier, full_chunk))

    return chunks

# Chunker for React and JS/TS files
def chunk_react_code(text):
    pattern = r"(export\s+(?:default\s+)?(?:function|class)\s+\w+|\bfunction\s+\w+|\bclass\s+\w+)"
    matches = [m.start() for m in re.finditer(pattern, text)]

    chunks = []
    for i, start in enumerate(matches):
        end = matches[i + 1] if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        identifier = chunk.split()[1]  # Extract function or class name
        chunks.append((identifier, chunk))

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