import gradio as gr
import sys
from dotenv import load_dotenv
import tiktoken
from lib.ollama import (
    get_ollama_model_names,
)
from lib.db import (
    fetch_snippet_ids,
    init_sqlite_tables,
    fetch_dependencies,
    fetch_dependents,
    clear_chat_history,
    load_chat_history,
    save_chat_history,
)
from lib.ingest import ingest_codebase, start_watcher
from lib.chat import (
    stream_chat,
    delete_message,
    build_prompt,
    build_prompt_code,
    retry_last_message,
)
from lib.assistants import add_assistant, update_prompt, assistants

load_dotenv(override=False)

tokenizer = tiktoken.encoding_for_model("gpt-4o")
directory = sys.argv[1]
source_directory = sys.argv[2]

installed_llms = get_ollama_model_names()
snippet_ids = []
last_file_reference_value = []


def refresh_snippets():
    global snippet_ids
    snippet_ids = fetch_snippet_ids(directory)


init_sqlite_tables()
initial_history = load_chat_history()
refresh_snippets()

# New assistant input
new_name = gr.Textbox(
    show_label=False, placeholder="New assistant name", submit_btn="Add new assistant"
)

# Create a Gradio chat interface with streaming
with gr.Blocks(fill_height=True) as chat_interface:
    with gr.Row():
        with gr.Column(scale=2):
            with gr.Tab(label="Chat"):
                chatbot = gr.Chatbot(
                    elem_id="chatbot",
                    min_height=800,
                    editable="all",
                    type="messages",
                    value=initial_history,
                )
                user_input = gr.Textbox(
                    show_label=False,
                    placeholder="Type your question here...",
                    submit_btn="Send",
                )
                chatbot.change(fn=save_chat_history, inputs=chatbot, outputs=None)
            with gr.Tab("Assistants"):

                @gr.render(triggers=[new_name.submit, chat_interface.load])
                def generate_assistants():
                    for name, prompt in assistants:
                        with gr.Accordion(name, open=True):
                            prompt_input = gr.Textbox(
                                label=f"Context length: {len(tokenizer.encode(prompt))} tokens",
                                value=prompt,
                                lines=15,
                                max_lines=30,
                                elem_id=f"prompt_{name}",
                                submit_btn="Save",
                            )

                            # Save button callback
                            prompt_input.submit(
                                lambda pn=prompt_input, n=name: update_prompt(n, pn),
                                inputs=[prompt_input],
                                outputs=None,
                            )

                new_name.render()
                # Add button handler
                new_name.submit(add_assistant, inputs=[new_name], outputs=None)
            with gr.Tab(label="Prompt (JSON)"):
                prompt_box = gr.Json()
                build_prompt_button = gr.Button("Generate")
            with gr.Tab(label="Prompt (Markdown)"):
                prompt_md_box = gr.Markdown()
                build_prompt_md_button = gr.Button("Generate")
        with gr.Column(scale=1, min_width=400):
            with gr.Accordion("General", open=True):
                selected_llm = gr.Dropdown(
                    label="Selected LLM",
                    choices=installed_llms,
                    value=installed_llms[0],
                )
                assistant = gr.Dropdown(
                    label="Selected assistant", choices=["Coder"], value="Coder"
                )
                context_limit = gr.Number(
                    label="Context limit in tokens", value=8192, precision=0
                )
                options = gr.CheckboxGroup(
                    choices=["Project dependencies", "File structure"],
                    label="Embed extra context",
                )
            with gr.Accordion("Snippets"):
                file_reference = gr.Dropdown(
                    label="Select snippet by module",
                    choices=snippet_ids,
                    value=None,
                    allow_custom_value=True,
                    multiselect=True,
                )
                file_options = gr.Radio(
                    choices=["Snippet", "Dependencies", "Dependents"],
                    value="Snippet",
                    label="Include",
                )
            with gr.Row():
                retry_button = gr.Button("Retry response", size="md")
                delete_button = gr.Button("Delete message", size="md")
                clear_button = gr.ClearButton(
                    [user_input, chatbot],
                    value="Clear history",
                    size="md",
                    variant="stop",
                )
                ingest_button = gr.Button("Ingest code", size="md")

    def on_snippet_input(file_reference, file_options):
        global last_file_reference_value
        added = [
            item for item in file_reference if item not in last_file_reference_value
        ]
        if len(added) and file_options == "Dependencies":
            # TODO should get internal dependencies (same file) recursively
            dependencies = fetch_dependencies(added[0])
            file_reference.pop()
            file_reference += [item for item in dependencies]
            file_reference += added
        if len(added) and file_options == "Dependents":
            dependents = fetch_dependents(added[0])
            file_reference += [item for item in dependents]
        last_file_reference_value = file_reference
        return gr.update(value=file_reference)

    file_reference.input(
        fn=on_snippet_input,
        inputs=[file_reference, file_options],
        outputs=[file_reference],
    )

    # Handle user input and display the streaming response
    user_input.submit(
        fn=stream_chat,
        inputs=[
            chatbot,
            user_input,
            file_reference,
            context_limit,
            options,
            selected_llm,
        ],
        outputs=chatbot,
    )
    user_input.submit(lambda x: gr.update(value=""), None, [user_input], queue=False)
    delete_button.click(delete_message, [chatbot], chatbot)
    retry_button.click(
        retry_last_message,
        [
            chatbot,
            file_reference,
            context_limit,
            options,
            selected_llm,
        ],
        chatbot,
    )
    build_prompt_button.click(
        build_prompt,
        inputs=[
            chatbot,
            user_input,
            file_reference,
            context_limit,
            options,
            selected_llm,
        ],
        outputs=prompt_box,
    )
    build_prompt_md_button.click(
        build_prompt_code,
        inputs=[
            chatbot,
            user_input,
            file_reference,
            context_limit,
            options,
            selected_llm,
        ],
        outputs=prompt_md_box,
    )

    def update_snippets():
        refresh_snippets()
        return gr.update(choices=snippet_ids)

    file_reference.focus(update_snippets, outputs=[file_reference])

    def click_ingest():
        ingest_codebase(directory, source_directory)
        return update_snippets()

    ingest_button.click(click_ingest, outputs=[file_reference])

    clear_button.click(clear_chat_history)

start_watcher(directory, source_directory)
# Launch the Gradio app
chat_interface.launch()
