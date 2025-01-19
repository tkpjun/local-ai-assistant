from langchain.schema import Document
from langchain_community.vectorstores import Qdrant
from qdrant_client import QdrantClient
from qdrant_client.http import models
from lib.embeddings import OllamaEmbeddings

config = {
    "enabled": False,
    "qdrant_url": "http://localhost:6333",
    "embeddings_model": OllamaEmbeddings,
}

qdrant_client = None
vectorstore = None

def initialize_database():
    set_up_connection()
    qdrant_client.recreate_collection(
        collection_name="codebase",
        vectors_config=models.VectorParams(size=5120, distance=models.Distance.COSINE),
    )

def set_up_connection():
    if qdrant_client != None:
        return
    qdrant_client = QdrantClient(config["qdrant_url"])
    embeddings = config["embeddings_model"]()
    vectorstore = Qdrant(client=qdrant_client, collection_name="codebase", embeddings=embeddings)

def insert_snippets(snippets):
    if not config["enabled"]:
        return

    documents = []
    for (filepath, identifier, content) in snippets:
        documents.append(Document(page_content=content, metadata={"source": filepath, "identifier": identifier}))
    vectorstore.add_documents(documents)