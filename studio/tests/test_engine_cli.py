import threading

import pytest

from airllm_studio.cli import build_parser, human_bytes, table
from airllm_studio.engine import GenOptions


def test_gen_options_clamp_and_merge():
    class D:
        max_new_tokens, temperature, top_p, context_length = 100, 0.7, 0.9, 4096

    o = GenOptions.merge(D, max_new_tokens=10**9, temperature=-1, top_p=5, stop="###")
    assert o.max_new_tokens == 32768 and o.temperature == 0 and o.top_p == 1.0 and o.stop == ["###"]
    assert GenOptions.merge(D).max_new_tokens == 100


def test_queue_and_cancel(studio):
    """A second request waits while the first one generates, and can be cancelled while waiting."""
    eng = studio.engine
    eng.delay = 0.02
    first_cancel, second_cancel = threading.Event(), threading.Event()
    first = eng.stream("org/ready-model", [{"role": "user", "content": "a"}], GenOptions(), first_cancel)
    next(first)                                      # holds the lock now
    events = []

    def second():
        for ev in eng.stream("org/ready-model", [{"role": "user", "content": "b"}], GenOptions(), second_cancel):
            events.append(ev)

    t = threading.Thread(target=second)
    t.start()
    t.join(0.3)
    assert events and events[0]["status"] == "queued"
    second_cancel.set()
    t.join(2)
    assert events[-1]["done_reason"] == "cancelled"
    first_cancel.set()
    assert list(first)[-1]["done_reason"] == "cancelled"
    assert eng.waiting == 0


def test_cli_parser_and_helpers():
    p = build_parser()
    args = p.parse_args(["run", "Qwen/Qwen3-8B", "hello", "world", "--max-tokens", "5"])
    assert args.model == "Qwen/Qwen3-8B" and args.prompt == ["hello", "world"] and args.max_tokens == 5
    assert p.parse_args(["ls"]).func.__name__ == "cmd_list"
    assert human_bytes(1536) == "2 KB" and human_bytes(5 * 1024**3) == "5.0 GB"
    assert table([["a", "1"]], ["NAME", "N"]).splitlines()[1].startswith("a")


def test_run_pulls_a_missing_model_first(monkeypatch, capsys):
    """`airllm run <model>` on a model that is not installed pulls it, then answers (it used to crash)."""
    from airllm_studio import cli

    calls = []

    class FakeClient:
        url = "http://127.0.0.1:11435"

        def get(self, path, *args, **kwargs):
            return {"models": []}

        def stream(self, path, body):
            calls.append((path, dict(body)))
            if path == "/api/pull":
                yield {"status": "success"}
            else:
                yield {"message": {"content": "hi there"}, "done": True}

    monkeypatch.setattr(cli, "ensure_server", lambda *args, **kwargs: FakeClient())
    args = build_parser().parse_args(["run", "org/model", "hello"])
    assert cli.cmd_run(args) == 0
    assert [path for path, _ in calls] == ["/api/pull", "/api/chat"]
    assert calls[0][1] == {"model": "org/model"}      # no custom-code permission is granted implicitly
    assert "hi there" in capsys.readouterr().out


def test_long_chats_drop_old_turns_but_keep_system_and_latest(studio):
    """Too long a history loses its oldest turns, never the system prompt (project files) or the question."""
    np = pytest.importorskip("numpy")

    class Tok:
        chat_template = "x"

        def apply_chat_template(self, msgs, tokenize, add_generation_prompt):
            return "|".join(f"{m['role']}:{m['content']}" for m in msgs)

        def __call__(self, text, return_tensors, add_special_tokens):
            return {"input_ids": np.zeros((1, len(text.split())), dtype=np.int64)}

    class Model:
        tokenizer = Tok()

    eng = studio.engine
    eng.model = Model()
    msgs = [{"role": "system", "content": "s " * 20}]
    for i in range(10):
        msgs += [{"role": "user", "content": f"q{i} " * 10}, {"role": "assistant", "content": f"a{i} " * 10}]
    msgs.append({"role": "user", "content": "latest question"})
    seen = []
    orig = Tok.__call__

    def spy(self, text, **kw):
        seen.append(text)
        return orig(self, text, **kw)

    Tok.__call__ = spy
    ids = eng._encode(msgs, None, limit=80)
    assert ids.shape[1] <= 80
    final = seen[-1]
    assert final.startswith("system:") and final.endswith("user:latest question")
    assert "q0" not in final and "a9" in final
