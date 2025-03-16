import json
import requests
import os
import tiktoken
import sys
from lib.db import (
    fetch_snippets_by_source,
    fetch_snippet_by_id,
    fetch_assistant_by_name,
)
from lib.ollama import (
    run_ollama_model_in_background,
    get_running_ollama_models,
    stop_ollama_model_by_name,
    get_ollama_model_names,
)
from lib.context import get_git_tracked_files, get_project_dependencies
from lib.assistants import get_assistant_prompt

tokenizer = tiktoken.encoding_for_model("gpt-4o")
directory = os.path.abspath(sys.argv[1])


def build_prompt(
    history,
    user_message,
    file_reference,
    selected_assistant,
    options,
):
    assistant = fetch_assistant_by_name(selected_assistant)
    history = history or []  # Ensure history is not None
    context_prompt = ""

    if "Include project dependencies" in options:
        (project_dependencies, dev_dependencies) = get_project_dependencies(directory)
        context_prompt += "\n# Project dependencies:\n"
        for dependency in project_dependencies:
            context_prompt += f"- {dependency}\n"

        context_prompt += "\n# Dev dependencies:\n"
        for dependency in dev_dependencies:
            context_prompt += f"- {dependency}\n"

    if "Include file structure" in options:
        files = get_git_tracked_files(directory)
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

    for snippet_id in file_reference:
        context_snippets.append(fetch_snippet_by_id(snippet_id))

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

        context_prompt += (
            f"\n# Relevant snippets of project code denoted in Markdown:\n\n"
        )
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
    if not running_llms.get(assistant.llm):
        for llm in running_llms.keys():
            stop_ollama_model_by_name(llm)
        run_ollama_model_in_background(assistant.llm)

    system_prompt_with_context = get_assistant_prompt()
    if context_prompt != "":
        system_prompt_with_context += f"\n\n{context_prompt}"
    chat_messages = [{"role": "system", "content": system_prompt_with_context}]
    for message in history:
        if message["metadata"]["title"] != "Thinking":
            chat_messages.append(message)
    if user_message:
        chat_messages.append({"role": "user", "content": user_message})
    return {
        "model": assistant.llm,
        "messages": chat_messages,
        "options": {"num_ctx": assistant.context_limit},
    }


def build_prompt_code(
    history,
    user_message,
    file_reference,
    selected_assistant,
    options,
):
    assistant = fetch_assistant_by_name(selected_assistant)
    prompt = build_prompt(
        history,
        user_message,
        file_reference,
        selected_assistant,
        options,
    )
    markdown = f"# Assistant: {assistant.name}\n"
    markdown += f"## Model: {assistant.llm}\n"
    markdown += f"## Context limit: {assistant.context_limit}\n"
    markdown += "\n***\n\n"
    for message in prompt["messages"]:
        token_amount = len(tokenizer.encode(text=message["content"]))
        markdown += f"\n# (tokens: {token_amount}) {message["role"]}:\n{message["content"]}\n\n***\n\n"
    return markdown


def stream_chat(
    history,
    user_message,
    file_reference,
    selected_assistant,
    options,
):
    history = history or []  # Ensure history is not None
    prompt = build_prompt(
        history,
        user_message,
        file_reference,
        selected_assistant,
        options,
    )
    response = requests.post(
        os.getenv("LLM_CHAT_ENDPOINT"),
        json=prompt,
        stream=True,
    )
    response.raise_for_status()
    # Stream the response line by line
    bot_message = ""
    thinking = False
    first = True
    for line in response.iter_lines():
        if line:
            if first:
                first = False
                history.append(
                    {
                        "role": "user",
                        "content": user_message,
                        "metadata": {"title": None},
                    }
                )
            try:
                data = json.loads(line.decode("utf-8"))
                if (data["message"]["content"]) == "<think>":
                    thinking = True
                    continue
                if (data["message"]["content"]) == "</think>":
                    thinking = False
                    continue

                if thinking:
                    if history[-1]["metadata"]["title"] != "Thinking":
                        history.append(
                            {
                                "role": "assistant",
                                "content": bot_message,
                                "metadata": {"title": "Thinking"},
                            }
                        )
                    bot_message += data["message"]["content"]
                    history[-1]["content"] = bot_message
                else:
                    if (
                        history[-1]["role"] != "assistant"
                        or history[-1]["metadata"]["title"] == "Thinking"
                    ):
                        bot_message = ""
                        history.append(
                            {
                                "role": "assistant",
                                "content": bot_message,
                                "metadata": {"title": None},
                            }
                        )
                    bot_message += data["message"]["content"]
                    history[-1]["content"] = bot_message
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
    context_limit,
    options,
    selected_llm,
):
    if chatbot and len(chatbot) > 1:
        chatbot.pop()
        user_message = chatbot.pop()["content"]
        generator = stream_chat(
            chatbot,
            user_message,
            file_reference,
            context_limit,
            options,
            selected_llm,
        )
        for chat_history in generator:
            yield chat_history
    else:
        yield chatbot
