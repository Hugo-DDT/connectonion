"""A link to a private topic uses the graph's masked label (#3387).

At 遮敏感 the topic page is already 「个人事项 N」. Insight prose, related knowledge, backlinks,
search hits and breadcrumbs were still printing the real title, and so were title and aria-label.
At 全部显示 the same link shows the title.

Opt in with CO_REM_BROWSER_TEST=1. An invented notebook: one person whose Insight links to two
private topics and one public topic.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CO_REM_BROWSER_TEST") != "1",
    reason="opt in with CO_REM_BROWSER_TEST=1; requires installed Chrome",
)

WOLF = "Wolfsbane ledger"
FUND = "Thistlebrook fund"
PUBLIC = "Harbour pilot"
TITLES = (WOLF, FUND)


def notebook(root):
    from connectonion.rem.config import prepare
    from connectonion.rem.files import Notebook
    prepare(root)
    nb = Notebook(root)
    nb.write("people/mara-ostrowski.md",
             "# Mara Ostrowski\n\n## Insight\n"
             f"- Mara keeps the [{WOLF}](../knowledge/wolfsbane-ledger.md) beside the "
             f"[{FUND}](../knowledge/thistlebrook-fund.md) and the [{PUBLIC}](../knowledge/harbour-pilot.md) [1].\n\n"
             "## Sources\n- [1] gmail:m1 — 2026-02-03\n")
    nb.write("knowledge/wolfsbane-ledger.md", f"# {WOLF} [personal]\n\nA private topic [1].\n\n## Sources\n- [1] gmail:m1\n")
    nb.write("knowledge/thistlebrook-fund.md", f"# {FUND} [sensitive]\n\nAnother private topic [1].\n\n## Sources\n- [1] gmail:m1\n")
    nb.write("knowledge/harbour-pilot.md",
             f"# {PUBLIC}\n\nA public topic [1].\n\n## Insight\n"
             f"- It sits next to the [{WOLF}](wolfsbane-ledger.md) [1].\n\n"
             "Related: [Wolfsbane ledger](wolfsbane-ledger.md)\n\n"
             "## Sources\n- [1] gmail:m1\n")
    return root


@pytest.fixture
def page(tmp_path, monkeypatch):
    from patchright.sync_api import sync_playwright
    from connectonion.rem.reader import render
    monkeypatch.setattr("connectonion.rem.service.mail_available", lambda kind: False)
    root = notebook(tmp_path / "rem")
    path = tmp_path / "reader.html"
    path.write_text(render(root, local=True), encoding="utf-8")
    with sync_playwright() as api:
        browser = api.chromium.launch(channel="chrome", headless=True)
        tab = browser.new_page(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        errors = []
        tab.on("pageerror", lambda error: errors.append(str(error)))
        tab.route("http*://**/*", lambda route: route.abort())
        tab.goto(path.as_uri() + "#r=people%2Fmara-ostrowski.md")
        tab.locator("#main h1").first.wait_for()
        yield tab, path.as_uri()
        browser.close()
        assert not errors, errors


def _leaks(tab):
    """DOM text, title and aria-label that still carry a private topic's name."""
    return tab.evaluate(
        """titles => {
          const hits = [];
          const consider = (where, text, title, label) => {
            const blob = [text || "", title || "", label || ""].join("\\n");
            for (const secret of titles) if (blob.includes(secret))
              hits.push({ where, text: (text || "").slice(0, 240), title, label, secret });
          };
          for (const el of document.querySelectorAll("#main a, #crumb a, .page-crumb, .gx-crumb, .ov-crumb"))
            consider(el.getAttribute("href") || el.className, el.textContent, el.getAttribute("title"), el.getAttribute("aria-label"));
          for (const el of document.querySelectorAll("[title], [aria-label]"))
            for (const name of ["title", "aria-label"]) {
              const value = el.getAttribute(name);
              if (!value) continue;
              for (const secret of titles) if (value.includes(secret))
                hits.push({ where: name, text: "", title: name === "title" ? value : "", label: name === "aria-label" ? value : "", secret });
            }
          consider("document.title", document.title, "", "");
          return hits;
        }""",
        list(TITLES),
        isolated_context=False,
    )


def _link_text(tab, record):
    href = "#r=" + record.replace("/", "%2F")
    return tab.evaluate(
        """href => [...document.querySelectorAll('#main a')].filter(a => a.getAttribute('href') === href).map(a => a.textContent)""",
        href,
        isolated_context=False,
    )


def test_insight_links_use_the_masked_label_at_cover_and_the_title_at_show_all(page):
    tab, uri = page
    assert tab.evaluate("privacyLevel", isolated_context=False) == "cover"
    assert tab.locator("#privacy-level").inner_text().strip() == "遮敏感"
    tab.locator(".deep-note .note a").first.wait_for()
    leaks = _leaks(tab)
    assert not leaks, leaks
    assert PUBLIC in tab.locator("#main").inner_text()
    wolf = " ".join(_link_text(tab, "knowledge/wolfsbane-ledger.md"))
    fund = " ".join(_link_text(tab, "knowledge/thistlebrook-fund.md"))
    assert "个人事项 1" in wolf and WOLF not in wolf
    assert "个人事项 2" in fund and FUND not in fund
    # The number is the graph's own, not a second sequence.
    labels = tab.evaluate(
        """() => Object.fromEntries(graphModel().nodes.filter(graphHidden).map(n => [n.id, graphTitle(n)]))""",
        isolated_context=False,
    )
    assert labels["knowledge/wolfsbane-ledger.md"] == "个人事项 1"
    assert labels["knowledge/thistlebrook-fund.md"] == "个人事项 2"

    # Search results, the topic page (its heading and the tab title) and the entries list.
    tab.goto(uri + "#q=" + WOLF.replace(" ", "%20"))
    tab.locator("#main h1").first.wait_for()
    assert not _leaks(tab), _leaks(tab)
    tab.goto(uri + "#r=knowledge%2Fwolfsbane-ledger.md")
    tab.locator("#main h1").first.wait_for()
    assert tab.locator("#main h1").first.inner_text().strip() == "个人事项 1"
    assert WOLF not in (tab.locator("#crumb").inner_text() + tab.locator("#main .gx-crumb").inner_text())
    assert not _leaks(tab), _leaks(tab)
    tab.goto(uri + "#c=knowledge&view=entries")
    tab.locator("#main").wait_for()
    assert not _leaks(tab), _leaks(tab)

    tab.goto(uri + "#r=people%2Fmara-ostrowski.md")
    tab.locator("#main h1").first.wait_for()
    tab.evaluate("setPrivacy('all', { save: false })", isolated_context=False)
    tab.wait_for_function("privacyLevel === 'all'")
    tab.locator(".deep-note .note a").first.wait_for()
    shown = " ".join(_link_text(tab, "knowledge/wolfsbane-ledger.md"))
    assert WOLF in shown
    assert FUND in " ".join(_link_text(tab, "knowledge/thistlebrook-fund.md"))
