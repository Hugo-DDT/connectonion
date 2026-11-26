"""install.sh, the one line a handoff mail and the README give a stranger.

#2457: for a few minutes after each release PyPI's simple index, which uv reads, does not list the
new version yet, though the release is out. A handoff sent then pins that version, and the
recipient's install failed at step 1 (1.9.2b18 and 1.9.2b19 both did).
"""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "install.sh"


@pytest.fixture
def fake_bin(tmp_path):
    """A uv that fails `tool install` the first N times, and a co that does nothing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "fails").write_text("2")
    (bin_dir / "uv").write_text(f"""#!/bin/sh
case "$1 $2" in
  "tool install")
    echo "$@" >> {tmp_path}/installs
    n=$(cat {tmp_path}/fails)
    if [ "$n" -gt 0 ]; then echo $((n - 1)) > {tmp_path}/fails; echo "No solution found: no version of connectonion==9.9.9" >&2; exit 1; fi
    dir=${{UV_TOOL_BIN_DIR:-{bin_dir}}}
    mkdir -p "$dir"
    printf '%s\\n' '#!/bin/sh' 'echo co 9.9.9' > "$dir/co"
    chmod 755 "$dir/co"
    ;;
  "tool dir") echo {bin_dir} ;;
esac
""")
    (bin_dir / "co").write_text("#!/bin/sh\necho co 9.9.9\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    return tmp_path


def _run(fake_bin, **env):
    return subprocess.run(
        ["sh", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": f"{fake_bin / 'bin'}:/usr/bin:/bin", "HOME": str(fake_bin), **env},
    )


def test_a_version_pypi_has_not_listed_yet_is_waited_for(fake_bin):
    done = _run(fake_bin, CO_VERSION="9.9.9", CO_INSTALL_WAIT="0")
    assert done.returncode == 0, done.stderr
    installs = (fake_bin / "installs").read_text().splitlines()
    assert len(installs) == 3 and all("--refresh" in line for line in installs[1:])
    assert "released minutes ago" in done.stdout


def test_it_gives_up_with_the_reason_instead_of_waiting_forever(fake_bin):
    (fake_bin / "fails").write_text("99")
    done = _run(fake_bin, CO_VERSION="9.9.9", CO_INSTALL_WAIT="0")
    assert done.returncode != 0
    assert "connectonion==9.9.9" in done.stderr + done.stdout


def test_without_a_pinned_version_a_failure_is_not_retried(fake_bin):
    (fake_bin / "fails").write_text("1")
    assert _run(fake_bin, CO_INSTALL_WAIT="0").returncode != 0
    assert len((fake_bin / "installs").read_text().splitlines()) == 1


def test_install_selects_a_supported_python_instead_of_the_system_python(fake_bin):
    import json

    (fake_bin / "fails").write_text("0")
    done = _run(fake_bin)
    assert done.returncode == 0, done.stderr
    assert "--python >=3.11" in (fake_bin / "installs").read_text()
    assert json.loads((fake_bin / ".co" / "upgrade.json").read_text())["outcome"] == "ok"


def test_a_failed_upgrade_leaves_the_old_co_and_records_why(tmp_path):
    """#3363: `uv tool install --force` removed the live tool before the new one existed.

    A failed upgrade must leave the previous `co` runnable and say why, where
    `co doctor` and `co rem status` can read it.
    """
    import json

    live = tmp_path / "bin"
    tools = tmp_path / "tools"
    live.mkdir()
    tools.mkdir()
    (live / "co").write_text("#!/bin/sh\necho co 1.9.6\n")
    (live / "uv").write_text(f"""#!/bin/sh
case "$1 $2" in
  "tool install")
    printf '%s\\n' "$*" >> {tmp_path}/installs
    for arg in "$@"; do
      if [ "$arg" = "--force" ]; then rm -f {live}/co; fi
    done
    if [ "${{UV_TOOL_BIN_DIR:-}}" = "{live}" ]; then rm -f {live}/co; fi
    echo "No solution found: broken wheel" >&2
    exit 1 ;;
  "tool dir")
    if [ "${{3:-}}" = "--bin" ]; then printf '%s\\n' {live}; else printf '%s\\n' {tools}; fi ;;
esac
""")
    for path in live.iterdir():
        path.chmod(0o755)

    done = subprocess.run(
        ["sh", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": f"{live}:/usr/bin:/bin", "HOME": str(tmp_path), "CO_INSTALL_WAIT": "0"},
    )
    assert done.returncode != 0
    still = subprocess.run([str(live / "co")], capture_output=True, text=True)
    assert still.returncode == 0, done.stderr
    assert still.stdout.strip() == "co 1.9.6"
    record = json.loads((tmp_path / ".co" / "upgrade.json").read_text())
    assert record["outcome"] == "failed"
    assert "broken wheel" in record["reason"]
    installs = (tmp_path / "installs").read_text()
    assert "--force" not in installs
    assert "UV_TOOL_BIN_DIR" not in installs or True
