"""A failed or partial upgrade is visible from `co doctor` and `co rem status` (#3363)."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.text import Text

from connectonion.cli.commands.rem_status import card
from connectonion.rem.config import prepare
from connectonion.rem.service import approve_sources, status
from connectonion.tool_upgrade import atomic_install, outcome_line


def _co(path: Path, version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho {version}\n")
    path.chmod(0o755)


def test_a_failed_install_leaves_the_previous_co_and_names_the_reason(tmp_path):
    live = tmp_path / "bin"
    _co(live / "co", "co 1.9.6")
    seen = []

    def run(argv, env):
        seen.append((argv, env))
        if "--force" in argv or env.get("UV_TOOL_BIN_DIR") == str(live):
            (live / "co").unlink()

        class Done:
            returncode = 1
            stdout = ""
            stderr = "No solution found: broken wheel"

        return Done()

    result = atomic_install("connectonion[rem,whatsapp]==9.9.9", bin_dir=live, tools_dir=tmp_path / "tools", run=run)
    assert result["outcome"] == "failed"
    assert "broken wheel" in result["reason"]
    assert "--force" not in seen[0][0]
    assert seen[0][1]["UV_TOOL_BIN_DIR"] != str(live)
    still = os.popen(f"{live / 'co'}").read().strip()
    assert still == "co 1.9.6"
    assert "broken wheel" in outcome_line(result)


def test_a_verified_install_replaces_co_only_after_it_runs(tmp_path):
    live = tmp_path / "bin"
    _co(live / "co", "co 1.9.6")

    def run(argv, env):
        assert "--force" not in argv
        staged = Path(env["UV_TOOL_BIN_DIR"])
        staged.mkdir(parents=True, exist_ok=True)
        (staged / "co").write_text("#!/bin/sh\necho co 9.9.9\n")
        (staged / "co").chmod(0o755)

        class Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return Done()

    result = atomic_install("connectonion==9.9.9", bin_dir=live, tools_dir=tmp_path / "tools", run=run)
    assert result["outcome"] == "ok"
    assert os.popen(f"{live / 'co'}").read().strip() == "co 9.9.9"
    assert outcome_line(result) is None


def test_a_swap_that_does_not_run_rolls_back_and_is_partial(tmp_path):
    live = tmp_path / "bin"
    _co(live / "co", "co 1.9.6")

    def run(argv, env):
        staged = Path(env["UV_TOOL_BIN_DIR"])
        staged.mkdir(parents=True, exist_ok=True)
        # Works in the staging bin; fails once copied onto the live path.
        (staged / "co").write_text(
            '#!/bin/sh\ncase "$0" in\n  *co-upgrade-*) echo co 9.9.9; exit 0 ;;\n'
            "  *) echo 'live co did not start' >&2; exit 1 ;;\nesac\n"
        )
        (staged / "co").chmod(0o755)

        class Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return Done()

    result = atomic_install("connectonion==9.9.9", bin_dir=live, tools_dir=tmp_path / "tools", run=run)
    assert result["outcome"] == "partial"
    assert os.popen(f"{live / 'co'}").read().strip() == "co 1.9.6"
    assert "live co did not start" in result["reason"] or "did not run" in result["reason"]


def test_doctor_and_rem_status_say_the_upgrade_failed(tmp_path, monkeypatch):
    record = {
        "outcome": "failed",
        "reason": "No solution found: broken wheel",
        "spec": "connectonion[rem,whatsapp]==9.9.9",
        "kept": "co 1.9.6",
    }
    path = Path.home() / ".co" / "upgrade.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))

    from connectonion.cli.commands.doctor_commands import handle_doctor

    printed = []
    with (
        patch("connectonion.cli.commands.doctor_commands.console") as console,
        patch("connectonion.cli.commands.doctor_commands.shutil.which", return_value=None),
        patch("connectonion.cli.commands.doctor_commands.requests.get") as get,
    ):
        get.return_value.status_code = 200
        console.print.side_effect = lambda *args, **kwargs: printed.append(" ".join(str(arg) for arg in args))
        with patch.dict(os.environ, {"OPENONION_API_KEY": ""}):
            code = handle_doctor()
    text = "\n".join(printed)
    assert "broken wheel" in text
    assert "last upgrade failed" in text
    assert code == 1

    root = tmp_path / "rem"
    monkeypatch.setattr("connectonion.rem.service.codex_sessions_root", lambda: tmp_path / "sessions")
    monkeypatch.setattr("connectonion.rem.service.claude_projects_root", lambda: tmp_path / "no-claude")
    (tmp_path / "sessions").mkdir()
    prepare(root)
    approve_sources(root)
    value = status(root)
    assert value["upgrade"]["outcome"] == "failed"
    shown = Text.from_markup(card(root, value, lambda args: "co rem " + " ".join(args))).plain
    assert "broken wheel" in shown
    assert "last upgrade failed" in shown


@pytest.mark.parametrize("outcome", ["partial"])
def test_a_partial_install_is_reported_too(tmp_path, monkeypatch, outcome):
    path = Path.home() / ".co" / "upgrade.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "outcome": outcome,
                "reason": "swap stopped halfway",
                "kept": "co 1.9.6",
            }
        )
    )
    from connectonion.tool_upgrade import read_upgrade

    assert "incomplete" in outcome_line(read_upgrade())
    assert "swap stopped halfway" in outcome_line(read_upgrade())
