from collections import defaultdict, deque
from lib.db import get_all_snippets, get_all_dependencies


# Function to recursively unroll dependencies
def get_dependencies(identifier: str, context_limit: int):
    # Fetch all snippets and their dependencies
    snippets = {row[0]: (row[1], row[2]) for row in get_all_snippets()}

    dependencies = defaultdict(list)
    reverse_dependencies = defaultdict(int)

    for snippet_id, dependency_id in get_all_dependencies():
        dependencies[snippet_id].append(dependency_id)
        reverse_dependencies[dependency_id] += 1

    # Perform topological sort
    order = []
    queue = deque([snippet_id for snippet_id in snippets if reverse_dependencies[snippet_id] == 0])

    while queue:
        current_snippet_id = queue.popleft()
        order.append(current_snippet_id)

        for dependent_snippet_id in dependencies[current_snippet_id]:
            reverse_dependencies[dependent_snippet_id] -= 1
            if reverse_dependencies[dependent_snippet_id] == 0:
                queue.append(dependent_snippet_id)

    # Ensure the requested identifier is included
    if identifier not in order:
        print(f"Warning: Snippet with ID {identifier} does not exist or has no valid dependencies.")
        return ""

    # Filter and collect snippets starting from the required snippet
    result_order = []
    visited = set()
    stack = [identifier]

    while stack:
        current_snippet_id = stack.pop()
        if current_snippet_id in visited:
            continue
        visited.add(current_snippet_id)

        # Add all dependencies of the current snippet to the stack
        for dependent_snippet_id in reversed(dependencies[current_snippet_id]):
            if dependent_snippet_id not in visited:
                stack.append(dependent_snippet_id)

        result_order.append(current_snippet_id)

    # Reverse the order to ensure correct dependency resolution
    result_order.reverse()

    # Collect snippets based on the resolved order
    result = ""
    context_left = context_limit  # Assuming a large enough limit

    for snippet_id in result_order:
        if snippet_id not in snippets:
            continue

        source, content = snippets[snippet_id]
        current_desc = f"# {source}:\n```\n{content}\n```\n\n"

        if context_left <= len(current_desc):
            break

        result += current_desc
        context_left -= len(current_desc)

    return result