import json

import gradio as gr
import requests
from lib.aggregating import get_dependencies, get_dependents
from lib.processing import get_git_tracked_files, get_project_dependencies
import sys
from dotenv import load_dotenv
import os
import tiktoken
from lib.ollama import run_ollama_model_in_background, get_running_ollama_models, stop_ollama_model_by_name, get_ollama_model_names
from lib.db import fetch_snippet_ids, fetch_snippets_by_source, fetch_snippet_by_id

load_dotenv(override=False)

tokenizer = tiktoken.encoding_for_model("gpt-4o")
directory = sys.argv[1]

system_prompt = """
You're an AI assistant. Your task is to write code for User. 
You can also make helpful suggestions to improve the existing codebase.

You write code that is:
- readable
- testable
- modularized based on project structure
- using mainstream libraries

Communicate in code snippets as User does.
"""


installed_llms = get_ollama_model_names()
snippet_ids = fetch_snippet_ids(directory)
files = get_git_tracked_files(directory)
definition_files = [
    f"{directory}/{file}"
    for file in files
    if file.endswith("pyproject.toml") or file.endswith("package.json")
]
(project_dependencies, dev_dependencies) = get_project_dependencies(definition_files)

def build_prompt(
    history,
    user_message,
    file_reference,
    file_options,
    file_reference_2,
    file_options_2,
    history_cutoff,
    options,
    selected_llm,
):
    history = history or []  # Ensure history is not None
    context_prompt = ""

    if "Include project dependencies" in options:
        context_prompt += "\n# Project dependencies:\n"
        for dependency in project_dependencies:
            context_prompt += f"- {dependency}\n"

        context_prompt += "\n# Dev dependencies:\n"
        for dependency in dev_dependencies:
            context_prompt += f"- {dependency}\n"

    if "Include file structure" in options:
        context_prompt += "\n# Project structure:\n"
        for file in files:
            context_prompt += f"- {file}\n"
            snippet_names = fetch_snippets_by_source(f"{directory}/{file}")
            if ".test." in file or ".test-" in file:
                continue
            for name in snippet_names:
                context_prompt += f"  - {name}\n"

    context_snippets = []
    file_order = []

    if file_options == "Dependencies":
        context_snippets += get_dependencies(file_reference)
    if file_options_2 == "Dependencies":
        context_snippets += get_dependencies(file_reference_2)
    if file_options == "Dependents":
        context_snippets += get_dependents(file_reference)
    if file_options_2 == "Dependents":
        context_snippets += get_dependents(file_reference_2)
    if file_reference is not None:
        context_snippets.append(fetch_snippet_by_id(file_reference))
    if file_reference_2 is not None:
        context_snippets.append(fetch_snippet_by_id(file_reference_2))

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

        context_prompt += f"\n# Relevant snippets of project code denoted in Markdown:\n\n"
        current_source = ""
        for content, source, _, _ in context_snippets:
            if source != current_source:
                if current_source:
                    context_prompt += "```\n\n"
                context_prompt += f"## {source}:\n```\n"
                current_source = source
            else:
                context_prompt += "\n"
            context_prompt += f"{content}\n"
        context_prompt += "```"

    running_llms = get_running_ollama_models()
    if not running_llms.get(selected_llm):
        for llm in running_llms.keys():
            stop_ollama_model_by_name(llm)
        run_ollama_model_in_background(selected_llm)

    insert_index = 1 if context_prompt == "" else 2
    chat_messages = [{ "role": "system", "content": system_prompt }]
    tokens_used = 0
    if context_prompt != "":
        chat_messages.append({ "role": "user", "content": context_prompt })
    for (old_user_message, llm_response) in reversed(history):
        if llm_response != "":
            tokens_used += len(tokenizer.encode(text=llm_response))
            if tokens_used <= history_cutoff:
                chat_messages.insert(insert_index, { "role": "assistant", "content": llm_response })
        tokens_used += len(tokenizer.encode(text=old_user_message))
        if tokens_used <= history_cutoff:
            chat_messages.insert(insert_index, { "role": "user", "content": old_user_message })
    if user_message:
        chat_messages.append({ "role": "user", "content": user_message })
    return {"model": selected_llm, "messages": chat_messages}

def build_prompt_code(
        history,
        user_message,
        file_reference,
        file_options,
        file_reference_2,
        file_options_2,
        history_cutoff,
        options,
        selected_llm,
):
    prompt = build_prompt(history,
                          user_message,
                          file_reference,
                          file_options,
                          file_reference_2,
                          file_options_2,
                          history_cutoff,
                          options,
                          selected_llm)
    markdown = ""
    for message in prompt["messages"]:
        token_amount = len(tokenizer.encode(text=message["content"]))
        markdown += f"\n# (tokens: {token_amount}) {message["role"]}:\n{message["content"]}\n\n***\n\n"
    return markdown

def stream_chat(
    history,
    user_message,
    file_reference,
    file_options,
    file_reference_2,
    file_options_2,
    history_cutoff,
    options,
    selected_llm,
):
    history = history or []  # Ensure history is not None
    prompt = build_prompt(history,
                          user_message,
                          file_reference,
                          file_options,
                          file_reference_2,
                          file_options_2,
                          history_cutoff,
                          options,
                          selected_llm)
    response = requests.post(
        os.getenv("LLM_CHAT_ENDPOINT"),
        json=prompt,
        stream=True,
    )
    response.raise_for_status()
    # Stream the response line by line
    history.append((user_message, ""))
    bot_message = ""
    thinking = 0
    for line in response.iter_lines():
        if line:
            try:
                data = json.loads(line.decode("utf-8"))
                if (data["message"]["content"]) == "<think>":
                    thinking = 1
                if (data["message"]["content"]) == "</think>":
                    bot_message = ""
                    thinking = 0
                if thinking == 0:
                    bot_message += data["message"]["content"]
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
            with gr.Tab(label="Chat"):
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
            with gr.Tab(label="Prompt (JSON)"):
                prompt_box = gr.Json()
                build_prompt_button = gr.Button("Generate")
            with gr.Tab(label="Prompt (Markdown)"):
                prompt_md_box = gr.Markdown()
                build_prompt_md_button = gr.Button("Generate")
        with gr.Column(scale=1, min_width=400):
            selected_llm = gr.Dropdown(
                label="Selected LLM", choices=installed_llms, value=installed_llms[0]
            )
            history_cutoff = gr.Number(
                label="Chat history max tokens", value=3000, precision=0
            )
            options = gr.CheckboxGroup(
                choices=["Project dependencies", "File structure"],
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
            options,
            selected_llm,
        ],
        outputs=chatbot,
    )
    user_input.submit(lambda x: gr.update(value=""), None, [user_input], queue=False)
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
            options,
            selected_llm,
        ],
        chatbot,
    )
    build_prompt_button.click(
        build_prompt,
        inputs=[chatbot,
                user_input,
                file_reference,
                file_options,
                file_reference_2,
                file_options_2,
                history_cutoff,
                options,
                selected_llm],
        outputs=prompt_box
    )
    build_prompt_md_button.click(
        build_prompt_code,
        inputs=[chatbot,
                user_input,
                file_reference,
                file_options,
                file_reference_2,
                file_options_2,
                history_cutoff,
                options,
                selected_llm],
        outputs=prompt_md_box
    )

# Launch the Gradio app
chat_interface.launch()
