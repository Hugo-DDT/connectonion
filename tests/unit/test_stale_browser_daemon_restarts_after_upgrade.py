"""A browser daemon keeps the packages it imported at start (#3366).

Upgrading co or onionwright on disk does not change the process that is
already answering the socket. Status has to name that process's versions
and when it started, and the CLI has to restart it when they differ from
what is installed — without throwing away other sessions' reserved tabs.
"""

import importlib.metadata
import json
import time

import pytest

from connectonion._version import __version__
from connectonion.cli.browser_agent import client
from connectonion.cli.browser_agent.daemon import BrowserDaemon
from connectonion.useful_tools.browser_tools._async_browser import AsyncBrowserCore

OLD_CO = "1.9.7rc14"
OLD_ONIONWRIGHT = "0.0.16"
STARTED = "2026-11-21T10:52:00Z"
STARTED_AT = 1_795_258_320  # 2026-11-21 10:52:00 UTC


def _installed_onionwright() -> str:
    try:
        return importlib.metadata.version("onionwright")
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _sentence(co: str = OLD_CO, onionwright: str = OLD_ONIONWRIGHT) -> str:
    return (
        f"this daemon runs co {co} / onionwright {onionwright}; "
        f"installed is co {__version__} / onionwright {_installed_onionwright()}"
    )


def _status(*, browser: str = "not open", versions: bool = True, tabs: str = "Tabs: none") -> str:
    lines = [f"Browser: {browser} · headless=false"]
    if versions:
        lines.append(f"Daemon: co {OLD_CO} / onionwright {OLD_ONIONWRIGHT} · started {STARTED}")
    lines.append("Engine: requested=auto · resolved=not-started · reason=not_started")
    lines.append(tabs)
    return "\n".join(lines)


def _script(replies: dict):
    calls = []

    def request(line, **kwargs):
        calls.append(line)
        for prefix, reply in replies.items():
            if line == prefix or line.startswith(prefix):
                return reply
        return 1, f"unexpected {line}"

    return calls, request


@pytest.fixture
def alive(monkeypatch):
    """A daemon process is up, so the CLI has something it might restart."""
    monkeypatch.setattr(client, "_owner_alive", lambda *args, **kwargs: True)
    monkeypatch.delenv("CO_BROWSER_DAEMON_PID", raising=False)


class _Browser:
    _headless = False
    _tab_meta = {}

    def _context_is_alive(self):
        return False

    def tab_status(self):
        return "Tabs: none"


def _daemon_for_status(**attrs):
    instance = BrowserDaemon.__new__(BrowserDaemon)
    instance.browser = _Browser()
    instance.last_command = None
    for name, value in attrs.items():
        setattr(instance, name, value)
    return instance


@pytest.mark.asyncio
async def test_status_names_the_versions_the_daemon_started_with(monkeypatch):
    from connectonion.cli.browser_agent import daemon as mod

    monkeypatch.setattr(mod, "driver_stealth_status", lambda: ("ok", "1.61.2", "ok"))
    monkeypatch.setattr(mod, "installed_browser_path", lambda: "/browser")
    instance = _daemon_for_status(
        co_version=OLD_CO,
        onionwright_version=OLD_ONIONWRIGHT,
        started_at=STARTED_AT,
    )

    ok, text = await instance._status_async()

    assert ok is True
    assert f"Daemon: co {OLD_CO} / onionwright {OLD_ONIONWRIGHT} · started {STARTED}" in text


@pytest.mark.asyncio
async def test_status_still_names_versions_when_init_did_not_run(monkeypatch):
    """In-process tests build a daemon with __new__. Status must not crash."""
    from connectonion.cli.browser_agent import daemon as mod

    monkeypatch.setattr(mod, "driver_stealth_status", lambda: ("ok", "1.61.2", "ok"))
    monkeypatch.setattr(mod, "installed_browser_path", lambda: "/browser")

    ok, text = await _daemon_for_status()._status_async()

    assert ok is True
    assert "Daemon: co " in text
    assert "onionwright" in text
    assert "started " in text


def test_a_daemon_records_the_versions_it_loaded_at_start(tmp_path, monkeypatch):
    from connectonion.cli.browser_agent import daemon as mod

    monkeypatch.setattr(mod, "_co_version", lambda: "9.9.9", raising=False)
    monkeypatch.setattr(mod, "_onionwright_version", lambda: "0.0.1", raising=False)
    before = time.time()
    server = mod.BrowserDaemon(str(tmp_path / "browser.sock"), headless=True)

    assert server.co_version == "9.9.9"
    assert server.onionwright_version == "0.0.1"
    assert before <= server.started_at <= time.time()


def _pinned(tmp_path):
    server = BrowserDaemon(str(tmp_path / "browser.sock"), headless=True, engine_mode="onion")
    server.browser = AsyncBrowserCore(headless=True)
    server.co_version = OLD_CO
    server.onionwright_version = OLD_ONIONWRIGHT
    server.started_at = STARTED_AT

    async def alive():
        return True

    server.browser.is_alive = alive
    return server


