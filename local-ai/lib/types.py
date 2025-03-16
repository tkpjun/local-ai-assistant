from dataclasses import dataclass


@dataclass
class Assistant:
    name: str
    llm: str | None
    context_limit: int
    prompt: str = ""
