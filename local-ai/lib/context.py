import subprocess
import tomli
import json


def get_git_tracked_files(root_dir):
    result = subprocess.run(
        "git ls-files", cwd=root_dir, shell=True, capture_output=True, text=True
    )
    return result.stdout.splitlines()


def get_project_dependencies(directory):
    files = get_git_tracked_files(directory)
    filepaths = [
        f"{directory}/{file}"
        for file in files
        if file.endswith("pyproject.toml") or file.endswith("package.json")
    ]
    dependencies = set()
    dev_dependencies = set()
    for filepath in filepaths:
        if filepath.endswith(".toml"):
            with open(filepath, "rb") as file:
                data = tomli.load(file)
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
