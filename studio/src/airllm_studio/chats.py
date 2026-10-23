"""Conversation history and projects, stored server-side in SQLite so every window sees the same data.

A project groups chats and carries instructions plus text files; every chat in the project gets
them as context (see ``project_context``). Chats outside any project have ``project_id`` NULL.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    model      TEXT NOT NULL DEFAULT '',
    messages   TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS chats_updated ON chats(updated_at DESC);
CREATE TABLE IF NOT EXISTS projects (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    instructions TEXT NOT NULL DEFAULT '',
    model        TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS project_files (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name       TEXT NOT NULL,
    content    TEXT NOT NULL,
    size       INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS project_files_project ON project_files(project_id);
"""
MAX_TITLE = 120
MAX_PROJECT_NAME = 80
MAX_INSTRUCTIONS = 20_000
MAX_FILE_BYTES = 1_000_000           # per file
MAX_PROJECT_FILE_BYTES = 4_000_000   # all files of one project
MAX_FILES = 100
UNSET = object()


class ProjectError(ValueError):
    """Bad input for a project or project file; the message is shown to the user."""


def decode_text_file(name: str, data: bytes) -> str:
    """Project files are given to the model as text, so only files that already are text qualify.

    PDF, Word, images and other binary formats are rejected (they would need conversion that
    the model does not do itself)."""
    if len(data) > MAX_FILE_BYTES:
        raise ProjectError(f"{name} is larger than {MAX_FILE_BYTES // 1_000_000} MB.")
    kinds = "Project files must be text (code, Markdown, CSV, JSON, plain text…)."
    # UTF-16 only with a byte-order mark: without one, almost any bytes "decode" as UTF-16.
    utf16 = data[:2] in (b"\xff\xfe", b"\xfe\xff")
    if not utf16 and b"\x00" in data[:8192]:
        raise ProjectError(f"{name} is not a text file. {kinds}")
    try:
        text = data.decode("utf-16" if utf16 else "utf-8-sig")
    except UnicodeDecodeError:
        raise ProjectError(f"{name} is not UTF-8 text. {kinds}") from None
    if "\x00" in text:
        raise ProjectError(f"{name} is not a text file. {kinds}")
    return text.replace("\r\n", "\n")


def project_context(project: dict | None, budget_chars: int | None = None) -> str:
    """The system-prompt block for a chat in ``project``: instructions, then the files.

    Files beyond ``budget_chars`` are cut (with a note) so the instructions and the conversation
    still fit the model's context."""
    if not project:
        return ""
    parts = []
    instructions = (project.get("instructions") or "").strip()
    if instructions:
        parts.append(instructions)
    files = project.get("files") or []
    if files:
        used = sum(len(p) for p in parts)
        blocks = []
        for f in files:
            content = f.get("content", "")
            room = None if budget_chars is None else budget_chars - used
            if room is not None and room <= 200:
                blocks.append(f'<file name="{f["name"]}">[left out: not enough context left]</file>')
                continue
            if room is not None and len(content) > room - 120:
                content = content[: max(0, room - 120)] + "\n[…truncated to fit the context]"
            block = f'<file name="{f["name"]}">\n{content}\n</file>'
            used += len(block)
            blocks.append(block)
        parts.append(f'You are working in the project "{project.get("name", "")}". '
                     "Its files are below; use them when they are relevant.\n\n" + "\n\n".join(blocks))
    return "\n\n".join(parts)


class ChatStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.execute("PRAGMA journal_mode=WAL")
            columns = {r["name"] for r in self._db.execute("PRAGMA table_info(chats)")}
            if "project_id" not in columns:          # databases from Studio 1.0
                self._db.execute("ALTER TABLE chats ADD COLUMN project_id TEXT")
            self._db.execute("CREATE INDEX IF NOT EXISTS chats_project ON chats(project_id)")
            self._db.commit()

    # --- chats ---------------------------------------------------------------------------
    @staticmethod
    def _row(row: sqlite3.Row, with_messages: bool) -> dict:
        out = {k: row[k] for k in ("id", "title", "model", "project_id", "created_at", "updated_at")}
        if with_messages:
            out["messages"] = json.loads(row["messages"])
        return out

    def list(self, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r, False) for r in rows]

    def get(self, chat_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return self._row(row, True) if row else None

    def create(self, title: str = "", model: str = "", messages: list | None = None,
               project_id: str | None = None) -> dict:
        if project_id and not self.get_project(project_id, with_files=False):
            raise ProjectError("That project no longer exists.")
        now = time.time()
        chat_id = uuid.uuid4().hex
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO chats (id, title, model, messages, project_id, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (chat_id, title[:MAX_TITLE], model, json.dumps(messages or []), project_id or None, now, now))
        return self.get(chat_id)

    def update(self, chat_id: str, title: str | None = None, model: str | None = None,
               messages: list | None = None, project_id=UNSET) -> dict | None:
        current = self.get(chat_id)
        if current is None:
            return None
        if project_id is not UNSET and project_id and not self.get_project(project_id, with_files=False):
            raise ProjectError("That project no longer exists.")
        title = current["title"] if title is None else title[:MAX_TITLE]
        model = current["model"] if model is None else model
        msgs = current["messages"] if messages is None else messages
        project = current["project_id"] if project_id is UNSET else (project_id or None)
        with self._lock, self._db:
            self._db.execute(
                "UPDATE chats SET title = ?, model = ?, messages = ?, project_id = ?, updated_at = ? "
                "WHERE id = ?", (title, model, json.dumps(msgs), project, time.time(), chat_id))
        return self.get(chat_id)

    def delete(self, chat_id: str) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        return cur.rowcount > 0

    def clear(self) -> int:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM chats")
        return cur.rowcount

    # --- projects ------------------------------------------------------------------------
    def _project_row(self, row: sqlite3.Row) -> dict:
        out = {k: row[k] for k in ("id", "name", "instructions", "model", "created_at", "updated_at")}
        stats = self._db.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM project_files WHERE project_id = ?",
            (row["id"],)).fetchone()
        out["file_count"], out["file_bytes"] = stats["n"], stats["bytes"]
        out["chat_count"] = self._db.execute(
            "SELECT COUNT(*) FROM chats WHERE project_id = ?", (row["id"],)).fetchone()[0]
        return out

    def list_projects(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
            return [self._project_row(r) for r in rows]

    def get_project(self, project_id: str, with_files: bool = True, with_content: bool = False) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                return None
            out = self._project_row(row)
            if with_files:
                cols = "id, name, size, created_at" + (", content" if with_content else "")
                out["files"] = [dict(r) for r in self._db.execute(
                    f"SELECT {cols} FROM project_files WHERE project_id = ? ORDER BY created_at",  # noqa: S608
                    (project_id,))]
        return out

    @staticmethod
    def _clean_project_fields(name=None, instructions=None) -> tuple:
        if name is not None:
            name = " ".join(str(name).split())[:MAX_PROJECT_NAME]
            if not name:
                raise ProjectError("A project needs a name.")
        if instructions is not None:
            instructions = str(instructions)
            if len(instructions) > MAX_INSTRUCTIONS:
                raise ProjectError(f"Instructions are limited to {MAX_INSTRUCTIONS:,} characters.")
        return name, instructions

    def create_project(self, name: str, instructions: str = "", model: str = "") -> dict:
        name, instructions = self._clean_project_fields(name, instructions)
        now = time.time()
        project_id = uuid.uuid4().hex
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO projects (id, name, instructions, model, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (project_id, name, instructions or "", model or "", now, now))
        return self.get_project(project_id)

    def update_project(self, project_id: str, name=None, instructions=None, model=None) -> dict | None:
        current = self.get_project(project_id, with_files=False)
        if current is None:
            return None
        name, instructions = self._clean_project_fields(name, instructions)
        with self._lock, self._db:
            self._db.execute(
                "UPDATE projects SET name = ?, instructions = ?, model = ?, updated_at = ? WHERE id = ?",
                (current["name"] if name is None else name,
                 current["instructions"] if instructions is None else instructions,
                 current["model"] if model is None else model, time.time(), project_id))
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> int | None:
        """Deletes the project, its files and its chats. Returns the number of chats deleted."""
        with self._lock, self._db:
            if self._db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
                return None
            chats = self._db.execute("DELETE FROM chats WHERE project_id = ?", (project_id,)).rowcount
            self._db.execute("DELETE FROM project_files WHERE project_id = ?", (project_id,))
            self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return chats

    def add_file(self, project_id: str, name: str, data: bytes) -> dict:
        project = self.get_project(project_id, with_files=False)
        if project is None:
            raise ProjectError("That project no longer exists.")
        name = Path(str(name).replace("\\", "/")).name.strip()[:200] or "file.txt"
        text = decode_text_file(name, data)
        size = len(text.encode("utf-8"))
        if project["file_count"] >= MAX_FILES:
            raise ProjectError(f"A project can hold up to {MAX_FILES} files.")
        if project["file_bytes"] + size > MAX_PROJECT_FILE_BYTES:
            raise ProjectError(f"Project files are limited to {MAX_PROJECT_FILE_BYTES // 1_000_000} MB in total.")
        file_id, now = uuid.uuid4().hex, time.time()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO project_files (id, project_id, name, content, size, created_at) VALUES (?,?,?,?,?,?)",
                (file_id, project_id, name, text, size, now))
            self._db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
        return {"id": file_id, "name": name, "size": size, "created_at": now}

    def get_file(self, project_id: str, file_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM project_files WHERE id = ? AND project_id = ?",
                                   (file_id, project_id)).fetchone()
        return dict(row) if row else None

    def delete_file(self, project_id: str, file_id: str) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM project_files WHERE id = ? AND project_id = ?",
                                   (file_id, project_id))
            if cur.rowcount:
                self._db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (time.time(), project_id))
        return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._db.close()
