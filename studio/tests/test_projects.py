"""Projects: grouping chats, instructions and text files that become every chat's context."""
import pytest

from airllm_studio.chats import MAX_FILE_BYTES, ChatStore, ProjectError, decode_text_file, project_context


def make_project(client, **kw):
    body = {"name": "Release notes", "instructions": "Answer in British English.", **kw}
    resp = client.post("/api/studio/projects", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def upload(client, project_id, name, data: bytes):
    return client.post(f"/api/studio/projects/{project_id}/files", params={"name": name}, content=data)


def test_project_crud_and_files(client):
    p = make_project(client, model="org/ready-model")
    assert p["name"] == "Release notes" and p["files"] == [] and p["chat_count"] == 0

    f = upload(client, p["id"], "notes.md", "# v4\n- faster loading\n".encode())
    assert f.status_code == 200 and f.json()["name"] == "notes.md"
    listed = client.get("/api/studio/projects").json()["projects"]
    assert listed[0]["file_count"] == 1 and listed[0]["file_bytes"] == f.json()["size"]

    full = client.get(f"/api/studio/projects/{p['id']}/files/{f.json()['id']}").json()
    assert full["content"].startswith("# v4")

    patched = client.patch(f"/api/studio/projects/{p['id']}", json={"name": "  Notes  ", "model": ""}).json()
    assert patched["name"] == "Notes" and patched["instructions"] == "Answer in British English."

    assert client.delete(f"/api/studio/projects/{p['id']}/files/{f.json()['id']}").json()["deleted"]
    assert client.get(f"/api/studio/projects/{p['id']}").json()["file_count"] == 0


def test_project_files_must_be_text(client):
    p = make_project(client)
    pdf = upload(client, p["id"], "spec.pdf", b"%PDF-1.7\n\x00\x01\x02binary")
    assert pdf.status_code == 400 and "not a text file" in pdf.json()["error"]
    latin1 = upload(client, p["id"], "old.txt", "café".encode("latin-1"))
    assert latin1.status_code == 400 and "UTF-8" in latin1.json()["error"]
    utf16 = upload(client, p["id"], "win.txt", "hello".encode("utf-16"))
    assert utf16.status_code == 200
    big = upload(client, p["id"], "big.txt", b"a" * (MAX_FILE_BYTES + 1))
    assert big.status_code in (400, 413)
    # chunked body with no Content-Length: the server still stops reading at its limit
    chunks = (b"a" * 500_000 for _ in range(6))
    huge = client.post(f"/api/studio/projects/{p['id']}/files?name=huge.txt", content=chunks)
    assert huge.status_code == 413
    assert upload(client, p["id"], "../../etc/passwd", b"x").json()["name"] == "passwd"   # no paths


def test_project_chat_gets_instructions_and_files(client, studio):
    p = make_project(client)
    upload(client, p["id"], "glossary.txt", b"AirLLM: streams one layer at a time.")
    resp = client.post("/api/chat", json={"model": "org/ready-model", "stream": False,
                                          "airllm_project": p["id"],
                                          "messages": [{"role": "user", "content": "what is airllm"}]})
    assert resp.status_code == 200
    system = studio.engine.last_messages[0]
    assert system["role"] == "system"
    assert "British English" in system["content"]
    assert '<file name="glossary.txt">' in system["content"] and "one layer at a time" in system["content"]
    # the global system prompt comes first
    studio.settings.update({"defaults": {"system_prompt": "Be brief."}})
    client.post("/api/chat", json={"model": "org/ready-model", "stream": False, "airllm_project": p["id"],
                                   "messages": [{"role": "user", "content": "hi"}]})
    assert studio.engine.last_messages[0]["content"].startswith("Be brief.\n\nAnswer in British English.")
    missing = client.post("/api/chat", json={"model": "org/ready-model", "airllm_project": "nope",
                                             "messages": [{"role": "user", "content": "hi"}]})
    assert missing.status_code == 404


def test_chats_belong_to_projects_and_go_with_them(client):
    p = make_project(client)
    inside = client.post("/api/studio/chats", json={"title": "in", "project_id": p["id"]}).json()
    outside = client.post("/api/studio/chats", json={"title": "out"}).json()
    assert inside["project_id"] == p["id"] and outside["project_id"] is None

    moved = client.patch(f"/api/studio/chats/{outside['id']}", json={"project_id": p["id"]}).json()
    assert moved["project_id"] == p["id"] and moved["title"] == "out"
    back = client.patch(f"/api/studio/chats/{outside['id']}", json={"project_id": None}).json()
    assert back["project_id"] is None
    renamed = client.patch(f"/api/studio/chats/{inside['id']}", json={"title": "renamed"}).json()
    assert renamed["project_id"] == p["id"]                       # untouched when not sent

    assert client.post("/api/studio/chats", json={"project_id": "gone"}).status_code == 400
    result = client.delete(f"/api/studio/projects/{p['id']}").json()
    assert result["deleted_chats"] == 1
    ids = [c["id"] for c in client.get("/api/studio/chats").json()["chats"]]
    assert outside["id"] in ids and inside["id"] not in ids
    assert client.get(f"/api/studio/projects/{p['id']}").status_code == 404


def test_project_validation(client):
    assert client.post("/api/studio/projects", json={"name": "   "}).status_code == 400
    assert client.post("/api/studio/projects", json={"name": "x", "instructions": "a" * 30_000}).status_code == 400


def test_context_budget_cuts_files_not_instructions():
    project = {"name": "P", "instructions": "Follow the style guide.",
               "files": [{"name": "a.txt", "content": "A" * 5000}, {"name": "b.txt", "content": "B" * 5000}]}
    full = project_context(project)
    assert full.startswith("Follow the style guide.") and "B" * 5000 in full
    cut = project_context(project, budget_chars=3000)
    assert cut.startswith("Follow the style guide.")
    assert "truncated to fit" in cut and "left out" in cut and len(cut) < 3600
    assert project_context(None) == "" and project_context({"name": "x"}) == ""


def test_old_databases_get_the_project_column(tmp_path):
    import sqlite3

    db = tmp_path / "chats.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', "
                      "model TEXT NOT NULL DEFAULT '', messages TEXT NOT NULL DEFAULT '[]', "
                      "created_at REAL NOT NULL, updated_at REAL NOT NULL);"
                      "INSERT INTO chats VALUES ('old', 'kept', 'm', '[]', 1, 1);")
    con.close()
    store = ChatStore(db)
    assert store.get("old")["project_id"] is None and store.list()[0]["title"] == "kept"


def test_decode_text_file_rules():
    assert decode_text_file("a.txt", "x\r\ny".encode()) == "x\ny"
    assert decode_text_file("bom.txt", b"\xef\xbb\xbfhi") == "hi"
    with pytest.raises(ProjectError):
        decode_text_file("img.png", b"\x89PNG\r\n\x1a\n\x00\x00")
