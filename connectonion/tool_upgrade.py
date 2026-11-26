"""Upgrade the `co` tool without removing the one that is already running (#3363).

`uv tool install --force` deletes the installed tool before the new one is
ready. A failure in that window leaves `co` missing, and a scheduled turn
dies with ``No module named 'connectonion'``. This installs into a fresh
tool directory and points ``bin/co`` at it only after the new install runs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def record_path() -> Path:
    from .environment import global_config_dir

    return global_config_dir() / "upgrade.json"


def read_upgrade(path: Path | None = None) -> dict | None:
    """The last upgrade's outcome, or None when nothing was recorded."""
    path = path or record_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("outcome") not in {"ok", "failed", "partial"}:
        return None
    return data


def outcome_line(data: dict | None) -> str | None:
    """What doctor and status say, or None when the last upgrade worked."""
    if not data or data.get("outcome") == "ok":
        return None
    reason = " ".join(str(data.get("reason") or "no reason recorded").split())
    kept = str(data.get("kept") or "").strip()
    suffix = f" ({kept} still installed)" if kept else ""
    if data["outcome"] == "partial":
        return f"last upgrade incomplete: {reason}{suffix}"
    return f"last upgrade failed: {reason}{suffix}"


def write_upgrade(data: dict, path: Path | None = None) -> None:
    path = path or record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def atomic_install(
    spec: str, *, bin_dir: Path | None = None, tools_dir: Path | None = None, run=None, extra: tuple[str, ...] = ()
) -> dict:
    """Install `spec` beside the current tool and switch only after it runs.

    `run(argv, env)` is `uv`. Tests pass a fake. `--force` is never forwarded:
    that flag is what removes the live tool first.
    """
    run = run or _subprocess
    extra = tuple(arg for arg in extra if arg != "--force")
    if bin_dir is None:
        bin_dir = Path(_tool_dir(run, "--bin"))
    if tools_dir is None:
        tools_dir = Path(_tool_dir(run))
    bin_dir, tools_dir = Path(bin_dir), Path(tools_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)
    kept = _version_of(bin_dir / "co")
    stage = Path(tempfile.mkdtemp(prefix="co-upgrade-", dir=str(tools_dir)))
    try:
        return _install(spec, bin_dir, tools_dir, stage, run, extra, kept)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _install(spec, bin_dir, tools_dir, stage, run, extra, kept) -> dict:
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(stage / "tools")
    env["UV_TOOL_BIN_DIR"] = str(stage / "bin")
    done = run(_argv(extra, spec), env)
    if done.returncode != 0:
        return _record("failed", _last_line(done), spec, kept)
    new_co = stage / "bin" / "co"
    ok, why = _verify(new_co)
    if not ok:
        return _record("failed", why, spec, kept)
    _relocate(stage, tools_dir, new_co)
    ok, why = _verify(new_co)
    if not ok:
        return _record("failed", why or "new install did not run after it was moved", spec, kept)
    return _swap(bin_dir, stage / "bin", spec, kept)


def _argv(extra: tuple[str, ...], spec: str) -> list[str]:
    argv = ["uv", "tool", "install", "--quiet"]
    if "--python" not in extra:
        argv += ["--python", ">=3.11"]
    return [*argv, *extra, spec]


def _swap(bin_dir: Path, staged_bin: Path, spec: str, kept: str) -> dict:
    previous: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for shim in sorted(path for path in staged_bin.iterdir() if path.is_file()):
            dest = bin_dir / shim.name
            if dest.exists():
                backup = dest.with_name(f".{shim.name}.previous")
                shutil.copy2(dest, backup)
                previous[dest] = backup
            incoming = dest.with_name(f".{shim.name}.incoming")
            shutil.copy2(shim, incoming)
            os.chmod(incoming, 0o755)
            os.replace(incoming, dest)
            published.append(dest)
        ok, why = _verify(bin_dir / "co")
    except OSError as error:
        _restore(previous, published)
        return _record("partial", str(error), spec, kept)
    if not ok:
        _restore(previous, published)
        return _record("partial", why, spec, kept)
    for backup in previous.values():
        backup.unlink(missing_ok=True)
    return _record("ok", "", spec, kept, version=_version_of(bin_dir / "co"))


