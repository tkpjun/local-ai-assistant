import json

import gradio as gr
import requests
from lib.aggregating import get_dependencies, get_dependents
import sqlite3
from lib.processing import get_git_tracked_files, get_project_dependencies
import sys
from dotenv import load_dotenv
import os

load_dotenv(override=False)

directory = sys.argv[1]

# Connect to SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect("../codebase.db", check_same_thread=False)
cursor = conn.cursor()

def fetch_snippet_ids():
    cursor.execute("SELECT id FROM snippets WHERE source LIKE ? ORDER BY id", (f"{directory}%",))
    snippet_ids = cursor.fetchall()
    return [snippet_id[0] for snippet_id in snippet_ids]

def fetch_snippets_by_source(source):
    cursor.execute("SELECT name FROM snippets WHERE source = ? AND name IS NOT NULL and name != '_imports_' ORDER BY name", (source,))
    names = cursor.fetchall()
    return [name[0] for name in names]

# Fetch file paths from the database
snippet_ids = fetch_snippet_ids()
files = get_git_tracked_files(directory)
definition_files = [f"{directory}/{file}" for file in files if file.endswith("pyproject.toml")]
(project_dependencies, dev_dependencies) = get_project_dependencies(definition_files)

# TODO
#  - get_dependents function

def stream_chat(history, user_message, file_reference, file_options, file_reference_2, file_options_2, history_cutoff, context_cutoff):
    history = history or []  # Ensure history is not None
    prompt = """# Context:
You're an elite software developer. You're pair programming with User over chat.
Propose readable, elegant ahd testable solutions that offload complexity to appropriate libraries.
Modularize code into different files based on its dependencies, denoted in Markdown.
Use the project structure for clues about correct modularization.

Every programming task should lead to a Potentially Releasable Product Increment.
If User gives you a task that seems like more than one Jira ticket, break it down into independent sub-tasks, and solve them one at a time.
Don't solve more than one task per message, ask User for confirmation before proceeding to the next.
If User's instructions are too vague for you to write good software, ask clarifying questions before writing code.

User is also a professional and doesn't need instruction unless they ask for it.
When coding, you just write out the task and then write snippets of code changes.

If the project exceeds expectations, everyone will be happy and you will get a reward.
"""

    prompt += "\n# Project dependencies:\n"
    for dependency in project_dependencies:
        prompt += f"- {dependency}\n"

    prompt += "\n# Dev dependencies:\n"
    for dependency in dev_dependencies:
        prompt += f"- {dependency}\n"

    prompt += "\n# Project structure:\n"
    for file in files:
        prompt += f"- {file}\n"
        snippet_names = fetch_snippets_by_source(f"{directory}/{file}")
        for name in snippet_names:
            prompt += f"  - {name}\n"

    context_snippets = []
    file_order = []

    if file_options == "Dependencies":
        context_snippets += get_dependencies(file_reference, context_cutoff)
    if file_options_2 == "Dependencies":
        context_snippets += get_dependencies(file_reference_2, context_cutoff)
    if file_options == "Dependents":
        context_snippets += get_dependents(file_reference, context_cutoff)
    if file_options_2 == "Dependents":
        context_snippets += get_dependents(file_reference_2, context_cutoff)
    if file_reference is not None:
        cursor.execute("SELECT content, source, start_line, end_line FROM snippets WHERE id = ?", (file_reference,))
        snippet = cursor.fetchone()
        context_snippets.append(snippet)
    if file_reference_2 is not None:
        cursor.execute("SELECT content, source, start_line, end_line FROM snippets WHERE id = ?", (file_reference_2,))
        snippet = cursor.fetchone()
        context_snippets.append(snippet)

    if context_snippets:
        for _, source, _, _ in context_snippets:
            if file_order.count(source) > 0:
                file_order.remove(source)
            file_order.append(source)

        seen = set()
        context_snippets = [dep for dep in context_snippets if (dep[1], dep[2], dep[3]) not in seen and not seen.add((dep[1], dep[2], dep[3]))]
        context_snippets = sorted(context_snippets, key=lambda dep: (file_order.index(dep[1]), dep[2]))

        prompt += f"\n# Relevant snippets of project code denoted in Markdown:\n\n"
        current_source = ""
        for content, source, _, _ in context_snippets:
            if source != current_source:
                if current_source:
                    prompt += "```\n\n"
                prompt += f"## {source}:\n```\n"
                current_source = source
            else:
                prompt += "\n"
            prompt += f"{content}\n"
        prompt += "```"

    print(prompt)

    history_applied = 0
    history_index = -1
    prompt += "\n# Chat history:\n\n"
    while history_applied < history_cutoff and len(history) >= -history_index:
        prompt += f"User:\n{history[history_index][0]}\nYou:\n{history[history_index][1]}\n"
        history_applied += len(history[history_index][0]) + len(history[history_index][1])
        history_index -= 1
    history.append((user_message, ""))

    prompt += f"User:\n{user_message}\n"

    response = requests.post(
        os.getenv("LLM_QUERY_ENDPOINT"),
        json={"model": os.getenv("FAST_LLM"), "prompt": prompt},
        stream=True
    )
    response.raise_for_status()
    # Stream the response line by line
    bot_message = ""
    for line in response.iter_lines():
        if line:
            try:
                data = json.loads(line.decode("utf-8"))
                bot_message += data["response"]
                history[-1] = (user_message, bot_message)  # Update the bot response
                yield history
                if data.get("done"):
                    break
            except json.JSONDecodeError:
                continue

# Create a Gradio chat interface with streaming
with gr.Blocks() as chat_interface:
    gr.Markdown("## 💬 Chat with Your Local LLM")

    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(elem_id="chatbot", min_height=800)
            user_input = gr.Textbox(placeholder="Type your question here...", label="Your Message")
        with gr.Column(scale=1, min_width=400):
            with gr.Row():
                history_cutoff = gr.Number(label="History Cutoff (max length)", value=10000, precision=0)
                context_cutoff = gr.Number(label="Context Cutoff (max length)", value=10000, precision=0)
            with gr.Row():
                with gr.Column():
                    file_reference = gr.Dropdown(label="Select snippet by module", choices=snippet_ids, value=None, allow_custom_value=True)
                    file_options = gr.Radio(choices=["Snippet", "Dependencies", "Dependents"], value="Snippet", label="Include")
            with gr.Row():
                with gr.Column():
                    file_reference_2 = gr.Dropdown(label="Select snippet by module", choices=snippet_ids, value=None, allow_custom_value=True)
                    file_options_2 = gr.Radio(choices=["Snippet", "Dependencies", "Dependents"], value="Snippet", label="Include")

    # Handle user input and display the streaming response
    user_input.submit(fn=stream_chat, inputs=[chatbot, user_input, file_reference, file_options, file_reference_2, file_options_2, history_cutoff, context_cutoff], outputs=chatbot)

# Launch the Gradio app
chat_interface.launch()