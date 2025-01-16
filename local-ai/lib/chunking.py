import json
import re

def chunk_python_code(text):
    # Regex to match function and class definitions
    pattern = r"(\bdef\s+\w+\(.*?\):|\bclass\s+\w+\(?.*?\)?:)"
    matches = [m.start() for m in re.finditer(pattern, text)]

    chunks = []
    for i, start in enumerate(matches):
        end = matches[i + 1] if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()

        # Extract identifier (class or function name)
        identifier_match = re.search(r"(class|def)\s+(\w+)", chunk)
        identifier = identifier_match.group(2) if identifier_match else None

        chunks.append((identifier, chunk))

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