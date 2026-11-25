"""
Node.js for the VeriWorkly checker, on a server that has no Node (Streamlit Community Cloud).

  - Node 24 comes from the Python package `nodejs-wheel-binaries` (requirements.txt): it carries the `node` program and
    npm inside the wheel, so pip installs them like any other package. A computer that already has Node on its PATH
    (this Windows PC, the Docker image) keeps using it when the wheel is not installed.
  - The engine itself (`@veriworkly/ats-engine`, MIT) is an npm package. It is installed ONCE into vendor/ats-engine
    (package.json and package-lock.json are in the repo, node_modules is not), in the background, as soon as the server
    has its first visitor. A server that was already set up (the folder is there) does nothing.
  - The engine's own PDF and DOCX readers (pdf-parse, pdfjs-dist, mammoth) are optional extras it does not need here:
    the Lab hands it the plain text it already extracted from the PDF (see lab_third.py).

Never raises. status() says where things are, in plain words, for the card on the Admin page.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX = os.path.join(HERE, "vendor", "ats-engine")                # package.json + package-lock.json live here
ENGINE_DIR = os.path.join(PREFIX, "node_modules", "@veriworkly", "ats-engine")
MIN_NODE = (22, 12)                                                # the engine's own requirement
INSTALL_TIMEOUT = 420                                              # seconds for the one-time npm install

_LOCK = threading.Lock()
_STATE = {"state": "idle", "why": "", "seconds": None, "detail": ""}       # idle | installing | ready | failed


# ---------------------------------------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------------------------------------
def _wheel_dir():
    """The folder of the node program inside the nodejs-wheel-binaries package, or None."""
    try:
        import nodejs_wheel
    except Exception:
        return None
    root = os.path.dirname(nodejs_wheel.__file__)
    return root if os.name == "nt" else os.path.join(root, "bin")


def node_path():
    """The node program: the wheel's first (a known version), else one on the PATH. None when there is none."""
    folder = _wheel_dir()
    if folder:
        path = os.path.join(folder, "node.exe" if os.name == "nt" else "node")
        if os.path.isfile(path):
            return path
    return shutil.which("node")


def env():
    """The environment for a node / npm / engine call: node's own folder first on the PATH (the npm and engine
    launchers start `node` by name), a cache folder that is surely writable, and no colours."""
    out = dict(os.environ, NO_COLOR="1", FORCE_COLOR="0", npm_config_update_notifier="false")
    node = node_path()
    if node:
        out["PATH"] = os.path.dirname(node) + os.pathsep + out.get("PATH", "")
    out.setdefault("npm_config_cache", os.path.join(tempfile.gettempdir(), "atslab-npm-cache"))
    return out


def node_version():
    """-> (major, minor, patch) of the node program, or None."""
    node = node_path()
    if not node:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20, env=env()).stdout
        parts = out.strip().lstrip("v").split(".")
        return tuple(int(p) for p in parts[:3])
    except Exception:
        return None


def _npm_cli():
    """npm's own script (run as `node npm-cli.js`, so it works whatever the launchers' permissions are)."""
    roots = []
    try:
        import nodejs_wheel         # the wheel keeps npm in <package>/lib/node_modules/npm (Windows and Linux alike)
        roots.append(os.path.join(os.path.dirname(nodejs_wheel.__file__), "lib", "node_modules", "npm"))
    except Exception:
        pass
    node = shutil.which("node")
    if node:
        base = os.path.dirname(os.path.realpath(node))
        roots += [os.path.join(base, "node_modules", "npm"), os.path.join(base, "..", "lib", "node_modules", "npm")]
    for root in roots:
        path = os.path.normpath(os.path.join(root, "bin", "npm-cli.js"))
        if os.path.isfile(path):
            return path
    return None


# ---------------------------------------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------------------------------------
def engine_script():
    """The engine's command-line script (from its package.json "bin"), or None when it is not installed."""
    try:
        with open(os.path.join(ENGINE_DIR, "package.json"), encoding="utf-8") as fh:
            bin_ = json.load(fh).get("bin")
        rel = bin_.get("ats-engine") if isinstance(bin_, dict) else bin_
        path = os.path.normpath(os.path.join(ENGINE_DIR, rel))
        return path if rel and os.path.isfile(path) else None
    except Exception:
        return None


def engine_command():
    """['node', 'cli.js'] when node and the engine are both there, else None."""
    node, script = node_path(), engine_script()
    return [node, script] if node and script else None


def _install():
    began = time.perf_counter()
    try:
        version = node_version()
        if version is None:
            return _done("failed", "node_missing", began, "no node program (nodejs-wheel-binaries is not installed)")
        if version[:2] < MIN_NODE:
            return _done("failed", "node_too_old", began, "node %s.%s, the engine needs %s.%s" % (*version[:2], *MIN_NODE))
        cli = _npm_cli()
        if cli is None:
            return _done("failed", "npm_missing", began, "no npm next to node")
        call = [node_path(), cli, "install", "--no-audit", "--no-fund", "--loglevel=error", "--omit=optional",
                "--omit=peer", "--prefix", PREFIX]
        done = subprocess.run(call, cwd=PREFIX, capture_output=True, text=True, timeout=INSTALL_TIMEOUT, env=env(),
                              encoding="utf-8", errors="replace")
        if done.returncode != 0 or engine_script() is None:
            detail = ((done.stderr or done.stdout or "").strip().splitlines() or [f"exit {done.returncode}"])[-1]
            return _done("failed", "npm_install_failed", began, detail[:200])
        return _done("ready", "", began, "")
    except subprocess.TimeoutExpired:
        return _done("failed", "npm_install_timeout", began, "")
    except BaseException as e:                      # nothing here ever stops the app
        return _done("failed", type(e).__name__, began, str(e)[:200])


def _done(state, why, began, detail):
    _STATE.update(state=state, why=why, seconds=round(time.perf_counter() - began, 1), detail=detail)


def _work():
    _install()


def ensure(background=True):
    """Make sure the engine is there: nothing to do when it already is; else install it once (in the background by
    default, so a visitor's page never waits). Never during the tests."""
    if engine_command():
        with _LOCK:
            if _STATE["state"] != "installing":
                _STATE.update(state="ready", why="")
        return
    if os.environ.get("ATSLAB_ATS_ENGINE") or shutil.which("ats-engine"):
        return                                      # a server that installed the command itself (the Docker image)
    if os.environ.get("ATSLAB_NODE_INSTALL") == "0" or any(n.startswith("test_") for n in list(sys.modules)):
        return
    with _LOCK:
        if _STATE["state"] in ("installing", "failed"):
            return                                  # once: a failed install is not retried at every click
        _STATE.update(state="installing", why="", detail="")
    if background:
        threading.Thread(target=_work, name="atslab-node-install", daemon=True).start()
    else:
        _work()


def status():
    """-> {"state": idle | installing | ready | failed, "why", "detail", "seconds", "node": "24.19.0" or ""}"""
    version = node_version() if (_STATE["state"] != "idle" or node_path()) else None
    return dict(_STATE, node=".".join(str(p) for p in version) if version else "")
