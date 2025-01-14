brew install ollama
ollama run qwen2.5-coder:32b

brew install podman
podman machine init
podman machine start
podman pull qdrant/qdrant
podman run -p 6333:6333 qdrant/qdrant

brew install python
brew install pipx
pipx ensurepath
brew install poetry
poetry install
poetry run python ingest.py
poetry run python query.py