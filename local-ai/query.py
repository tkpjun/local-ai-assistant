import json

import gradio as gr
import requests
from lib.aggregating import get_dependencies, get_dependents
import sqlite3
from lib.processing import get_git_tracked_files, get_project_dependencies
import sys
from dotenv import load_dotenv
import os
import subprocess

load_dotenv(override=False)

directory = sys.argv[1]

# Connect to SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect("../codebase.db", check_same_thread=False)
cursor = conn.cursor()


def get_ollama_model_names():
    try:
        # Call `ollama list` and capture the output
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=True
        )
        # Extract lines of the output (skip the header line)
        lines = result.stdout.strip().split("\n")[1:]
        # Extract the model names (first column of each line)
        model_names = [line.split()[0] for line in lines if line]
        return model_names
    except subprocess.CalledProcessError as e:
        print(f"Error while running 'ollama list': {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []


def get_running_ollama_models():
    try:
        # Call `ollama ps` and capture the output
        result = subprocess.run(
            ["ollama", "ps"], capture_output=True, text=True, check=True
        )
        # Extract lines of the output (skip the header line)
        lines = result.stdout.strip().split("\n")[1:]
        # Extract model names and IDs (first and second columns)
        running_models = {}
        for line in lines:
            if line.strip():  # Skip empty lines
                parts = line.split()  # Split by whitespace
                model_name = parts[0]
                model_id = parts[1]
                running_models[model_name] = model_id

        return running_models
    except subprocess.CalledProcessError as e:
        print(f"Error while running 'ollama ps': {e}")
        return {}
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {}


def stop_ollama_model_by_name(name):
    try:
        # Call `ollama stop` with the model name
        subprocess.run(
            ["ollama", "stop", name], capture_output=True, text=True, check=True
        )
        return f"Successfully stopped model '{name}'."
    except subprocess.CalledProcessError as e:
        return f"Error stopping model '{name}': {e.stderr.strip()}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


def run_ollama_model_in_background(name):
    try:
        # Run `ollama run` in the background
        process = subprocess.Popen(
            ["ollama", "run", name],
            stdout=subprocess.PIPE,  # Redirect stdout
            stderr=subprocess.PIPE,  # Redirect stderr
            text=True,  # Decode output to strings
        )
        return f"Model '{name}' is running in the background (PID: {process.pid})."
    except Exception as e:
        return f"Failed to run model '{name}': {str(e)}"


def fetch_snippet_ids():
    cursor.execute(
        "SELECT id FROM snippets WHERE source LIKE ? ORDER BY id", (f"{directory}%",)
    )
    snippet_ids = cursor.fetchall()
    return [snippet_id[0] for snippet_id in snippet_ids]


def fetch_snippets_by_source(source):
    cursor.execute(
        "SELECT name FROM snippets WHERE source = ? AND name IS NOT NULL and name != '_imports_' ORDER BY name",
        (source,),
    )
    names = cursor.fetchall()
    return [name[0] for name in names]


installed_llms = get_ollama_model_names()
snippet_ids = fetch_snippet_ids()
files = get_git_tracked_files(directory)
definition_files = [
    f"{directory}/{file}"
    for file in files
    if file.endswith("pyproject.toml") or file.endswith("package.json")
]
(project_dependencies, dev_dependencies) = get_project_dependencies(definition_files)


def stream_chat(
    history,
    user_message,
    file_reference,
    file_options,
    file_reference_2,
    file_options_2,
    history_cutoff,
    context_cutoff,
    options,
    selected_llm,
):
    history = history or []  # Ensure history is not None
    prompt = """# Context:
You're a software developer with 10 years of experience. 
You are doing pair programming with User. Your task is to write code for User.
Propose readable, elegant ahd testable solutions that offload complexity to project libraries.
Modularize code according to existing project structure when functions get too large.
Ask clarifying questions instead of writing code if User is vague.

User is also a professional and doesn't need instruction unless they ask for it.
When coding, just write out the task and then write snippets of code changes.

If the project exceeds expectations, everyone will be happy and you will get a reward.
"""

    if "Include project dependencies" in options:
        prompt += "\n# Project dependencies:\n"
        for dependency in project_dependencies:
            prompt += f"- {dependency}\n"

        prompt += "\n# Dev dependencies:\n"
        for dependency in dev_dependencies:
            prompt += f"- {dependency}\n"

    if "Include file structure" in options:
        prompt += "\n# Project structure:\n"
        for file in files:
            prompt += f"- {file}\n"
            snippet_names = fetch_snippets_by_source(f"{directory}/{file}")
            if ".test." in file or ".test-" in file:
                continue
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
        cursor.execute(
            "SELECT content, source, start_line, end_line FROM snippets WHERE id = ?",
            (file_reference,),
        )
        snippet = cursor.fetchone()
        context_snippets.append(snippet)
    if file_reference_2 is not None:
        cursor.execute(
            "SELECT content, source, start_line, end_line FROM snippets WHERE id = ?",
            (file_reference_2,),
        )
        snippet = cursor.fetchone()
        context_snippets.append(snippet)

    if context_snippets:
        for _, source, _, _ in context_snippets:
            if file_order.count(source) > 0:
                file_order.remove(source)
            file_order.append(source)

        seen = set()
        context_snippets = [
            dep
            for dep in context_snippets
            if (dep[1], dep[2], dep[3]) not in seen
            and not seen.add((dep[1], dep[2], dep[3]))
        ]
        context_snippets = sorted(
            context_snippets, key=lambda dep: (file_order.index(dep[1]), dep[2])
        )

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

    history_applied = 0
    history_index = -1
    prompt += "\n# Chat history:\n\n"
    while history_applied < history_cutoff and len(history) >= -history_index:
        prompt += (
            f"User:\n{history[history_index][0]}\nYou:\n{history[history_index][1]}\n"
        )
        history_applied += len(history[history_index][0]) + len(
            history[history_index][1]
        )
        history_index -= 1
    history.append((user_message, ""))

    prompt += f"User:\n{user_message}\n"

    running_llms = get_running_ollama_models()
    if not running_llms.get(selected_llm):
        for llm in running_llms.keys():
            stop_ollama_model_by_name(llm)
        run_ollama_model_in_background(selected_llm)

    response = requests.post(
        os.getenv("LLM_QUERY_ENDPOINT"),
        json={"model": selected_llm, "prompt": prompt},
        stream=True,
    )
    response.raise_for_status()
    # Stream the response line by line
    bot_message = ""
    thinking = 0
    for line in response.iter_lines():
        if line:
            try:
                data = json.loads(line.decode("utf-8"))
                if (data["response"]) == "<think>":
                    thinking = 1
                if (data["response"]) == "</think>":
                    bot_message = ""
                    thinking = 0
                if thinking == 0:
                    bot_message += data["response"]
                else:
                    dots = ""
                    for dot in range(thinking):
                        dots += "."
                    bot_message = f"Thinking{dots}"
                    thinking = (thinking + 1) % 3 + 1

                history[-1] = (user_message, bot_message)  # Update the bot response
                yield history
                if data.get("done"):
                    break
            except json.JSONDecodeError:
                continue


def delete_message(chatbot):
    if chatbot and len(chatbot) > 0:
        chatbot.pop()  # Remove the last message from the history
    return chatbot


def retry_last_message(
    chatbot,
    file_reference,
    file_options,
    file_reference_2,
    file_options_2,
    history_cutoff,
    context_cutoff,
    options,
    selected_llm,
):
    if chatbot and len(chatbot) > 0:
        (user_message, _) = chatbot.pop()
        generator = stream_chat(
            chatbot,
            user_message,
            file_reference,
            file_options,
            file_reference_2,
            file_options_2,
            history_cutoff,
            context_cutoff,
            options,
            selected_llm,
        )
        for chat_history in generator:
            yield chat_history
    else:
        yield chatbot


# Create a Gradio chat interface with streaming
with gr.Blocks(fill_height=True) as chat_interface:
    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(elem_id="chatbot", min_height=800, editable="all")
            user_input = gr.Textbox(
                placeholder="Type your question here...", label="Your Message"
            )
            with gr.Row():
                retry_button = gr.Button("Retry response")
                delete_button = gr.Button("Delete message")
                clear_button = gr.ClearButton(
                    [user_input, chatbot], value="Clear history"
                )
        with gr.Column(scale=1, min_width=400):
            selected_llm = gr.Dropdown(
                label="Selected LLM", choices=installed_llms, value=installed_llms[0]
            )
            with gr.Row():
                history_cutoff = gr.Number(
                    label="History Cutoff (max length)", value=10000, precision=0
                )
                context_cutoff = gr.Number(
                    label="Context Cutoff (max length)", value=10000, precision=0
                )
            options = gr.CheckboxGroup(
                choices=["Include project dependencies", "Include file structure"],
                label="Options",
            )
            with gr.Row():
                with gr.Column():
                    file_reference = gr.Dropdown(
                        label="Select snippet by module",
                        choices=snippet_ids,
                        value=None,
                        allow_custom_value=True,
                    )
                    file_options = gr.Radio(
                        choices=["Snippet", "Dependencies", "Dependents"],
                        value="Snippet",
                        label="Include",
                    )
            with gr.Row():
                with gr.Column():
                    file_reference_2 = gr.Dropdown(
                        label="Select snippet by module",
                        choices=snippet_ids,
                        value=None,
                        allow_custom_value=True,
                    )
                    file_options_2 = gr.Radio(
                        choices=["Snippet", "Dependencies", "Dependents"],
                        value="Snippet",
                        label="Include",
                    )

    # Handle user input and display the streaming response
    user_input.submit(
        fn=stream_chat,
        inputs=[
            chatbot,
            user_input,
            file_reference,
            file_options,
            file_reference_2,
            file_options_2,
            history_cutoff,
            context_cutoff,
            options,
            selected_llm,
        ],
        outputs=chatbot,
    ).then(
        lambda: "",  # This lambda function returns an empty string
        None,
        user_input,  # Update the user_input field with the empty string
    )
    delete_button.click(delete_message, [chatbot], chatbot)
    retry_button.click(
        retry_last_message,
        [
            chatbot,
            file_reference,
            file_options,
            file_reference_2,
            file_options_2,
            history_cutoff,
            context_cutoff,
            options,
            selected_llm,
        ],
        chatbot,
    )

# Launch the Gradio app
chat_interface.launch()
