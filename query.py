import os
from langchain.document_loaders import TextLoader
from langchain.vectorstores import Qdrant
from langchain.embeddings.base import Embeddings
from langchain.chains import RetrievalQA
from qdrant_client import QdrantClient
import requests
import json
import sys
from rich.console import Console
from rich.markdown import Markdown
import gradio as gr

console = Console()

# Custom embeddings class to use Ollama for embeddings
class OllamaEmbeddings(Embeddings):
    def _get_embedding(self, text):
        """Helper method to get embedding from Ollama."""
        response = requests.post(
            "http://localhost:11434/api/embed",
            json={"model": "qwen2.5-coder:32b", "input": text},
        )
        response.raise_for_status()
        return response.json()["embeddings"][0]

    def embed_documents(self, texts):
        """Embed a list of documents."""
        return [self._get_embedding(text) for text in texts]

    def embed_query(self, text):
        """Embed a single query."""
        return self._get_embedding(text)

# Initialize Qdrant client
qdrant_client = QdrantClient("http://localhost:6333")

# Initialize vectorstore with Ollama embeddings
embeddings = OllamaEmbeddings()
vectorstore = Qdrant(client=qdrant_client, collection_name="codebase", embeddings=embeddings)

def stream_chat(history, user_message):
    history = history or []  # Ensure history is not None
    history_cutoff = 10000
    context_cutoff = 50000
    prompt = ""

    #search_context = user_message
    #if (len(history) > 0):
    #    search_context += "\n\n"
    #    search_context += history[-1][1]
    #    search_context += "\n\n"
    #    search_context += history[-1][0]
    #mmr_retriever = vectorstore.as_retriever(search_type="mmr", search_kwargs={"k": 3, "lambda_mult": 0.25})
    #basic_retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 3})
    #relevant_docs = mmr_retriever.invoke(search_context)
    #context_applied = 0
    #prompt += "Context from codebase:\n\n"
    #while context_applied < context_cutoff:
    #    context_batch = ""
    #    metadata_batch = ""
    #    for doc in relevant_docs:
    #        context_batch += doc.page_content
    #        context_batch += "\n\n"
    #        metadata_batch += doc.metadata
    #        metadata_batch += "\n"
    #        context_applied += len(doc.page_content)
    #    prompt += context_batch
    #    if context_applied < context_cutoff:
    #        context_batch += metadata_batch
    #        relevant_docs = basic_retriever.invoke(context_batch)

    history_applied = 0
    history_index = -1
    prompt += "Chat history:\n\n"
    while history_applied < history_cutoff and len(history) >= -history_index:
        prompt += "User:\n"
        prompt += history[history_index][0]
        history_applied += len(history[history_index][0])
        prompt += "You:\n"
        prompt += history[history_index][1]
        history_applied += len(history[history_index][1])
        history_index -= 1
    history.append((user_message, ""))

    prompt += "User:\n"
    prompt += user_message

    print(prompt)

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

# Custom CSS for full-height chat interface
css = """
#chatbot {
    height: calc(100vh - 200px) !important;
}
"""

# Create a Gradio chat interface with streaming
with gr.Blocks(css=css) as chat_interface:
    gr.Markdown("## 💬 Chat with Your Local LLM (Ollama)")

    # Chatbot component
    chatbot = gr.Chatbot(elem_id="chatbot")
    user_input = gr.Textbox(placeholder="Type your question here...", label="Your Message")

    # Handle user input and display the streaming response
    user_input.submit(fn=stream_chat, inputs=[chatbot, user_input], outputs=chatbot)

# Launch the Gradio app
chat_interface.launch()