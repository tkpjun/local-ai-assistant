from dataclasses import dataclass


@dataclass
class Assistant:
    name: str
    llm: str | None
    context_limit: int
    prompt: str = ""


system_prompt = """
You're an AI assistant. Your task is to write code for User. 
You can also make helpful suggestions to improve the existing codebase.

You write code that is:
- readable
- testable
- modularized based on project structure
- using mainstream libraries

Communicate in code snippets as User does.
""".strip(
    "\n"
)

assistants = [Assistant("Coder", None, 8192, system_prompt)]


def update_prompt(name, new_prompt):
    global assistants
    for assistant in assistants:
        if assistant.name == name:
            assistant.prompt = new_prompt
            break


def update_llm(name, new_llm):
    global assistants
    for assistant in assistants:
        if assistant.name == name:
            assistant.llm = new_llm
            break

def update_context_limit(name, new_context_limit):
    global assistants
    for assistant in assistants:
        if assistant.name == name:
            assistant.context_limit = new_context_limit
            break


def add_assistant(new_name):
    global assistants
    if new_name.strip():
        assistants.append(Assistant(new_name, None, 8192, ""))


def get_assistant_prompt():
    return assistants[0].prompt


def get_assistant(name):
    for assistant in assistants:
        if assistant.name == name:
            return assistant
    return None
