import re
import subprocess
from lib.db import upsert_dependency
from lib.log import log

def get_git_tracked_files(root_dir):
    result = subprocess.run(
        "git ls-files",
        cwd=root_dir,
        shell=True,
        capture_output=True,
        text=True
    )
    return result.stdout.splitlines()

# Function to process imports and store dependencies
def process_imports(filepath, modulepath, identifier, full_content, snippet_content):
    # Detect imports at the beginning of the file (Python and JS/TS)
    regex = r'^(?:import\s+\S+(?:\s+as\s+\S+)?|from\s+\S+\s+import\s+[^,\n]+(?:,\s*[^,\n]+)*)'
    import_lines = re.findall(regex, full_content, re.MULTILINE)

    # Extract only the import paths and their contents
    all_imports = {}
    for line in import_lines:
        if filepath.endswith((".js", ".ts", ".tsx")):
            # For JS/TS files
            match = re.search(r'from\s+["\'](.*?)["\']', line)
            if match:
                path = match.group(1)
                all_imports[path] = []
        elif filepath.endswith(".py"):
            # For Python files
            matches = re.findall(r'(?:from\s+(\w+(?:\.\w+)*)\s+import\s+([\w,\s]+))|(?:import\s+(\w+(?:\.\w+)*))', line)
            for match in matches:
                if match[0] and match[1]:  # from X import Y, Z
                    module_path = match[0]
                    imported_objects = [obj.strip() for obj in match[1].split(',')]
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
            # For JS/TS files, we can assume the whole module is imported
            if f'from "{module_path}"' in full_content or f"from '{module_path}'" in full_content:
                relevant_imports.append(module_path)
        elif filepath.endswith(".py"):
            # For Python files, check which specific objects are used in the snippet
            for obj in objects:
                if re.search(rf'\b{re.escape(obj)}\b', snippet_content):
                    relevant_imports.append(f"{module_path}.{obj}" if module_path != obj else module_path)

    log.debug(all_imports)
    log.debug(relevant_imports)

    # Insert dependencies into the database
    for imp in relevant_imports:
        upsert_dependency(modulepath, identifier, imp)