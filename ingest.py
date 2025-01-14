import os
from langchain_community.vectorstores import Qdrant
from langchain.embeddings.base import Embeddings
from qdrant_client import QdrantClient
import requests
from qdrant_client.http import models
import re
import json
from langchain.schema import Document
import sqlite3
import subprocess
import sys


EXCLUDED_DIRS = {"node_modules", ".git", "dist", "build", ".webpack", ".serverless", ".idea", ".iml"}

# Connect to SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect("codebase.db")
cursor = conn.cursor()

# Create tables
cursor.execute("""
CREATE TABLE IF NOT EXISTS snippets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    identifier TEXT UNIQUE,
    content TEXT,
    type TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snippet_id INTEGER,
    dependency_id INTEGER,
    FOREIGN KEY (snippet_id) REFERENCES snippets (id),
    FOREIGN KEY (dependency_id) REFERENCES snippets (id)
)
""")

# Commit changes
conn.commit()

# TODO add more metadata
#  - imports referenced in snippet (or maybe add to the snippet itself)
#  - file name
#  - modules
#  - commit history

def get_git_tracked_files(root_dir):
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=root_dir,
        capture_output=True,
        text=True
    )
    return result.stdout.splitlines()

def chunk_python_code(text):
    # Regex to match function and class definitions
    pattern = r"(\bdef\s+\w+\(.*?\):|\bclass\s+\w+\(?.*?\)?:)"
    matches = [m.start() for m in re.finditer(pattern, text)]

    chunks = []
    for i, start in enumerate(matches):
        end = matches[i + 1] if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()

        # Extract identifier (class or function name)
        identifier_match = re.search(r"(class|def)\s+(\w+)", chunk)
        identifier = identifier_match.group(2) if identifier_match else None

        chunks.append((identifier, chunk))

    return chunks

# Chunker for React and JS/TS files
def chunk_react_code(text):
    pattern = r"(export\s+(?:default\s+)?(?:function|class)\s+\w+|\bfunction\s+\w+|\bclass\s+\w+)"
    matches = [m.start() for m in re.finditer(pattern, text)]

    chunks = []
    for i, start in enumerate(matches):
        end = matches[i + 1] if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        identifier = chunk.split()[1]  # Extract function or class name
        chunks.append((identifier, chunk))

    return chunks

# Chunker for JSON files
def chunk_json_file(text):
    data = json.load(text)
    chunks = []
    if isinstance(data, dict):
        for key, value in data.items():
            chunks.append(json.dumps({key: value}, indent=2))
    elif isinstance(data, list):
        for item in data:
            chunks.append(json.dumps(item, indent=2))

    return chunks

# Function to process imports and store dependencies
def process_imports(filepath, content):
    imports = re.findall(r'import\s+.*?from\s+["\'](.*?)["\']', content)
    for imp in imports:
        cursor.execute("SELECT id FROM snippets WHERE identifier = ?", (imp,))
        dependency = cursor.fetchone()
        if dependency:
            cursor.execute("INSERT OR REPLACE INTO dependencies (snippet_id, dependency_id) VALUES (?, ?)", (filepath, dependency[0]))

# Custom Embeddings class to use Ollama
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

qdrant_client.recreate_collection(
    collection_name="codebase",
    vectors_config=models.VectorParams(size=5120, distance=models.Distance.COSINE),
)

embeddings = OllamaEmbeddings()
vectorstore = Qdrant(client=qdrant_client, collection_name="codebase", embeddings=embeddings)

# Function to ingest the codebase
def ingest_codebase(directory):
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        documents = []

        for file in files:
            filepath = os.path.join(root, file)
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

            cursor.execute("""
                    INSERT OR REPLACE INTO snippets (source, identifier, content, type)
                    VALUES (?, ?, ?, ?)
                """, (filepath, filepath, text, "file"))
            process_imports(filepath, text)

            for identifier, content in chunks:
                # Insert snippet into the database
                cursor.execute("""
                    INSERT OR REPLACE INTO snippets (source, identifier, content, type)
                    VALUES (?, ?, ?, ?)
                """, (filepath, identifier, content, "code"))
                process_imports(filepath, content)
                documents.append(Document(page_content=content, metadata={"source": filepath, "identifier": identifier}))
            # Add the documents to your vector store
            vectorstore.add_documents(documents)

    conn.commit()

# Ingest your codebase
filepath = sys.argv[1]
ingest_codebase(filepath)