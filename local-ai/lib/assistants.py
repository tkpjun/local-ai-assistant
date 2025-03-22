from lib.types import Assistant
from lib.db import upsert_assistant, fetch_all_assistants, fetch_assistant_by_name


def get_default_assistant():
    default_prompt = """
You're an AI assistant. Your task is to write code for User. 
You can also make helpful suggestions to improve the existing codebase.

You write code that is:
- readable
- testable
- modularized
- using mainstream libraries

Communicate in code snippets as User does.
""".strip()
    return Assistant("Coder", None, 6000, 4096, default_prompt)


def get_all_assistants():
    assistants_data = fetch_all_assistants()
    if not assistants_data:
        default_assistant = get_default_assistant()
        upsert_assistant(default_assistant)
        return [default_assistant]
    return assistants_data


def get_assistant_prompt():
    assistant = fetch_assistant_by_name("Coder")
    if assistant:
        return assistant.prompt
    return None


def add_assistant(new_name: str):
    if not fetch_assistant_by_name(new_name):
        upsert_assistant(Assistant(new_name, None, 6000, 4096, ""))
