from langchain.embeddings.base import Embeddings
import requests
from dotenv import load_dotenv
import os
import subprocess

load_dotenv(override=False)


def get_ollama_model_names():
    try:
        # Call `ollama list` and capture the output
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=True
        )
        # Extract lines of the output (skip the header line)
        lines = result.stdout.strip().split("\n")[1:]
        # Extract the model names (first column of each line)
        model_names = [line.split()[0] for line in lines if line]
        return model_names
    except subprocess.CalledProcessError as e:
        print(f"Error while running 'ollama list': {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []


def get_running_ollama_models():
    try:
        # Call `ollama ps` and capture the output
        result = subprocess.run(
            ["ollama", "ps"], capture_output=True, text=True, check=True
        )
        # Extract lines of the output (skip the header line)
        lines = result.stdout.strip().split("\n")[1:]
        # Extract model names and IDs (first and second columns)
        running_models = {}
        for line in lines:
            if line.strip():  # Skip empty lines
                parts = line.split()  # Split by whitespace
                model_name = parts[0]
                model_id = parts[1]
                running_models[model_name] = model_id

        return running_models
    except subprocess.CalledProcessError as e:
        print(f"Error while running 'ollama ps': {e}")
        return {}
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {}


def stop_ollama_model_by_name(name):
    try:
        # Call `ollama stop` with the model name
        subprocess.run(
            ["ollama", "stop", name], capture_output=True, text=True, check=True
        )
        return f"Successfully stopped model '{name}'."
    except subprocess.CalledProcessError as e:
        return f"Error stopping model '{name}': {e.stderr.strip()}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


def run_ollama_model_in_background(name):
    try:
        # Run `ollama run` in the background
        process = subprocess.Popen(
            ["ollama", "run", name],
            stdout=subprocess.PIPE,  # Redirect stdout
            stderr=subprocess.PIPE,  # Redirect stderr
            text=True,  # Decode output to strings
        )
        return f"Model '{name}' is running in the background (PID: {process.pid})."
    except Exception as e:
        return f"Failed to run model '{name}': {str(e)}"


# Custom Embeddings class to use Ollama
class OllamaEmbeddings(Embeddings):
    def __init__(self, model):
        self.model = model

    def _get_embedding(self, text):
        """Helper method to get embedding from Ollama."""
        response = requests.post(
            os.getenv("LLM_EMBED_ENDPOINT"),
            json={"model": self.model, "input": text},
        )
        response.raise_for_status()
        return response.json()["embeddings"][0]

    def embed_documents(self, texts):
        """Embed a list of documents."""
        return [self._get_embedding(text) for text in texts]

    def embed_query(self, text):
        """Embed a single query."""
        return self._get_embedding(text)
