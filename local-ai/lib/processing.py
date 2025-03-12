import re
import subprocess
from lib.db import upsert_dependency
from lib.log import log
import tomli
import os
import json


def get_git_tracked_files(root_dir):
    result = subprocess.run(
        "git ls-files", cwd=root_dir, shell=True, capture_output=True, text=True
    )
    return result.stdout.splitlines()


def get_project_dependencies(filepaths):
    dependencies = set()
    dev_dependencies = set()
    for filepath in filepaths:
        if filepath.endswith(".toml"):
            with open(filepath, "rb") as file:
                data = tomli.load(file)
            print(data)
            deps_from_file = data["project"]["dependencies"]
            for line in deps_from_file:
                dependencies.add(line)
            dev_deps_from_file = data["project"].get("dev-dependencies", [])
            for line in dev_deps_from_file:
                dev_dependencies.add(line)
        elif filepath.endswith(".json"):
            with open(filepath, "r") as file:
                data = json.load(file)
            deps_from_file = data.get("dependencies", {})
            for dep, version in deps_from_file.items():
                dependencies.add(f"{dep}: {version}")
            dev_deps_from_file = data.get("devDependencies", {})
            for dep, version in dev_deps_from_file.items():
                dev_dependencies.add(f"{dep}: {version}")
    return (dependencies, dev_dependencies)


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
