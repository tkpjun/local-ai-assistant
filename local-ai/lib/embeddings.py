from langchain.embeddings.base import Embeddings
import requests

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
