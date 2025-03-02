from collections import defaultdict, deque
from typing import Dict, List, Tuple

from lib.db import get_all_snippets, get_all_dependencies
from lib.log import log


# Function to recursively unroll dependencies
def fetch_snippets(snippet_ids: List[str]) -> Dict[str, Tuple[str, str, int, int]]:
    """
    Fetch snippet details for given identifiers.

    :param snippet_ids: List of snippet identifiers to fetch.
    :return: Dictionary mapping snippet identifier to (source, content, start_line, end_line).
    """
    all_snippets = {row[0]: (row[1], row[2], row[3], row[4]) for row in get_all_snippets()}
    return {sid: details for sid, details in all_snippets.items() if sid in snippet_ids}


def build_dependency_graph() -> Dict[str, List[str]]:
    """
    Build a dependency graph from all dependencies.

    :return: Dictionary mapping each snippet ID to a list of its dependent snippet IDs.
    """
    graph = defaultdict(list)
    for snippet_id, dependency_id in get_all_dependencies():
        graph[snippet_id].append(dependency_id)
    return graph


def resolve_dependency_order(identifier: str, graph: Dict[str, List[str]]) -> List[str]:
    """
    Resolve the order of dependencies starting from a given identifier using BFS.

    :param identifier: Starting snippet identifier.
    :param graph: Dependency graph built by build_dependency_graph().
    :return: Ordered list of snippet identifiers based on dependency resolution.
    """
    visited = set()
    queue = deque([identifier])
    result_order = []

    while queue:
        current_snippet_id = queue.popleft()
        if current_snippet_id in visited:
            continue
        visited.add(current_snippet_id)

        for dependent_snippet_id in graph[current_snippet_id]:
            if dependent_snippet_id not in visited:
                queue.append(dependent_snippet_id)

        result_order.append(current_snippet_id)

    return result_order[1:]  # Skip the identifier itself


def get_dependencies(identifier: str) -> List[Tuple[str, str, int, int]]:
    """
    Get dependencies for a given snippet identifier within the specified context limit.

    :param identifier: Starting snippet identifier.
    :return: List of (content, source, start_line, end_line) tuples for each dependent snippet.
    """
    graph = build_dependency_graph()
    result_order = resolve_dependency_order(identifier, graph)

    snippets = fetch_snippets(result_order)

    result = []

    for snippet_id in result_order:
        if snippet_id not in snippets:
            continue

        source, content, start_line, end_line = snippets[snippet_id]
        result.append((content, source, start_line, end_line))

    return result


def collect_dependencies(snippet_ids: List[str]) -> List[Tuple[str, str, int, int]]:
    """
    Collect dependencies for given snippet identifiers within the specified context limit.

    :param snippet_ids: List of snippet identifiers.
    :return: List of (content, source, start_line, end_line) tuples for each dependent snippet.
    """
    snippets = fetch_snippets(snippet_ids)

    result = []

    for snippet_id in snippet_ids:
        if snippet_id not in snippets:
            continue

        source, content, start_line, end_line = snippets[snippet_id]
        result.append((content, source, start_line, end_line))

    return result


def build_reverse_dependency_graph() -> Dict[str, List[str]]:
    """
    Build a reverse dependency graph from all dependencies.

    :return: Dictionary mapping each snippet ID to a list of its dependent snippet IDs.
    """
    graph = defaultdict(list)
    for snippet_id, dependency_id in get_all_dependencies():
        graph[dependency_id].append(snippet_id)  # Reverse the direction of dependency
    return graph


def resolve_dependents_order(start_snippet_id: str, reverse_graph: Dict[str, List[str]]) -> List[str]:
    """
    Resolve the order of dependents starting from a given identifier using BFS.

    :param start_snippet_id: Starting snippet identifier.
    :param reverse_graph: Reverse dependency graph built by build_reverse_dependency_graph().
    :return: Ordered list of snippet identifiers based on dependent resolution.
    """
    visited = set()
    queue = deque([start_snippet_id])
    result_order = []

    while queue:
        current_snippet_id = queue.popleft()
        if current_snippet_id in visited:
            continue
        visited.add(current_snippet_id)

        for dependent_snippet_id in reverse_graph[current_snippet_id]:
            if dependent_snippet_id not in visited:
                queue.append(dependent_snippet_id)

        result_order.append(current_snippet_id)

    return result_order[1:]  # Skip the identifier itself


def get_dependents(start_snippet_id: str) -> List[Tuple[str, str, int, int]]:
    """
    Get dependents for a given snippet identifier within the specified context limit.

    :param start_snippet_id: Starting snippet identifier.
    :return: List of (content, source, start_line, end_line) tuples for each dependent snippet.
    """
    reverse_graph = build_reverse_dependency_graph()
    result_order = resolve_dependents_order(start_snippet_id, reverse_graph)
    return collect_dependencies(result_order)