def _envelope(line: str, *, engine: str) -> str:
    return json.dumps({"v": 1, "caller": "agent", "account": "", "tab": None, "line": line, "engine": engine})


@pytest.mark.asyncio
async def test_an_engine_pin_error_names_the_daemon_that_refused(tmp_path):
    server = _pinned(tmp_path)

    ok, payload = await server.dispatch_async(_envelope("get_text", engine="system"))

    assert ok == 6
    assert f"Daemon: co {OLD_CO} / onionwright {OLD_ONIONWRIGHT} · started {STARTED}" in payload


@pytest.mark.asyncio
async def test_system_go_to_keeps_registered_tabs_when_no_browser_is_open(tmp_path):
    """#3315: a pin protects running pages. With none, --engine system re-pins."""
    server = BrowserDaemon(str(tmp_path / "browser.sock"), headless=True, engine_mode="onion")
    server.browser = AsyncBrowserCore(headless=True)
    server.browser._tab_meta["cy9"] = {"who": "other", "purpose": "keep this", "opened_by": "other"}

    async def go_to(url, purpose="", who="", hours=0.0):
        return f"navigated {url}"

    server.browser.go_to = go_to

    ok, payload = await server.dispatch_async(_envelope("go_to https://example.com", engine="system"))

    assert ok is True
    assert payload == "navigated https://example.com"
    assert server.engine_mode == "system"
    assert server.browser._engine_mode == "system"
    assert server.browser._tab_meta["cy9"]["who"] == "other"


@pytest.mark.asyncio
async def test_tab_board_json_keeps_the_hold_window_for_a_restart(tmp_path):
    server = BrowserDaemon(str(tmp_path / "browser.sock"), headless=True)
    ok, name = await server.dispatch_async('tab open cy9 --who other --for "keep this" --needs 10m')
    assert ok is True and name == "cy9"

    ok, payload = await server.dispatch_async("tab ls --json")

    assert ok is True
    row = next(item for item in json.loads(payload) if item["tab"] == "cy9")
    assert row["who"] == "other"
    assert row["purpose"] == "keep this"
    assert row["needs_seconds"] >= 590


def _info(tabs=None, *, browser_open=False, co=OLD_CO, onionwright=OLD_ONIONWRIGHT) -> str:
    body = {
        "co": co,
        "onionwright": onionwright,
        "started": STARTED,
        "browser_open": browser_open,
        "tabs": [] if tabs is None else tabs,
    }
    return "daemon-info " + json.dumps(body)


LEGACY = (1, "unknown command: daemon_info")


@pytest.mark.asyncio
async def test_daemon_info_does_not_ask_chrome_whether_it_is_alive(tmp_path):
    """The check in front of every command must not be the liveness probe."""

    class Quiet:
        _headless = False
        _tab_meta = {}
        browser = None

        def _bind_session(self, key):
            return None

        def is_alive(self):
            raise AssertionError("liveness probe")

        def _context_is_alive(self):
            raise AssertionError("liveness probe")

    server = BrowserDaemon(str(tmp_path / "browser.sock"), headless=True)
    server.browser = Quiet()
    server.co_version = OLD_CO
    server.onionwright_version = OLD_ONIONWRIGHT
    server.started_at = STARTED_AT

    ok, payload = await server.dispatch_async("daemon_info")

    assert ok is True
    assert payload.startswith("daemon-info ")
    info = json.loads(payload.split(" ", 1)[1])
    assert info["co"] == OLD_CO
    assert info["browser_open"] is False
    assert await server._should_stop(True, payload) is False


