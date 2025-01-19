# Set up the LLM backend
brew install ollama
ollama run qwen2.5-coder:32b

# Set up QDrant (optional):
brew install podman
podman machine init
podman machine start
podman pull qdrant/qdrant
podman run -p 6333:6333 qdrant/qdrant

# Set up and run the project
brew install python
brew install pipx
pipx ensurepath
brew install poetry
poetry install
poetry run python ingest.py
poetry run python query.py