# Projects

A **project** groups related chats and gives all of them shared context, like projects in ChatGPT or Claude. Use one when you keep coming back to the same piece of work: a codebase you ask questions about, a document you are drafting, a topic you are studying.

## What a project holds

| Part | What it does |
|---|---|
| **Instructions** | Text every chat in the project starts with ("Answer as a reviewer of Python code", "Reply in Hindi"). Up to 20,000 characters. They follow the global system prompt from Settings. |
| **Files** | Text files the model can use in every chat of the project. See below. |
| **Default model** | The model new chats in the project start with. You can still switch inside a chat. |
| **Chats** | The chats created in, or moved into, the project. They are listed under the project in the sidebar. |

## Using projects

1. In the sidebar, press **+** next to **Projects** and give the project a name (up to 80 characters).
2. Open the project. Write **Instructions** and press **Save instructions**. Add **Files** by dropping them on the drop zone or choosing them.
3. Press **New chat** inside the project. Its chats appear nested under the project in the sidebar. A breadcrumb above the chat shows which project you are in.
4. Move an existing chat in or out from its **⋯** menu (**Move to project**, **No project**, or **New project...**).
5. **Delete project** (at the bottom of the project page) deletes the project, its files **and its chats**.

## Project files

Studio gives a model **text only**. Files must be UTF-8 text (UTF-16 with a byte-order mark is also accepted): source code, Markdown, plain notes, CSV, JSON, logs.

| Limit | Value |
|---|---|
| Size of one file | 1 MB |
| All files in one project | 4 MB |
| Number of files | 100 |

PDF, Word, spreadsheets and other binary files are **refused** with an explanation. Studio does not convert them: converting a PDF to text silently loses tables and layout, so it is left to you (copy the text out, or export to `.txt` / `.md` first). Images are different: they go to vision models in the chat itself ([Images and Voice](Images-and-Voice)).

## How the context reaches the model

For every message in a project chat, Studio builds one system message:

1. the global **System prompt** from Settings (if any),
2. the project's **Instructions**,
3. a line naming the project, then each file as a `<file name="...">...</file>` block.

Then the conversation follows. Two rules keep it inside the model's **context length** (Settings, default 4096 tokens):

* The project block is cut to **about half of the context length**. A file that does not fit is truncated and marked `[...truncated to fit the context]`; files that no longer fit at all are listed as left out.
* When a long chat outgrows the rest of the context, the **oldest turns are dropped first**. Instructions and files are never dropped, and the newest message is always kept.

The project page shows an estimate of how many tokens its instructions and files take compared with the context length, and suggests raising the context length (in Settings) if the model supports more. A larger context uses more memory and is slower ([Models and Performance](Models-and-Performance)).

Tips:

* Keep instructions short and specific. Models follow a few clear rules better than a long essay.
* Small, relevant files beat many large ones. The model reads all of them for every message.
* With the default 4096-token context, only a few kilobytes of files fit. Raise the context length for real document work, and pick a model that supports it.

## Through the API

Projects are stored in the same database as chats (`chats.db`). The Studio API manages them (`/api/studio/projects`, see [API Reference](API-Reference)), and `/api/chat` accepts `"airllm_project": "<project id>"` to apply a project's instructions and files to a request from your own scripts.