def test_status_names_both_versions_and_restarts_when_nobody_holds_a_tab(alive, monkeypatch, capsys):
    calls, request = _script(
        {
            "daemon_info": (0, _info()),
            "status": (0, _status()),
            "close": (0, "No browser is open — nothing to close."),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("status") == 0

    out = capsys.readouterr().out
    assert _sentence() in out
    assert STARTED in out
    assert "would end" not in out
    assert calls == ["daemon_info", "status", "close"]


def test_a_page_command_restarts_a_stale_daemon_silently_when_no_tabs_are_reserved(alive, monkeypatch, capsys):
    calls, request = _script(
        {
            "daemon_info": (0, _info()),
            "close": (0, "No browser is open — nothing to close."),
            "go_to": (0, "navigated https://example.com"),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("go_to https://example.com") == 0

    out = capsys.readouterr().out
    assert out.strip() == "navigated https://example.com"
    assert "would end" not in out
    assert calls == ["daemon_info", "close", "go_to https://example.com"]


def test_reserved_tabs_are_carried_onto_the_new_daemon(alive, monkeypatch, capsys):
    board = [
        {"tab": "main", "who": "main", "purpose": "shared", "active_requests": []},
        {
            "tab": "cy9",
            "who": "other",
            "purpose": "keep this",
            "needs_seconds": 600,
            "active_requests": [],
        },
    ]
    calls, request = _script(
        {
            "daemon_info": (0, _info(board)),
            "close": (0, "No browser is open — nothing to close."),
            "tab open": (0, "cy9"),
            "go_to": (0, "navigated https://example.com"),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("go_to https://example.com", engine_mode="system") == 0

    opened = next(line for line in calls if line.startswith("tab open"))
    assert "cy9" in opened
    assert "--who" in opened and "other" in opened
    assert "keep this" in opened
    assert "--needs" in opened and "600s" in opened
    assert "close" in calls
    assert calls[-1] == "go_to https://example.com"
    assert "would end" not in capsys.readouterr().out


def test_live_reservations_are_not_killed_and_the_error_names_the_one_command(alive, monkeypatch, capsys):
    board = [
        {
            "tab": "cy9",
            "who": "other",
            "purpose": "keep this",
            "active_requests": [{"request_id": "r1", "line": "go_to https://example.com"}],
        },
        {"tab": "cy10", "who": "third", "purpose": "also", "active_requests": []},
    ]
    calls, request = _script(
        {
            "daemon_info": (0, _info(board)),
            "go_to": (0, "should not run"),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("go_to https://example.com") == 1

    err = capsys.readouterr().err
    assert _sentence() in err
    assert "2 tab reservations would end" in err
    assert "co browser close" in err
    assert "close" not in calls
    assert not any(line.startswith("go_to") for line in calls)


def test_an_unreadable_board_names_how_many_reservations_close_would_end(alive, monkeypatch, capsys):
    calls, request = _script(
        {
            "daemon_info": LEGACY,
            "status": (0, _status(tabs="Tabs (4):")),
            "tab ls --json": (1, "not json"),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("go_to https://example.com") == 1

    err = capsys.readouterr().err
    assert _sentence() in err
    assert "4 tab reservations would end" in err
    assert "\n  co browser close" in err
    assert calls == ["daemon_info", "status", "tab ls --json"]


def test_a_daemon_that_never_learned_to_report_versions_is_still_stale(alive, monkeypatch, capsys):
    calls, request = _script(
        {
            "daemon_info": LEGACY,
            "status": (0, _status(versions=False)),
            "tab ls --json": (0, "[]"),
            "close": (0, "No browser is open — nothing to close."),
            "go_to": (0, "navigated https://example.com"),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("go_to https://example.com") == 0

    assert calls == [
        "daemon_info",
        "status",
        "tab ls --json",
        "close",
        "go_to https://example.com",
    ]
    assert "would end" not in capsys.readouterr().out


def test_status_of_a_versionless_daemon_names_the_installed_packages(alive, monkeypatch, capsys):
    calls, request = _script(
        {
            "daemon_info": LEGACY,
            "status": (0, _status(versions=False)),
            "tab ls --json": (0, "[]"),
            "close": (0, "No browser is open — nothing to close."),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("status") == 0

    out = capsys.readouterr().out
    assert "this daemon runs co unknown / onionwright unknown" in out
    assert f"installed is co {__version__} / onionwright {_installed_onionwright()}" in out
    assert "close" in calls


def test_an_open_browser_is_left_running_and_its_engine_error_names_both_versions(alive, monkeypatch, capsys):
    calls, request = _script(
        {
            "daemon_info": (0, _info(browser_open=True)),
            "get_text": (
                6,
                "browser daemon is pinned to engine=wtf; this request asked for engine=system.",
            ),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("get_text", engine_mode="system") == 6

    err = capsys.readouterr().err
    assert _sentence() in err
    assert "pinned to engine=wtf" in err
    assert "close" not in calls
    assert "tab ls" not in " ".join(calls)


def test_a_current_daemon_is_not_restarted(alive, monkeypatch, capsys):
    calls, request = _script(
        {
            "daemon_info": (0, _info(co=__version__, onionwright=_installed_onionwright())),
            "go_to": (0, "navigated https://example.com"),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("go_to https://example.com") == 0

    assert calls == ["daemon_info", "go_to https://example.com"]
    assert "would end" not in capsys.readouterr().out


def test_close_still_reaches_the_daemon_it_was_asked_to_stop(alive, monkeypatch):
    calls, request = _script(
        {
            "close": (0, "No browser is open — nothing to close."),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("close") == 0
    assert calls == ["close"]


def test_a_supervised_daemon_is_not_restarted_by_the_client(alive, monkeypatch):
    monkeypatch.setenv("CO_BROWSER_DAEMON_PID", "4242")
    calls, request = _script(
        {
            "go_to": (0, "navigated https://example.com"),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send("go_to https://example.com") == 0
    assert calls == ["go_to https://example.com"]


def test_a_quoted_task_does_not_run_on_a_daemon_it_cannot_safely_replace(alive, monkeypatch, capsys):
    board = [
        {"tab": "cy9", "who": "other", "purpose": "keep this", "active_requests": [{"line": "go_to"}]},
    ]
    calls, request = _script(
        {
            "daemon_info": (0, _info(board)),
        }
    )
    monkeypatch.setattr(client, "_request", request)

    assert client.send('"open the homepage"') == 1

    err = capsys.readouterr().err
    assert _sentence() in err
    assert "1 tab reservation would end" in err
    assert "co browser close" in err
    assert calls == ["daemon_info"]
