"""A finished task's summary, reason, reply and report keep the item's privacy (#3436).

An open item can be marked sensitive while the run that came from it stores a
one-line summary, a reason and a reply that restate the item without the mark.
Waiting on you curtained the title at 遮敏感 and dropped it at 只看公开, then
still printed the summary beside "做完了". Public only must not reveal that
context. Cover sensitive curtains a sensitive result and still shows a personal
one. Show all shows every result, with no raw mark. Everything here is invented.
"""

import os
from pathlib import Path

import pytest

from connectonion.rem.census import threads
from connectonion.rem.config import prepare
from connectonion.rem.files import Notebook, write_json
from connectonion.rem.reader import write_reader
from connectonion.rem.tasks import directory, identity
from connectonion.rem.threads import done_key

pytestmark = pytest.mark.skipif(
    os.environ.get("CO_REM_BROWSER_TEST") != "1",
    reason="opt in with CO_REM_BROWSER_TEST=1; requires installed Chrome",
)

RECORD = "people/wren-hale.md"
PAGE = """# Wren Hale

## Facts
- Email: wren@example.test [1]

## Open threads
- You owe the auditor the zephyrcove settlement figures [sensitive] [1].
- You owe the auditor a thistlebrook call before ten [personal] [1].
- You owe the auditor the harbour pilot agenda [1].

## Sources
- [1] file:/notes/wren.md — 2026-09-30
"""
# Words that belong to one item. The derived summary, reason and reply restate
# them without a privacy mark — that is the leak.
SENSITIVE = "zephyrcove"
PERSONAL = "thistlebrook"
PUBLIC = "harbour"
TOKENS = ["[sensitive]", "[personal]", "［sensitive］", "［personal］"]

READ = r"""() => {
  const main = document.querySelector('#main');
  const seen = [];
  const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const host = n.parentElement;
    if (!host || host.closest('[hidden], script, style, .curtain:not(.lifted)')) continue;
    const style = getComputedStyle(host);
    if (style.display === 'none' || style.visibility === 'hidden' || style.color === 'rgba(0, 0, 0, 0)') continue;
    if (!host.getClientRects().length) continue;
    seen.push(n.textContent);
  }
  for (const field of main.querySelectorAll('textarea, input')) {
    if (field.closest('.curtain:not(.lifted), [hidden]')) continue;
    const style = getComputedStyle(field);
    if (style.display === 'none' || style.visibility === 'hidden' || style.color === 'rgba(0, 0, 0, 0)') continue;
    seen.push(field.value || '');
  }
  for (const el of main.querySelectorAll('[title], [aria-label]')) {
    if (el.closest('.curtain:not(.lifted)')) continue;
    seen.push(el.getAttribute('title') || '', el.getAttribute('aria-label') || '');
  }
  return seen.join('\n').toLowerCase();
}"""


def _receipt(root, text, summary, reason, reply):
    key = done_key(RECORD, text)
    folder = directory(root, identity(key))
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    deliverable = folder / "result.md"
    deliverable.write_text(f"{summary}\n\n```reply\n{reply}\n```\n", encoding="utf-8")
    write_json(folder / "receipt.json", {
        "id": identity(key), "result": "completed", "agent": "codex", "by": "owner",
        "key": key, "keys": [key], "record": RECORD, "title": "Wren Hale", "text": text,
        "reason": reason, "finished_at": "2026-11-23T12:00:00+00:00",
        "deliverable": str(deliverable), "last_message": str(folder / "last.md"),
        "log": str(folder / "codex.jsonl"), "receipt": str(folder / "receipt.json"),
    })


def _reader(tmp_path, monkeypatch):
    monkeypatch.setattr("connectonion.rem.service.mail_available", lambda kind: False)
    root = tmp_path / "rem"
    prepare(root)
    Notebook(root).write(RECORD, PAGE)
    items = threads(Notebook(root).read(RECORD))
    derived = {
        SENSITIVE: ("已整理 zephyrcove 结算数字，待审计员核对", "原因是 zephyrcove 的数字还要对一遍", "回复里写了 zephyrcove 的数字"),
        PERSONAL: ("已记下 thistlebrook 的通话时间", "原因是 thistlebrook 的时间还没定", "回复里约了 thistlebrook 的电话"),
        PUBLIC: ("已整理 harbour 议程，可以发出", "原因是 harbour 的议程可以发出", "回复里附了 harbour 的议程"),
    }
    for text in items:
        token = next(token for token in derived if token in text)
        _receipt(root, text, *derived[token])
    path = write_reader(root)
    html = path.read_text(encoding="utf-8")
    assert "已整理 zephyrcove" in html  # the receipt is on the page, not only in the notebook
    return path


def _open(api, path, width):
    browser = api.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(
        viewport={"width": width, "height": 900 if width > 500 else 844},
        locale="zh-CN", reduced_motion="reduce", is_mobile=width < 500, has_touch=width < 500)
    page.goto(path.as_uri() + "#view=open")
    page.locator("#main h1").first.wait_for()
    page.evaluate("() => setInterfaceLanguage('zh')", isolated_context=False)
    page.locator("#main").get_by_text("等你处理").first.wait_for()
    return browser, page


def _show(page, level, route):
    page.evaluate("(level) => setPrivacy(level, { save: false })", level, isolated_context=False)
    page.evaluate("(route) => { location.hash = route; }", route, isolated_context=False)
    page.locator("#main h1").first.wait_for()
    page.wait_for_timeout(250)
    # The report is what See result draws. A snapshot has no Host to fetch it, so the test asks the
    # same function with the derived report and lets the page curtain it.
    page.evaluate("""() => {
      document.getElementById('task-privacy-report')?.remove();
      const row = (REM.today_queue || []).find(item => (item.text || '').includes('zephyrcove'));
      const task = row && (row.outcome?.kind === 'task' ? row.outcome.task : row.task);
      if (!task) return;
      const report = taskReport('完整报告写了 zephyrcove 的结算过程，没有标记。', task);
      report.id = 'task-privacy-report';
      document.getElementById('main').appendChild(report);
    }""", isolated_context=False)
    page.wait_for_timeout(100)


@pytest.mark.parametrize("width", [1440, 390])
def test_public_only_hides_a_private_task_result_and_the_other_levels_keep_theirs(tmp_path, monkeypatch, width):
    from patchright.sync_api import sync_playwright

    path = _reader(tmp_path, monkeypatch)
    with sync_playwright() as api:
        browser, page = _open(api, path, width)
        _show(page, "cover", "#view=open")
        covered = page.evaluate(READ, isolated_context=False)
        assert SENSITIVE not in covered  # title and the derived summary are curtained
        assert PERSONAL in covered and PUBLIC in covered  # personal stays readable at 遮敏感
        assert not [token for token in TOKENS if token in covered]
        assert page.locator("#main .handed .curtain").count() >= 1

        _show(page, "public", "#view=open")
        public_waiting = page.evaluate(READ, isolated_context=False)
        assert SENSITIVE not in public_waiting and PERSONAL not in public_waiting
        assert PUBLIC in public_waiting  # an unmarked item's summary stays
        assert "做完了" in public_waiting  # the completion label is not itself the secret
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        _show(page, "public", "#")
        public_today = page.evaluate(READ, isolated_context=False)
        assert SENSITIVE not in public_today and PERSONAL not in public_today
        assert PUBLIC in public_today

        _show(page, "all", "#view=open")
        shown = page.evaluate(READ, isolated_context=False)
        assert SENSITIVE in shown and PERSONAL in shown and PUBLIC in shown
        assert not [token for token in TOKENS if token in shown]
        browser.close()
