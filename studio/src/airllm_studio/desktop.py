"""Desktop integration: open the UI in an app-style window and, on Windows, a tray icon."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .client import Client, ClientError, ensure_server
from .config import data_dir, logs_dir, parse_host

log = logging.getLogger("airllm_studio.desktop")
WEB_DIR = Path(__file__).parent / "web"

CHROMIUM_LINUX = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                  "microsoft-edge", "microsoft-edge-stable", "brave-browser"]

# Linux docks (GNOME, KDE) pick a window's icon by matching it to a .desktop file, so the app
# window has to identify itself as "airllm" (packaging/linux/airllm.desktop):
#  - X11 / XWayland: Chromium sets WM_CLASS to the --class value -> desktop id "airllm".
#  - native Wayland: --class is ignored for --app windows; Chromium derives the xdg app_id as
#    "<exe>-<host>_<path>-<profile>" with path characters replaced by "_", e.g.
#    "chrome-127.0.0.1__-Default". airllm.desktop lists that value as StartupWMClass.
#    Only Chrome and Chromium use the "chrome" prefix, so other Chromium browsers run through
#    XWayland, where --class applies.
WM_CLASS = "airllm"
WAYLAND_NATIVE_PREFIX = "chrome"


def chromium_app_id(url: str, profile: str = "Default", exe: str = WAYLAND_NATIVE_PREFIX) -> str:
    """The Wayland app_id Chromium gives an --app=<url> window (see WM_CLASS notes above)."""
    parsed = urlparse(url)
    name = f"{exe}-{parsed.hostname}_{parsed.path or '/'}-{profile}"
    return re.sub(r'[/\\:*?"<>| ]', "_", name)


def _window_url(url: str) -> str:
    """Use one fixed loopback host, so the Wayland app_id (and the dock icon) never changes."""
    parsed = urlparse(url)
    if parsed.hostname == "localhost":
        parsed = parsed._replace(netloc=f"127.0.0.1:{parsed.port}" if parsed.port else "127.0.0.1")
    return urlunparse(parsed._replace(path=parsed.path or "/"))


def _is_native_wayland_capable(browser: str) -> bool:
    name = Path(os.path.realpath(browser)).name.lower()
    return any(key in name for key in ("chrome", "chromium")) and "edge" not in name


def _profile_dir(browser: str) -> Path:
    """Snap-packaged browsers (Ubuntu's chromium) cannot write to hidden folders like ~/.airllm."""
    if os.path.realpath(browser).startswith("/snap/") or browser.startswith("/snap/"):
        snap = Path(browser).name.split(".")[0] or "chromium"
        return Path.home() / "snap" / snap / "common" / "airllm-window"
    return data_dir() / "window-profile"


def window_command(browser: str, url: str, platform: str | None = None,
                   environ: dict | None = None) -> list[str]:
    """Command line that opens the UI as a standalone app window in a Chromium-based browser."""
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    profile = _profile_dir(browser) if platform.startswith("linux") else data_dir() / "window-profile"
    args = [browser, f"--app={_window_url(url)}", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--window-size=1280,860"]
    if platform.startswith("linux"):
        args.append(f"--class={WM_CLASS}")
        wayland = bool(environ.get("WAYLAND_DISPLAY")) or environ.get("XDG_SESSION_TYPE") == "wayland"
        if wayland and not _is_native_wayland_capable(browser):
            args.append("--ozone-platform=x11")
    return args


def _find_windows_edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.exists():
                return str(path)
    return shutil.which("msedge")


def open_window(url: str) -> None:
    """Open the UI as a standalone app window (Edge/Chrome --app), else in the default browser."""
    browser = None
    if sys.platform == "win32":
        browser = _find_windows_edge()
    elif sys.platform.startswith("linux"):
        browser = next((shutil.which(b) for b in CHROMIUM_LINUX if shutil.which(b)), None)
    if browser:
        args = window_command(browser, url)
        try:
            kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if sys.platform != "win32":
                kwargs["start_new_session"] = True
            subprocess.Popen(args, **kwargs)
            return
        except OSError as exc:
            log.warning("could not start %s: %s", browser, exc)
    webbrowser.open(url)


def _redirect_output_if_windowless() -> None:
    """pythonw has no stdout/stderr; libraries that print would crash, so send them to a log."""
    if sys.stdout is None or sys.stderr is None:
        stream = open(logs_dir() / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream


def run_app(background: bool = False) -> int:
    client = Client()
    url = client.url + "/"
    if client.running():
        if not background:
            open_window(url)
        return 0
    if sys.platform == "win32":
        try:
            import pystray  # noqa: F401
        except ImportError:
            pass
        else:
            return _run_with_tray(open_on_start=not background)
    try:
        ensure_server(client, quiet=True)
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not background:
        open_window(url)
    return 0


def _run_with_tray(open_on_start: bool) -> int:
    """Windows: host the server in this (windowless) process with a tray icon to open or quit."""
    import pystray
    import uvicorn
    from PIL import Image

    from .server import Studio, create_app

    _redirect_output_if_windowless()
    logging.basicConfig(filename=str(logs_dir() / "server.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host, port = parse_host()
    studio = Studio()
    server = uvicorn.Server(uvicorn.Config(create_app(studio, bind_host=host), host=host, port=port, log_config=None,
                                           access_log=False, timeout_graceful_shutdown=5))
    client = Client()
    url = client.url + "/"

    def quit_app(icon=None, item=None):
        server.should_exit = True
        if icon is not None:
            icon.stop()

    studio.shutdown_hook = lambda: quit_app(tray)

    def open_folder(path: Path):
        os.startfile(str(path))  # type: ignore[attr-defined]

    tray = pystray.Icon(
        "AirLLM", Image.open(WEB_DIR / "icon-256.png"), "AirLLM",
        menu=pystray.Menu(
            pystray.MenuItem("Open AirLLM", lambda i, it: open_window(url), default=True),
            pystray.MenuItem("Open models folder", lambda i, it: open_folder(studio.settings.models_dir())),
            pystray.MenuItem("Open logs folder", lambda i, it: open_folder(logs_dir())),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit AirLLM", quit_app),
        ))

    def serve():
        try:
            server.run()
        finally:
            tray.stop()

    thread = threading.Thread(target=serve, name="uvicorn", daemon=True)
    thread.start()
    if open_on_start:
        def open_when_ready():
            if client.wait_ready(60):
                open_window(url)
        threading.Thread(target=open_when_ready, daemon=True).start()
    tray.run()                      # blocks until Quit
    server.should_exit = True
    thread.join(timeout=10)
    return 0
