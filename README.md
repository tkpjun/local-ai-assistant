Disclaimer: this app is not intended to serve any and all kind of project.
Currently, it supports itself and similar Python projects, as well as Node.js based Javascript and Typescript projects.

# Set up the LLM backend
brew install ollama
ollama run [model].

You have to install at least one model before the app will work.
You can escape with the command /bye, and after that the app will be able to run the model whenever.

Example models:
- qwen2.5-coder:14b (basic, fast, lower memory consumption)
- qwen2.5-coder:32b (basic, medium speed, higher memory consumption)
- deepseek-R1:14b (chain-of-thought, medium speed, lower memory consumption)
- deepseek-R1:32b (chain-of-thought, slow, higher memory consumption)

# Set up QDrant (not necessary at the time):
brew install podman
podman machine init
podman machine start
podman pull qdrant/qdrant
podman run -p 6333:6333 qdrant/qdrant

# Set up and run the project
First, navigate to project root.

brew install python
brew install pipx
pipx ensurepath
brew install poetry
poetry install
poetry run python ingest.py [project path] [source directory path]
poetry run python query.py [project path]

Project path example: /Users/test/Documents/project-name
Source directory path example: "src"