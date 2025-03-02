from langchain.schema import Document
from langchain_community.vectorstores import Qdrant
from qdrant_client import QdrantClient
from qdrant_client.http import models
from lib.ollama import OllamaEmbeddings
from dotenv import load_dotenv
import os

load_dotenv(override=False)

config = {
    "enabled": os.getenv("QDRANT_ENABLED") == "True",
    "qdrant_url": os.getenv("QDRANT_URL"),
    "embeddings_model": OllamaEmbeddings,
}

qdrant_client = None
vectorstore = None
retriever = None


def initialize_database():
    set_up_connection()
    qdrant_client.recreate_collection(
        collection_name="codebase",
        vectors_config=models.VectorParams(size=5120, distance=models.Distance.COSINE),
    )


def set_up_connection():
    if qdrant_client is not None:
        return
    qdrant_client = QdrantClient(config["qdrant_url"])
    embeddings = config["embeddings_model"]()
    vectorstore = Qdrant(
        client=qdrant_client, collection_name="codebase", embeddings=embeddings
    )


def insert_snippets(snippets):
    if not config["enabled"]:
        return
    if qdrant_client is None:
        set_up_connection()

    documents = []
    for filepath, identifier, content in snippets:
        documents.append(
            Document(
                page_content=content,
                metadata={"source": filepath, "identifier": identifier},
            )
        )
    vectorstore.add_documents(documents)


def fetch_context_data(context, cutoff):
    if not config["enabled"]:
        return []
    if qdrant_client is None:
        set_up_connection()
    if retriever is None:
        basic_retriever = vectorstore.as_retriever(
            search_type="similarity", search_kwargs={"k": 3}
        )
    relevant_docs = basic_retriever.invoke(context)
    context_applied = 0
    context = "Context from codebase:\n\n"

    while context_applied < cutoff:
        context_batch = ""
        metadata_batch = ""
        if len(relevant_docs) == 0:
            break
        for doc in relevant_docs:
            context_batch += f"{doc.page_content}\n\n"
            metadata_batch += f"{doc.metadata}\n"
            context_applied += len(doc.page_content)
        context += context_batch
        if context_applied < cutoff:
            context_batch += metadata_batch
            relevant_docs = retrieve_snippets(context_batch)
    return context
