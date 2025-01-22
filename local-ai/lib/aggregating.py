from collections import defaultdict, deque
from lib.db import get_all_snippets, get_all_dependencies
from lib.log import log


# Function to recursively unroll dependencies
def get_dependencies(identifier: str, context_limit: int):
    # Fetch all snippets and their dependencies
    snippets = {row[0]: (row[1], row[2], row[3], row[4]) for row in get_all_snippets()}

    dependencies = defaultdict(list)

    for snippet_id, dependency_id in get_all_dependencies():
        dependencies[snippet_id].append(dependency_id)

    # Filter and collect snippets starting from the required snippet using BFS
    result_order = []
    visited = set()
    queue = deque([identifier])

    while queue:
        current_snippet_id = queue.popleft()
        if current_snippet_id in visited:
            continue
        visited.add(current_snippet_id)

        # Add all dependencies of the current snippet to the queue
        for dependent_snippet_id in dependencies[current_snippet_id]:
            if dependent_snippet_id not in visited:
                queue.append(dependent_snippet_id)

        result_order.append(current_snippet_id)

    # Collect snippets based on the resolved order
    result = []
    context_left = context_limit  # Assuming a large enough limit

    for snippet_id in result_order[1:]:  # Skip the identifier itself
        if snippet_id not in snippets:
            continue

        source, content, start_line, end_line = snippets[snippet_id]

        if context_left <= len(content):
            break

        result.append((content, source, start_line, end_line))
        context_left -= len(content)

    return result


def get_dependents(identifier: str, context_limit: int):
    # Fetch all snippets and their dependencies
    snippets = {row[0]: (row[1], row[2], row[3], row[4]) for row in get_all_snippets()}

    dependencies = defaultdict(list)

    for snippet_id, dependency_id in get_all_dependencies():
        dependencies[dependency_id].append(
            snippet_id
        )  # Reverse the direction of dependency

    # Ensure the requested identifier is included
    if identifier not in snippets:
        log.warn(f"Snippet with ID {identifier} does not exist.")
        return ""

    # Filter and collect dependents starting from the required snippet using BFS
    result_order = []
    visited = set()
    queue = deque([identifier])

    while queue:
        current_snippet_id = queue.popleft()
        if current_snippet_id in visited:
            continue
        visited.add(current_snippet_id)

        # Add all snippets that depend on the current snippet to the queue
        for dependent_snippet_id in dependencies[current_snippet_id]:
            if dependent_snippet_id not in visited:
                queue.append(dependent_snippet_id)

        result_order.append(current_snippet_id)

    # Collect snippets based on the resolved order, excluding the identifier itself
    result = []
    context_left = context_limit  # Assuming a large enough limit

    for snippet_id in result_order[1:]:
        if snippet_id not in snippets:
            continue

        source, content, start_line, end_line = snippets[snippet_id]

        if context_left <= len(content):
            break

        result.append((content, source, start_line, end_line))
        context_left -= len(content)

    return result
