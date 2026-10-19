"""`airllm` command line, modelled on the Ollama CLI.

    airllm serve                 run the server in the foreground (API + web UI)
    airllm app                   open the desktop app (starts the server if needed)
    airllm pull <model>          download + prepare a Hugging Face model (or a local folder)
    airllm run <model> [prompt]  chat in the terminal, or answer one prompt
    airllm list | ps | rm | stop | status
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

from . import __version__
from .client import Client, ClientError, ensure_server
from .config import apply_cuda_overlay, base_url, logs_dir, parse_host


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def ago(iso: str) -> str:
    from datetime import datetime, timezone

    try:
        delta = datetime.now(timezone.utc) - datetime.fromisoformat(iso)
    except ValueError:
        return iso
    secs = int(delta.total_seconds())
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if secs >= size:
            n = secs // size
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"


def table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows, strict=True)]
    fmt = "    ".join("{:<%d}" % w for w in widths)
    return "\n".join(fmt.format(*r) for r in [headers, *rows])


# --- commands -----------------------------------------------------------------------------
def cmd_serve(args) -> int:
    import uvicorn

    from .server import Studio, create_app

    host, port = parse_host(args.host)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("AIRLLM_API_KEY"):
        logging.warning("listening on %s without AIRLLM_API_KEY: anyone on the network can use it", host)
    studio = Studio()
    config = uvicorn.Config(create_app(studio, bind_host=host), host=host, port=port, log_config=None,
                            log_level=args.log_level, access_log=False, timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)
    studio.shutdown_hook = lambda: setattr(server, "should_exit", True)
    logging.info("AirLLM Studio %s on http://%s:%s  (models: %s)", __version__, host, port,
                 studio.settings.models_dir())
    server.run()
    return 0


def cmd_app(args) -> int:
    from .desktop import run_app

    return run_app(background=args.background)


def _progress_line(ev: dict, started: float) -> str:
    total, done = ev.get("total") or 0, ev.get("completed") or 0
    status = ev.get("status", "")
    if not total:
        return status
    pct = done * 100 / total
    bar = ("█" * int(pct / 4)).ljust(25)
    if status.startswith("pulling"):
        rate = done / max(time.time() - started, 0.001)
        return f"{status}  {bar} {pct:5.1f}%  {human_bytes(done)}/{human_bytes(total)}  {human_bytes(rate)}/s"
    return f"{status}  {bar} {done}/{total}"


def cmd_pull(args) -> int:
    client = ensure_server()
    started = time.time()
    width = 0
    try:
        body = {"model": args.model}
        if args.trust_remote_code:
            body["trust_remote_code"] = True
        for ev in client.stream("/api/pull", body):
            if ev.get("status") == "success":
                print("\r" + " " * width + "\rsuccess")
                return 0
            line = _progress_line(ev, started)
            width = max(width, len(line))
            print("\r" + line.ljust(width), end="", flush=True)
    except KeyboardInterrupt:
        print("\nStopped watching; the pull continues in the server. Cancel it from the app.")
        return 130
    return 1


def cmd_list(args) -> int:
    client = ensure_server(quiet=True)
    models = client.get("/api/studio/models")["models"]
    rows = []
    for m in models:
        status = m["status"]
        if m.get("job") and not m["job"]["done"]:
            job = m["job"]
            if job["total"] and job["phase"] == "downloading":
                status = f"downloading {job['completed'] * 100 // max(job['total'], 1)}%"
            elif job["phase"] == "preparing" and job["layers_total"]:
                status = f"preparing {job['layers_done']}/{job['layers_total']}"
            else:
                status = job["phase"]
        rows.append([m["name"], m["parameter_size"] or "-", human_bytes(m["size_on_disk"]),
                     status + (" (loaded)" if m.get("loaded") else ""), ago(m["modified_at"])])
    print(table(rows, ["NAME", "PARAMS", "SIZE", "STATUS", "MODIFIED"]) if rows else
          "No models yet. Try: airllm pull HuggingFaceTB/SmolLM2-135M-Instruct")
    return 0


def cmd_ps(args) -> int:
    client = Client()
    if not client.running():
        print("AirLLM server is not running.")
        return 0
    status = client.get("/api/studio/status")
    eng = status["engine"]
    if not eng["model"]:
        print(f"No model loaded (server idle, device {status.get('device') or 'auto'}).")
        return 0
    print(table([[eng["model"], eng["device"] or "-", eng["state"], str(eng["queued"])]],
                ["NAME", "DEVICE", "STATE", "QUEUED"]))
    return 0


def cmd_rm(args) -> int:
    client = ensure_server(quiet=True)
    code = 0
    for name in args.models:
        try:
            client.delete("/api/delete", {"model": name})
            print(f"deleted '{name}'")
        except ClientError as exc:
            print(f"error: {exc}", file=sys.stderr)
            code = 1
    return code


def cmd_stop(args) -> int:
    client = Client()
    if not client.running():
        if not args.quiet:
            print("AirLLM server is not running.")
        return 0
    try:
        client.post("/api/shutdown")
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for _ in range(50):
        if not client.running():
            break
        time.sleep(0.2)
    if not args.quiet:
        print("AirLLM server stopped.")
    return 0


def cmd_status(args) -> int:
    client = Client()
    if not client.running():
        print(f"AirLLM server: not running ({client.url}). Start it with `airllm serve` or `airllm app`.")
        return 1
    s = client.get("/api/studio/status")
    hw = s["hardware"]
    gpus = ", ".join(g["name"] for g in hw.get("gpus", [])) or "none (CPU only)"
    print(f"AirLLM Studio {s['version']} (airllm {s['airllm']}, python {s['python']}) at {client.url}")
    print(f"  torch:    {hw.get('torch')}  CUDA: {hw.get('cuda') or 'no'}  GPUs: {gpus}")
    print(f"  device:   {s.get('device') or 'auto'}")
    print(f"  model:    {s['engine']['model'] or '-'} ({s['engine']['state']})")
    print(f"  models:   {s['models_dir']}  (free {human_bytes(s['disk'].get('free', 0))})")
    return 0


def cmd_run(args) -> int:
    client = ensure_server(quiet=True)
    models = {m["name"].lower(): m for m in client.get("/api/studio/models")["models"]}
    if args.model.lower() not in models:
        print(f"'{args.model}' is not installed; pulling it first.", file=sys.stderr)
        if cmd_pull(argparse.Namespace(model=args.model)) != 0:
            return 1
    options = {k: v for k, v in (("temperature", args.temperature), ("num_predict", args.max_tokens))
               if v is not None}
    messages: list[dict] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})

    def ask(prompt: str) -> bool:
        messages.append({"role": "user", "content": prompt})
        answer, spinner_on, stats = [], True, {}
        stop_spin = threading.Event()

        def spin():
            frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            i = 0
            while not stop_spin.wait(0.1):
                print(f"\r{frames[i % len(frames)]} ", end="", file=sys.stderr, flush=True)
                i += 1
            print("\r  \r", end="", file=sys.stderr, flush=True)

        spinner = threading.Thread(target=spin, daemon=True)
        if sys.stderr.isatty():
            spinner.start()
        try:
            for ev in client.stream("/api/chat", {"model": args.model, "messages": messages,
                                                  "stream": True, "options": options}):
                text = ev.get("message", {}).get("content", "")
                if text:
                    if spinner_on:
                        stop_spin.set()
                        if spinner.is_alive():
                            spinner.join()
                        spinner_on = False
                    answer.append(text)
                    print(text, end="", flush=True)
                if ev.get("done"):
                    stats = ev
        except KeyboardInterrupt:
            print("\n[stopped]")
        except ClientError as exc:
            stop_spin.set()
            print(f"\nerror: {exc}", file=sys.stderr)
            messages.pop()
            return False
        finally:
            stop_spin.set()
        print()
        if args.verbose and stats:
            evals, dur = stats.get("eval_count", 0), stats.get("eval_duration", 0) / 1e9
            print(f"[{evals} tokens, {evals / dur if dur else 0:.2f} tok/s, "
                  f"total {stats.get('total_duration', 0) / 1e9:.1f}s]", file=sys.stderr)
        messages.append({"role": "assistant", "content": "".join(answer)})
        return True

    if args.prompt:
        return 0 if ask(" ".join(args.prompt)) else 1

    print(f"Chatting with {args.model}. /clear resets the conversation, /bye or Ctrl+D quits.")
    while True:
        try:
            line = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/bye", "/exit", "/quit"):
            return 0
        if line == "/clear":
            messages = [m for m in messages if m["role"] == "system"]
            print("Conversation cleared.")
            continue
        if line in ("/help", "/?"):
            print("/clear  reset conversation   /bye  quit")
            continue
        ask(line)


# --- entry point -------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="airllm", description="AirLLM Studio: run large LLMs locally with AirLLM.")
    p.add_argument("-v", "--version", action="version",
                   version=f"airllm-studio {__version__} (server {base_url()})")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    s = sub.add_parser("serve", help="run the server in the foreground")
    s.add_argument("--host", default=None, help="host[:port] to listen on (default AIRLLM_HOST or 127.0.0.1:11435)")
    s.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("app", help="open the desktop app (starts the server if needed)")
    s.add_argument("--background", action="store_true", help="start the server (and tray icon) without a window")
    s.set_defaults(func=cmd_app)

    s = sub.add_parser("pull", help="download and prepare a model (Hugging Face id or local folder)")
    s.add_argument("model")
    s.add_argument("--trust-remote-code", action="store_true",
                   help="allow a model that ships its own Python code to run it (only for publishers you trust)")
    s.set_defaults(func=cmd_pull)

    s = sub.add_parser("run", help="chat with a model, or answer a single prompt")
    s.add_argument("model")
    s.add_argument("prompt", nargs="*")
    s.add_argument("--system", help="system prompt")
    s.add_argument("--temperature", type=float)
    s.add_argument("--max-tokens", type=int)
    s.add_argument("--verbose", action="store_true", help="print token speed after each answer")
    s.set_defaults(func=cmd_run)

    for name in ("list", "ls"):
        s = sub.add_parser(name, help="list installed models" if name == "list" else argparse.SUPPRESS)
        s.set_defaults(func=cmd_list)

    s = sub.add_parser("ps", help="show the loaded model")
    s.set_defaults(func=cmd_ps)

    s = sub.add_parser("rm", help="delete models")
    s.add_argument("models", nargs="+")
    s.set_defaults(func=cmd_rm)

    s = sub.add_parser("stop", help="stop the background server")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_stop)

    s = sub.add_parser("status", help="server, hardware and storage info")
    s.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    apply_cuda_overlay()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args) or 0
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(f"(server log: {logs_dir() / 'server.log'})", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
