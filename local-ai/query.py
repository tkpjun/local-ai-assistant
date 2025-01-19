import json

import gradio as gr
import requests
from lib.aggregating import get_dependencies
import sqlite3

# Connect to SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect("../codebase.db", check_same_thread=False)
cursor = conn.cursor()

def stream_chat(history, user_message, file_reference, include_dependencies, file_reference_2, include_dependencies_2, history_cutoff, context_cutoff):
    history = history or []  # Ensure history is not None
    prompt = ""
    context_snippets = []
    file_order = []

    if include_dependencies or include_dependencies_2:
        if include_dependencies:
            context_snippets += get_dependencies(file_reference, context_cutoff)
        if include_dependencies_2:
            context_snippets += get_dependencies(file_reference_2, context_cutoff)
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

        prompt += f"Code file with dependencies denoted in Markdown:\n\n"
        current_source = ""
        for content, source, _, _ in context_snippets:
            if source != current_source:
                if current_source:
                    prompt += "```\n\n"
                prompt += f"# {source}:\n```\n"
                current_source = source
            else:
                prompt += "\n"
            prompt += f"{content}\n"
        prompt += "```"

    print(prompt)

    history_applied = 0
    history_index = -1
    prompt += "Chat history:\n\n"
    while history_applied < history_cutoff and len(history) >= -history_index:
        prompt += f"User:\n{history[history_index][0]}\nYou:\n{history[history_index][1]}\n"
        history_applied += len(history[history_index][0]) + len(history[history_index][1])
        history_index -= 1
    history.append((user_message, ""))

    prompt += f"User:\n{user_message}\n"

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "qwen2.5-coder:32b", "prompt": prompt},
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

def fetch_file_paths():
    cursor.execute("SELECT id FROM snippets ORDER BY id")
    file_paths = cursor.fetchall()
    return [path[0] for path in file_paths]

# Fetch file paths from the database
file_paths = fetch_file_paths()

# Create a Gradio chat interface with streaming
with gr.Blocks() as chat_interface:
    gr.Markdown("## 💬 Chat with Your Local LLM (Ollama)")

    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(elem_id="chatbot", min_height=800)
            user_input = gr.Textbox(placeholder="Type your question here...", label="Your Message")
        with gr.Column(scale=1):
            with gr.Row():
                history_cutoff = gr.Number(label="History Cutoff (max length)", value=10000, precision=0)
                context_cutoff = gr.Number(label="Context Cutoff (max length)", value=10000, precision=0)
            with gr.Row():
                with gr.Column():
                    file_reference = gr.Dropdown(label="Select File Path", choices=file_paths, value=None, allow_custom_value=True)
                    include_dependencies = gr.Checkbox(label="Include Dependencies", value=False)
            with gr.Row():
                with gr.Column():
                    file_reference_2 = gr.Dropdown(label="Select File Path", choices=file_paths, value=None, allow_custom_value=True)
                    include_dependencies_2 = gr.Checkbox(label="Include Dependencies", value=False)

    # Handle user input and display the streaming response
    user_input.submit(fn=stream_chat, inputs=[chatbot, user_input, file_reference, include_dependencies, file_reference_2, include_dependencies_2, history_cutoff, context_cutoff], outputs=chatbot)

# Launch the Gradio app
chat_interface.launch()