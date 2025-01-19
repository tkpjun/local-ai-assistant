import json

import gradio as gr
import requests
from langchain.vectorstores import Qdrant
from qdrant_client import QdrantClient
from lib.aggregating import get_dependencies, snippet_to_prompt

from lib.embeddings import OllamaEmbeddings
import sqlite3

# Connect to SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect("../codebase.db", check_same_thread=False)
cursor = conn.cursor()

# Initialize Qdrant client
qdrant_client = QdrantClient("http://localhost:6333")

# Initialize vectorstore with Ollama embeddings
embeddings = OllamaEmbeddings()
vectorstore = Qdrant(client=qdrant_client, collection_name="codebase", embeddings=embeddings)

def fetch_context_from_vector_store(search_context: str, context_cutoff: int):
    mmr_retriever = vectorstore.as_retriever(search_type="mmr", search_kwargs={"k": 3, "lambda_mult": 0.25})
    basic_retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 3})
    relevant_docs = mmr_retriever.invoke(search_context)
    context_applied = 0
    context = ""
    context += "Context from codebase:\n\n"
    while context_applied < context_cutoff:
        context_batch = ""
        metadata_batch = ""
        for doc in relevant_docs:
            context_batch += f"{doc.page_content}\n\n"
            metadata_batch += f"{doc.metadata}\n"
            context_applied += len(doc.page_content)
        context += context_batch
        if context_applied < context_cutoff:
            context_batch += metadata_batch
            relevant_docs = basic_retriever.invoke(context_batch)
    return context

def stream_chat(history, user_message, file_reference, include_dependencies, file_reference_2, include_dependencies_2, history_cutoff, context_cutoff):
    history = history or []  # Ensure history is not None
    prompt = ""

    if include_dependencies or include_dependencies_2:
        dependencies = []
        if include_dependencies:
            dependencies += get_dependencies(file_reference, context_cutoff)
        if include_dependencies_2:
            dependencies += get_dependencies(file_reference_2, context_cutoff)
        dependencies = list(dict.fromkeys(dependencies))
        prompt += f"Code file with dependencies denoted in Markdown:\n{"".join(dependencies)}\n"
    if file_reference is not None:
        cursor.execute("SELECT source, content FROM snippets WHERE id = ?", (file_reference,))
        snippet = cursor.fetchone()
        prompt += snippet_to_prompt(snippet[0], snippet[1])
    if file_reference_2 is not None:
        cursor.execute("SELECT source, content FROM snippets WHERE id = ?", (file_reference_2,))
        snippet = cursor.fetchone()
        prompt += snippet_to_prompt(snippet[0], snippet[1])

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

    # Chatbot component
    chatbot = gr.Chatbot(elem_id="chatbot")
    with gr.Row():
        with gr.Column():  # Note the parentheses here
            file_reference = gr.Dropdown(label="Select File Path", choices=file_paths, value=None, allow_custom_value=True)
            include_dependencies = gr.Checkbox(label="Include Dependencies", value=False)
        with gr.Column():  # Note the parentheses here
            file_reference_2 = gr.Dropdown(label="Select File Path", choices=file_paths, value=None, allow_custom_value=True)
            include_dependencies_2 = gr.Checkbox(label="Include Dependencies", value=False)
        with gr.Column():
            history_cutoff = gr.Number(label="History Cutoff (max length)", value=10000, precision=0)
            context_cutoff = gr.Number(label="Context Cutoff (max length)", value=10000, precision=0)
    user_input = gr.Textbox(placeholder="Type your question here...", label="Your Message")

    # Handle user input and display the streaming response
    user_input.submit(fn=stream_chat, inputs=[chatbot, user_input, file_reference, include_dependencies, file_reference_2, include_dependencies_2, history_cutoff, context_cutoff], outputs=chatbot)

# Launch the Gradio app
chat_interface.launch()