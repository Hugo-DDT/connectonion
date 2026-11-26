from types import SimpleNamespace

import pytest

from connectonion.useful_tools.browser_tools import engine


def ready_resolution():
    prepared = SimpleNamespace(
        ready=True,
        capability=SimpleNamespace(
            reason="ready",
            next_action="start",
            artifact=SimpleNamespace(artifact_id="chrome/150/linux-x86_64.tar.zst"),
        ),
    )
    client = SimpleNamespace(
        client_version=engine.MIN_ONIONWRIGHT_VERSION,
        prepare=lambda revision: prepared,
    )
    return engine.resolve(
        engine.ONION,
        token_loader=lambda: "token",
        client_factory=lambda token, home: client,
    )


def test_launch_passes_the_same_prepared_result_to_onionwright(monkeypatch):
    result = ready_resolution()
    calls = []

    def fake_launch(playwright, client, revision, key, **kwargs):
        calls.append((playwright, client, revision, key, kwargs))
        return "paid-run"

    monkeypatch.setitem(
        __import__("sys").modules,
        "onionwright",
        SimpleNamespace(launch_paid=fake_launch),
    )
    launched = engine.launch(
        result,
        "playwright",
        "stable-idempotency-key",
        user_data_dir=True,
        headless=True,
    )
    assert launched == "paid-run"
    assert calls == [(
        "playwright",
        result.client,
        engine.BROWSER_REVISION,
        "stable-idempotency-key",
        {"prepared": result.prepared, "user_data_dir": True, "headless": True},
    )]


@pytest.mark.asyncio
async def test_async_launch_passes_same_prepared_result_to_onionwright(monkeypatch):
    result = ready_resolution()
    calls = []

    async def fake_launch(playwright, client, revision, key, **kwargs):
        calls.append((playwright, client, revision, key, kwargs))
        return "async-paid-run"

    monkeypatch.setitem(
        __import__("sys").modules,
        "onionwright",
        SimpleNamespace(launch_paid_async=fake_launch),
    )
    launched = await engine.launch_async(
        result,
        "async-playwright",
        "stable-idempotency-key",
        user_data_dir=True,
        headless=True,
    )
    assert launched == "async-paid-run"
    assert calls == [(
        "async-playwright",
        result.client,
        engine.BROWSER_REVISION,
        "stable-idempotency-key",
        {"prepared": result.prepared, "user_data_dir": True, "headless": True},
    )]


def test_system_resolution_cannot_cross_the_billing_boundary():
    result = engine.resolve(engine.SYSTEM)
    with pytest.raises(engine.BrowserEngineError):
        engine.launch(result, "playwright", "key")


def test_missing_onionwright_is_named_rather_than_silently_free():
    """An explicit paid request says what to install instead of going free."""
    with pytest.raises(engine.BrowserEngineError) as caught:
        engine.resolve(
            engine.ONION,
            token_loader=lambda: "token",
            client_factory=lambda token, home: (_ for _ in ()).throw(
                ModuleNotFoundError("No module named 'onionwright'")
            ),
        )
    assert caught.value.reason == engine.Reason.ONIONWRIGHT_MISSING


def test_prepare_exception_is_typed_and_explicit_onion_fails():
    class FailedClient:
        client_version = engine.MIN_ONIONWRIGHT_VERSION

        def prepare(self, revision):
            exc = RuntimeError("offline")
            exc.code = "api_unavailable"
            exc.message = "retry later"
            raise exc

    with pytest.raises(engine.BrowserEngineError) as caught:
        engine.resolve(
            engine.ONION,
            token_loader=lambda: "token",
            client_factory=lambda token, home: FailedClient(),
        )
    assert caught.value.reason == "api_unavailable"
    assert caught.value.next_action == "retry later"


def _ready_prepared():
    return SimpleNamespace(
        ready=True,
        executable="/runtimes/chrome",
        capability=SimpleNamespace(
            reason="ready",
            next_action="start",
            artifact=SimpleNamespace(artifact_id="chrome/154/linux-x86_64.tar.zst"),
            interval_usd=0.025,
            client_version=engine.MIN_ONIONWRIGHT_VERSION,
        ),
    )


def _resolve_with(client, tmp_path):
    return engine.resolve(
        engine.ONION,
        token_loader=lambda: "token",
        client_factory=lambda token, home: client,
        home=tmp_path,
    )


def test_an_uncached_artifact_announces_the_one_time_download_and_its_progress(tmp_path, capsys):
    """The first WTF launch is a download. Say so, with the size and how far it got."""

    class Client:
        client_version = engine.MIN_ONIONWRIGHT_VERSION

        def capability(self, revision):
            return SimpleNamespace(
                reason="artifact_download_required",
                cache_state="absent",
                artifact=SimpleNamespace(size_bytes=186_400_000, artifact_id="chrome/154/linux"),
            )

        def prepare(self, revision, on_progress=None):
            self.progress = on_progress
            if on_progress is not None:
                on_progress(93_200_000, 186_400_000)
            return _ready_prepared()

    client = Client()
    result = _resolve_with(client, tmp_path)

    assert result.resolved == engine.ONION
    assert client.progress is not None
    err = capsys.readouterr().err
    assert "one-time download" in err
    assert "186.4 MB" in err
    assert "50%" in err


def test_a_cached_artifact_does_not_announce_a_download(tmp_path, capsys):
    prepared = _ready_prepared()

    class Client:
        client_version = engine.MIN_ONIONWRIGHT_VERSION
        calls = 0

        def capability(self, revision):
            return SimpleNamespace(reason="ready", cache_state="ready", artifact=prepared.capability.artifact)

        def prepare(self, revision):
            self.calls += 1
            return prepared

    client = Client()
    result = _resolve_with(client, tmp_path)

    assert result.resolved == engine.ONION
    assert client.calls == 1
    assert "one-time download" not in capsys.readouterr().err


def test_a_preflight_failure_is_not_announced_as_a_download(tmp_path, capsys):
    class Client:
        client_version = engine.MIN_ONIONWRIGHT_VERSION

        def capability(self, revision):
            return SimpleNamespace(
                reason="manifest_invalid",
                cache_state="unknown",
                artifact=None,
            )

        def prepare(self, revision):
            return SimpleNamespace(ready=False, capability=self.capability(revision))

    with pytest.raises(engine.BrowserEngineError):
        _resolve_with(Client(), tmp_path)

    assert "one-time download" not in capsys.readouterr().err


def test_uncached_prepare_keeps_working_when_onionwright_has_no_progress_callback(tmp_path, capsys):
    """0.0.16's prepare(revision, **host) forwards **host into capability(), which rejects extras."""
    forwarded = []

    class Client:
        client_version = engine.MIN_ONIONWRIGHT_VERSION

        def capability(self, revision):
            return SimpleNamespace(
                reason="artifact_download_required",
                cache_state="absent",
                artifact=SimpleNamespace(size_bytes=2_500_000, artifact_id="chrome/154/linux"),
            )

        def prepare(self, revision, **host):
            forwarded.append(dict(host))
            return _ready_prepared()

    _resolve_with(Client(), tmp_path)

    assert forwarded == [{}]
    err = capsys.readouterr().err
    assert "one-time download" in err
    assert "2.5 MB" in err
