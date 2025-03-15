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

assistants = [("Coder", system_prompt)]


def update_prompt(name, new_prompt):
    global assistants
    for i, (n, p) in enumerate(assistants):
        if n == name:
            assistants[i] = (name, new_prompt)
            break


def add_assistant(new_name):
    global assistants
    if new_name.strip():
        assistants.append((new_name, ""))


def get_assistant_prompt():
    return assistants[0][1]
