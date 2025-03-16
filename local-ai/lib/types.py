from dataclasses import dataclass


@dataclass
class Assistant:
    name: str
    llm: str | None
    context_limit: int
    response_size_limit: int
    prompt: str = ""
