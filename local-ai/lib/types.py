from dataclasses import dataclass
from typing import List


@dataclass
class Assistant:
    name: str
    llm: str | None
    context_limit: int
    response_size_limit: int
    prompt: str = ""


@dataclass
class Chunk:
    name: str | None
    content: str
    start_line: int
    end_line: int
    type: str


@dataclass
class Snippet:
    id: str
    source: str
    module: str
    name: str | None
    content: str
    start_line: int
    end_line: int
    type: str


@dataclass
class Dependency:
    snippet_id: str
    dependency_name: str


@dataclass
class UIState:
    assistant_name: str = ""
    extra_content_options: List[str] = None
    selected_snippets: List[str] = None
