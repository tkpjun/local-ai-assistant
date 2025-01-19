
import sys
import os

from langchain.schema import Document
from langchain_community.vectorstores import Qdrant
from qdrant_client import QdrantClient
from qdrant_client.http import models
from lib.chunking import chunk_python_code, chunk_react_code, chunk_json_file
from lib.processing import process_imports, get_git_tracked_files
from lib.log import log

from lib.embeddings import OllamaEmbeddings
from lib.db import init_sqlite_tables, upsert_snippet

config = {
    "qdrant_url": "http://localhost:6333",
    "embeddings_model": OllamaEmbeddings,
    "file_processors": {
        ".py": chunk_python_code,
        ".js": chunk_react_code,
        ".ts": chunk_react_code,
        ".tsx": chunk_react_code,
        ".json": chunk_json_file
    }
}

# TODO add more metadata
#  - imports referenced in snippet (or maybe add to the snippet itself)
#  - file name
#  - modules
#  - commit history

def read_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError as e:
        log.error(f'Failed to read file {filepath}: {e}')
    except Exception as e:
        log.error(f'An error occurred while reading file {filepath}: {e}')
    return None

def ingest_codebase(directory, source_directory):
    qdrant_client = QdrantClient(config["qdrant_url"])
    qdrant_client.recreate_collection(
        collection_name="codebase",
        vectors_config=models.VectorParams(size=5120, distance=models.Distance.COSINE),
    )
    embeddings = config["embeddings_model"]()
    vectorstore = Qdrant(client=qdrant_client, collection_name="codebase", embeddings=embeddings)

    filepaths = get_git_tracked_files(directory)
    for file in filepaths:
        documents = []
        filepath = directory + "/" + file
        local_file_path = filepath.removeprefix(f"{directory}/")
        modulepath = (local_file_path
                      .removeprefix(f"{source_directory}/")
                      .replace("/", "."))
        for ext in config["file_processors"]:
            if filepath.endswith(ext):
                modulepath = modulepath.removesuffix(ext)
                break

        log.info(f"Processing file: {filepath}")
        text = read_file(filepath)
        if text is None:
            continue

        processor = config["file_processors"].get(os.path.splitext(file)[1])
        if not processor:
            log.info(f"No processor found for file {filepath}. Skipping.")
            continue

        chunks = processor(text)

        log.info(f"Processing snippet: {modulepath}")
        upsert_snippet(modulepath, None, filepath, text, "file")
        process_imports(filepath, modulepath, None, text, text)

        for identifier, content in chunks:
            log.info(f"Processing snippet: {modulepath + '.' + identifier}")
            upsert_snippet(modulepath, identifier, filepath, content, "code")
            process_imports(filepath, modulepath, identifier, text, content)
            documents.append(Document(page_content=content, metadata={"source": filepath, "identifier": identifier}))

        vectorstore.add_documents(documents)

directory = sys.argv[1]
source_directory = sys.argv[2]
# Create tables
init_sqlite_tables(directory)
ingest_codebase(directory, source_directory)