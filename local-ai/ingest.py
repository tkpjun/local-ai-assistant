
import sys

from langchain.schema import Document
from langchain_community.vectorstores import Qdrant
from qdrant_client import QdrantClient
from qdrant_client.http import models
from lib.chunking import chunk_python_code
from lib.chunking import chunk_react_code
from lib.chunking import chunk_json_file
from lib.processing import process_imports, get_git_tracked_files

from lib.ollama import OllamaEmbeddings
from lib.db import init_sqlite_tables, upsert_snippet

# Create tables
init_sqlite_tables()

# TODO add more metadata
#  - imports referenced in snippet (or maybe add to the snippet itself)
#  - file name
#  - modules
#  - commit history

# Initialize Qdrant client
qdrant_client = QdrantClient("http://localhost:6333")

qdrant_client.recreate_collection(
    collection_name="codebase",
    vectors_config=models.VectorParams(size=5120, distance=models.Distance.COSINE),
)

embeddings = OllamaEmbeddings()
vectorstore = Qdrant(client=qdrant_client, collection_name="codebase", embeddings=embeddings)

# Function to ingest the codebase
def ingest_codebase(directory, source_directory):
    filepaths = get_git_tracked_files(directory)
    for file in filepaths:
        documents = []
        filepath = directory + "/" + file
        local_file_path = filepath.removeprefix(f"{directory}/")
        modulepath = (local_file_path
                      .removeprefix(f"{source_directory}/")
                      .replace("/", ".")
                      .removesuffix(".py")
                      .removesuffix(".ts")
                      .removesuffix(".tsx")
                      .removesuffix(".js"))
        print(filepath)
        try:
            with open(filepath, "r") as f:
                text = f.read()
        except:
            print('Failed to read file')
            continue

        if file.endswith(".py"):
            chunks = chunk_python_code(text)
        elif file.endswith((".js", ".ts", ".tsx")):
            chunks = chunk_react_code(text)
        elif file.endswith(".json"):
            chunks = chunk_json_file(text)
        else:
            continue

        print(modulepath)
        upsert_snippet(modulepath, None, filepath, text, "file")
        process_imports(filepath, modulepath, None, text, text)

        for identifier, content in chunks:
            # Insert snippet into the database
            print(modulepath + '.' + identifier)
            upsert_snippet(modulepath, identifier, filepath, content, "code")
            process_imports(filepath, modulepath, identifier, text, content)
            documents.append(Document(page_content=content, metadata={"source": filepath, "identifier": identifier}))
        # Add the documents to your vector store
        vectorstore.add_documents(documents)
    #cursor.execute("SELECT * FROM dependencies")
    #print(cursor.fetchall())

# Ingest your codebase
directory = sys.argv[1]
source_directory = sys.argv[2]
ingest_codebase(directory, source_directory)