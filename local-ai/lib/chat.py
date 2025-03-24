import json
import os
import tiktoken
import sys
import ollama
from lib.db import (
    fetch_snippets_by_source,
    fetch_snippet_by_id,
    fetch_assistant_by_name,
    upsert_message,
    fetch_snippet_dependencies,
)
from lib.context import get_git_tracked_files, get_project_dependencies
from lib.assistants import get_assistant_prompt
from gradio import ChatMessage
from dataclasses import asdict

tokenizer = tiktoken.encoding_for_model("gpt-4o")
directory = os.path.abspath(sys.argv[1])


def sort_snippets(context_snippets):
    files = list({s.source for s in context_snippets})
    if not files:
        sorted_files = []
    else:
        # Build adjacency list and in_degree for topological sort
        adj = {file: [] for file in files}
        in_degree = {file: 0 for file in files}

        snippets_by_id = {snippet.id: snippet for snippet in context_snippets}
        dependencies = fetch_snippet_dependencies(context_snippets)

        # Process dependencies between files
        for dependency in dependencies:
            from_snippet = snippets_by_id[dependency.snippet_id]
            dep_snippet = snippets_by_id.get(dependency.dependency_name)
            if not dep_snippet:
                continue
            from_file = from_snippet.source
            dep_file = dep_snippet.source

            if from_file != dep_file:
                # Add edge from dependency file to dependent file (dep_file → from_file)
                adj[dep_file].append(from_file)
                in_degree[from_file] += 1

        # Perform Kahn's algorithm for topological sort
        from collections import deque

        queue = deque()
        for file in files:
            if in_degree[file] == 0:
                queue.append(file)

        sorted_files = []
        temp_in_degree = in_degree.copy()
        while queue:
            u = queue.popleft()
            sorted_files.append(u)
            for v in adj[u]:
                temp_in_degree[v] -= 1
                if temp_in_degree[v] == 0:
                    queue.append(v)

        # Handle cycles by appending remaining files alphabetically
        if len(sorted_files) < len(files):
            remaining = [f for f in files if f not in sorted_files]
            remaining_sorted = sorted(remaining)
            sorted_files += remaining_sorted

    # Create priority mapping
    file_priority = {f: idx for idx, f in enumerate(sorted_files)}

    # Sort snippets by file priority and line number
    context_snippets.sort(
        key=lambda s: (
            file_priority[s.source],  # File priority from dependency graph
            s.start_line,  # Line number within file
        )
    )
    return context_snippets


def build_prompt(
    history,
    user_message,
    file_reference,
    selected_assistant,
    options,
):
    assistant = fetch_assistant_by_name(selected_assistant)
    history = [
        ChatMessage(**message) for message in history or []
    ]  # Ensure history is not None
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

    for snippet_id in set(file_reference):
        context_snippets.append(fetch_snippet_by_id(snippet_id))

    if context_snippets:
        context_snippets = sort_snippets(context_snippets)
        context_prompt += (
            f"\n# Relevant snippets of project code denoted in Markdown:\n\n"
        )
        current_source = ""
        for snippet in context_snippets:
            if snippet.source != current_source:
                if current_source:
                    context_prompt += "```\n\n"
                context_prompt += f"## {snippet.source}:\n```\n"
                current_source = snippet.source
            else:
                context_prompt += "\n"
            context_prompt += f"{snippet.content}\n"
        context_prompt += "```"

    user_prompt_len = len(tokenizer.encode(user_message))
    context_prompt_len = len(tokenizer.encode(context_prompt))
    system_prompt_with_context = get_assistant_prompt()
    system_tokens = (
        len(tokenizer.encode(text=system_prompt_with_context)) + context_prompt_len
    )

    chat_messages = []
    tokens_used = 0
    if user_message:
        chat_messages.append(ChatMessage("user", user_message, metadata=dict()))
        tokens_used += len(tokenizer.encode(user_message))
    if context_prompt:
        chat_messages.append(ChatMessage("system", context_prompt, metadata=dict()))
    for message in reversed(history):
        message_length = len(tokenizer.encode(message.content))
        if (
            tokens_used + message_length <= assistant.context_limit
            and message.metadata["title"] != "Thinking"
        ):
            chat_messages.append(message)
            tokens_used += message_length
        elif tokens_used + message_length > assistant.context_limit:
            break

    chat_messages.append(
        ChatMessage("system", system_prompt_with_context, metadata=dict())
    )
    chat_messages = list(reversed(chat_messages))
    return {
        "model": assistant.llm,
        "messages": chat_messages,
        "options": {
            "num_ctx": max(
                system_tokens + assistant.context_limit,
                assistant.response_size_limit + context_prompt_len + user_prompt_len,
            ),
            "num_predict": assistant.response_size_limit,
        },
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
    system_message_tokens = [
        len(tokenizer.encode(message.content))
        for message in prompt["messages"]
        if message.role == "system"
    ]
    system_prompt_len = sum(system_message_tokens)
    markdown = f"# Assistant: {assistant.name}\n"
    markdown += f"## Model: {assistant.llm}\n"
    markdown += f"## Context limit: {assistant.context_limit} + {system_prompt_len}\n"
    markdown += f"## Response size limit: {assistant.response_size_limit}\n\n"
    markdown += "\n***\n\n"
    for message in prompt["messages"]:
        token_amount = len(tokenizer.encode(text=message.content))
        markdown += f"\n# (tokens: {token_amount}) {message.role}:\n{message.content}\n\n***\n\n"
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
    assistant = fetch_assistant_by_name(selected_assistant)
    stream = ollama.chat(
        model=assistant.llm,
        messages=[asdict(message) for message in prompt["messages"]],
        options=prompt["options"],
        stream=True,
    )
    # Stream the response line by line
    bot_message = ""
    thinking = False
    first = True
    for data in stream:
        if first:
            first = False
            new_message = ChatMessage("user", user_message, dict())
            history.append(new_message)
            upsert_message(new_message, len(history))
        if (data["message"]["content"]) == "<think>":
            thinking = True
            continue
        if (data["message"]["content"]) == "</think>":
            thinking = False
            continue

        if thinking:
            if dict.get(history[-1].metadata, "title") != "Thinking":
                new_message = ChatMessage(
                    "assistant",
                    bot_message,
                    {"title": "Thinking"},
                )
                history.append(new_message)
                upsert_message(new_message, len(history))
            bot_message += data["message"]["content"]
            history[-1].content = bot_message
        else:
            if (
                history[-1].role != "assistant"
                or dict.get(history[-1].metadata, "title") == "Thinking"
            ):
                bot_message = ""
                new_message = ChatMessage("assistant", bot_message, dict())
                history.append(new_message)
                upsert_message(new_message, len(history))
            bot_message += data["message"]["content"]
            history[-1].content = bot_message
            upsert_message(history[-1], len(history))
        yield history
        if data.get("done"):
            break


def delete_message(chatbot):
    if chatbot and len(chatbot) > 0:
        chatbot.pop()  # Remove the last message from the history
    return chatbot


def retry_last_message(
    chatbot,
    file_reference,
    selected_assistant,
    options,
):
    if chatbot and len(chatbot) > 1:
        chatbot.pop()
        user_message = chatbot.pop()["content"]
        generator = stream_chat(
            chatbot,
            user_message,
            file_reference,
            selected_assistant,
            options,
        )
        for chat_history in generator:
            yield chat_history
    else:
        yield chatbot