def _restore(previous: dict[Path, Path], published: list[Path]) -> None:
    for dest, backup in previous.items():
        os.replace(backup, dest)
    for dest in published:
        if dest not in previous and dest.exists():
            dest.unlink()


def _relocate(stage: Path, tools_dir: Path, new_co: Path) -> None:
    """Move the staged environment to a permanent path and point shims at it.

    The live tool directory is left in place until the shim is swapped, so a
    failure here still runs the previous `co`.
    """
    source = stage / "tools" / "connectonion"
    if not source.is_dir():
        return
    version = _version_of(new_co).split()[-1] if _version_of(new_co) else "new"
    dest = tools_dir / f"connectonion-{version}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(source), dest)
    for shim in (stage / "bin").iterdir():
        if not shim.is_file():
            continue
        text = shim.read_text(encoding="utf-8", errors="surrogateescape")
        rewritten = text.replace(str(source), str(dest), 1)
        if rewritten != text:
            shim.write_text(rewritten, encoding="utf-8", errors="surrogateescape")
            os.chmod(shim, 0o755)


def _verify(co: Path) -> tuple[bool, str]:
    """True when `co --version` runs, and a Python entry point can import."""
    if not co.is_file():
        return False, "new install did not produce co"
    try:
        done = subprocess.run([str(co), "--version"], capture_output=True, text=True, timeout=30)
    except OSError as error:
        return False, f"new install did not run: {error}"
    if done.returncode != 0:
        return False, _last_line(done) or "new install did not run"
    python = _shebang(co)
    if python and "python" in Path(python).name:
        try:
            imported = subprocess.run([python, "-c", "import connectonion"], capture_output=True, text=True, timeout=30)
        except OSError as error:
            return False, f"new install cannot import connectonion: {error}"
        if imported.returncode != 0:
            return False, "new install cannot import connectonion: " + (_last_line(imported) or "import failed")
    return True, ""


def _shebang(co: Path) -> str:
    try:
        first = co.read_text(encoding="utf-8", errors="surrogateescape").splitlines()[0]
    except (OSError, IndexError):
        return ""
    if not first.startswith("#!"):
        return ""
    return first[2:].strip().split()[0]


def _version_of(co: Path) -> str:
    if not co.is_file():
        return ""
    try:
        done = subprocess.run([str(co), "--version"], capture_output=True, text=True, timeout=30)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _record(outcome: str, reason: str, spec: str, kept: str, **extra) -> dict:
    data = {
        "outcome": outcome,
        "reason": " ".join(str(reason).split()),
        "spec": spec,
        "kept": kept,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **extra,
    }
    write_upgrade(data)
    return data


def _last_line(done) -> str:
    text = (getattr(done, "stderr", "") or "") + "\n" + (getattr(done, "stdout", "") or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[-1] if lines else "uv tool install failed")[:500]


def _tool_dir(run, *args: str) -> str:
    done = run(["uv", "tool", "dir", *args], os.environ.copy())
    if done.returncode != 0:
        raise RuntimeError(_last_line(done) or "uv tool dir failed")
    return (done.stdout or "").strip().splitlines()[-1]


def _subprocess(argv, env):
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=600)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: python -m connectonion.tool_upgrade SPEC [uv options]", file=sys.stderr)
        return 2
    result = atomic_install(argv[0].strip("'\""), extra=tuple(argv[1:]))
    if result["outcome"] != "ok":
        print(outcome_line(result) or result["reason"], file=sys.stderr)
        return 1
    print(result.get("version") or "ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
