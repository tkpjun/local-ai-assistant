import gradio as gr
import sys
import os
from dotenv import load_dotenv
import tiktoken
from typing import List
from lib.ollama import (
    get_ollama_model_names,
)
from lib.db import (
    fetch_snippets_by_directory,
    init_sqlite_tables,
    fetch_dependencies,
    fetch_dependents,
    clear_chat_history,
    load_chat_history,
    fetch_ui_state,
    upsert_ui_state,
)
from lib.ingest import ingest_codebase, start_watcher
from lib.chat import (
    stream_chat,
    delete_message,
    build_prompt,
    build_prompt_code,
    retry_last_message,
)
from lib.assistants import (
    update_prompt,
    get_all_assistants,
    update_llm,
    update_context_limit,
    update_response_limit,
    add_assistant,
)
from lib.types import UIState

load_dotenv(override=False)

tokenizer = tiktoken.encoding_for_model("gpt-4o")
directory = os.path.abspath(sys.argv[1])
source_directory = sys.argv[2]

installed_llms = get_ollama_model_names()
last_file_reference_value = []


init_sqlite_tables()
initial_history = load_chat_history()
initial_ui_state = fetch_ui_state() or UIState("Coder")

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
                    autoscroll=True,
                )
                user_input = gr.Textbox(
                    show_label=False,
                    placeholder="Type your question here...",
                    submit_btn="Send",
                )
            with gr.Tab("Assistants"):

                @gr.render(triggers=[new_name.submit, chat_interface.load])
                def generate_assistants():
                    for assistant in get_all_assistants():
                        with gr.Accordion(assistant.name, open=not assistant.llm):
                            with gr.Row():
                                llm_selector = gr.Dropdown(
                                    label=f"Assistant model",
                                    choices=installed_llms,
                                    value=assistant.llm,
                                    elem_id=f"llm_{assistant.name}",
                                )
                                context_limit_input = gr.Number(
                                    label=f"Chat history limit in tokens",
                                    value=assistant.context_limit,
                                    precision=0,
                                    elem_id=f"context_limit_{assistant.name}",
                                )
                                response_limit_input = gr.Number(
                                    label=f"Response limit in tokens",
                                    value=assistant.response_size_limit,
                                    precision=0,
                                    elem_id=f"response_limit_{assistant.name}",
                                )
                            prompt_input = gr.Textbox(
                                label=f"Context length: {len(tokenizer.encode(assistant.prompt))} tokens",
                                value=assistant.prompt,
                                lines=12,
                                max_lines=30,
                                elem_id=f"prompt_{assistant.name}",
                                submit_btn="Save",
                            )
                            # Save button callback
                            prompt_input.submit(
                                lambda pn=prompt_input, n=assistant.name: update_prompt(
                                    n, pn
                                ),
                                inputs=[prompt_input],
                                outputs=None,
                            )
                            prompt_input.submit(
                                lambda ln=llm_selector, n=assistant.name: update_llm(
                                    n, ln
                                ),
                                inputs=[llm_selector],
                                outputs=None,
                            )
                            prompt_input.submit(
                                lambda cl=context_limit_input, n=assistant.name: update_context_limit(
                                    n, int(cl)
                                ),
                                inputs=[context_limit_input],
                                outputs=None,
                            )
                            prompt_input.submit(
                                lambda cl=response_limit_input, n=assistant.name: update_response_limit(
                                    n, int(cl)
                                ),
                                inputs=[response_limit_input],
                                outputs=None,
                            )

                new_name.render()
                # TODO update assistant selector
                new_name.submit(add_assistant, inputs=[new_name], outputs=None)
            with gr.Tab(label="Prompt (JSON)"):
                prompt_box = gr.Json()
                build_prompt_button = gr.Button("Generate")
            with gr.Tab(label="Prompt (Markdown)"):
                prompt_md_box = gr.Markdown()
                build_prompt_md_button = gr.Button("Generate")
        with gr.Column(scale=1, min_width=400):
            with gr.Accordion("General", open=True):
                assistants = get_all_assistants()
                assistant_ids = [assistant.name for assistant in assistants]
                assistant_selector = gr.Dropdown(
                    label="Selected assistant",
                    choices=assistant_ids,
                    value=initial_ui_state.assistant_name,
                )
                options = gr.CheckboxGroup(
                    choices=["Project dependencies", "File structure"],
                    label="Embed extra context",
                    value=initial_ui_state.extra_content_options,
                )
            with gr.Accordion("Snippets"):
                file_reference = gr.Dropdown(
                    label="Select snippet by module",
                    choices=[
                        snippet.id for snippet in fetch_snippets_by_directory(directory)
                    ],
                    value=initial_ui_state.selected_snippets,
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
            file_reference += [
                dependency.dependency_name for dependency in dependencies
            ]
            file_reference += added
        if len(added) and file_options == "Dependents":
            dependents = fetch_dependents(added[0])
            file_reference += [dependency.snippet_id for dependency in dependents]
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
            assistant_selector,
            options,
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
            assistant_selector,
            options,
        ],
        chatbot,
    )
    build_prompt_button.click(
        build_prompt,
        inputs=[
            chatbot,
            user_input,
            file_reference,
            assistant_selector,
            options,
        ],
        outputs=prompt_box,
    )
    build_prompt_md_button.click(
        build_prompt_code,
        inputs=[
            chatbot,
            user_input,
            file_reference,
            assistant_selector,
            options,
        ],
        outputs=prompt_md_box,
    )

    def update_snippets():
        return gr.update(
            choices=[snippet.id for snippet in fetch_snippets_by_directory(directory)]
        )

    file_reference.focus(update_snippets, outputs=[file_reference])

    def click_ingest():
        ingest_codebase(directory, source_directory)
        return update_snippets()

    ingest_button.click(click_ingest, outputs=[file_reference])

    clear_button.click(clear_chat_history)

    def save_ui_state(assistant_name, extra_content_options, selected_snippets):
        ui_state = UIState(
            assistant_name=assistant_name,
            extra_content_options=list(extra_content_options),
            selected_snippets=list(selected_snippets),
        )
        upsert_ui_state(ui_state)

    # Update assistant selector
    assistant_selector.change(
        fn=save_ui_state,
        inputs=[assistant_selector, options, file_reference],
        outputs=None,
    )

    # Update options checkbox
    options.change(
        fn=save_ui_state,
        inputs=[assistant_selector, options, file_reference],
        outputs=None,
    )

    # Update file reference dropdown
    file_reference.change(
        fn=save_ui_state,
        inputs=[assistant_selector, options, file_reference],
        outputs=None,
    )

start_watcher(directory, source_directory)
# Launch the Gradio app
chat_interface.launch()
