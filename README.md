Disclaimer: this app is not intended to serve any and all kind of project.
Currently, it supports itself and similar Python projects, as well as Node.js based Javascript and Typescript projects.

# Set up the LLM backend
```
brew install ollama
ollama run [model]
```

You have to install at least one model before the app will work.
You can escape with the command `/bye`, and after that the app will be able to run the model whenever.

Example models that run at reasonable speed on laptops:
- devstral:24b (Coding-oriented, not as good for chatting.)
- qwen2.5-coder:32b (Similar idea to devstral but older and heavier.)
- gemma3:27b (Similar footprint to devstral, but generalist chatting model)
- qwen3:14b (Also generalist, but reasoning. Lower memory need, less knowledge, comparable speed.)
- qwen3:30b-a3b (Similar to qwen3:14b. Faster in exchange for more memory.)

# Set up and run the project
First, navigate to project root.

```
brew install python
brew install pipx
pipx ensurepath
brew install poetry
poetry install
poetry run python query.py [project path] [source directory path]
```

Then click "Ingest code" to initialize the data.

Project path example: `/Users/test/Documents/project-name`

Source directory path example: "src"
