"""A scheduled turn must not crash while an upgrade has removed connectonion (#3363).

The launchd job fired in the window where `co` was gone and died with
`No module named 'connectonion'`. The wrapper logs one line and retries in a
few minutes, and the log has no traceback.
"""

import os
import plistlib
import subprocess
from pathlib import Path

from connectonion.rem.config import default_config
from connectonion.rem.schedule import Launchd


def _python(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


def _job(tmp_path, monkeypatch, python: Path):
    monkeypatch.setattr("shutil.which", lambda name: None)
    scheduler = Launchd(
        agents_dir=tmp_path / "LaunchAgents",
        uid=501,
        run=lambda *a, **k: None,
        command=[str(python), "-m", "connectonion.cli.main"],
    )
    root = tmp_path / "rem"
    plist = plistlib.loads(scheduler.render(root, default_config()).encode())
    return root, plist["ProgramArguments"][2:]


def _run(args, tmp_path):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HOME": str(tmp_path), "CO_SCHEDULE_RETRY_SECONDS": "0", "PATH": "/usr/bin:/bin"},
    )


def test_a_missing_module_skips_and_retries_without_a_traceback(tmp_path, monkeypatch):
    probes = tmp_path / "probes"
    python = _python(
        tmp_path / "python",
        f"""#!/bin/sh
n=$(cat {probes} 2>/dev/null || echo 0)
echo $((n + 1)) > {probes}
echo "Traceback (most recent call last):" >&2
echo "ModuleNotFoundError: No module named 'connectonion'" >&2
exit 1
""",
    )
    _root, args = _job(tmp_path, monkeypatch, python)
    done = _run(args, tmp_path)
    assert done.returncode == 0, done.stderr
    assert "Traceback" not in done.stdout + done.stderr
    assert "ModuleNotFoundError" not in done.stdout + done.stderr
    assert done.stdout.count("co 正在升级或缺失，本轮跳过，稍后重试") == 2
    assert probes.read_text().strip() == "2"


def test_a_module_that_returns_on_the_retry_runs_the_turn(tmp_path, monkeypatch):
    probes = tmp_path / "probes"
    python = _python(
        tmp_path / "python",
        f"""#!/bin/sh
n=$(cat {probes} 2>/dev/null || echo 0)
echo $((n + 1)) > {probes}
if [ "$1" = "-c" ] && [ "$n" = "0" ]; then
  echo "Traceback (most recent call last):" >&2
  echo "ModuleNotFoundError: No module named 'connectonion'" >&2
  exit 1
fi
if [ "$1" = "-c" ]; then
  exit 0
fi
echo TURN
exit 0
""",
    )
    _root, args = _job(tmp_path, monkeypatch, python)
    done = _run(args, tmp_path)
    assert done.returncode == 0, done.stderr
    assert "Traceback" not in done.stdout + done.stderr
    assert "TURN" in done.stdout
    assert "co 正在升级或缺失，本轮跳过，稍后重试" in done.stdout
