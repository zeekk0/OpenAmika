"""Real isolated Chromium DOM tests with all HTTP traffic fulfilled in memory.

No application process, credentials, hardware, or consent storage is used.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def localized_browser():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(headless=True, channel="chrome")
        except pw.Error as exc:
            pytest.skip(f"Isolated Chrome unavailable: {exc}")
        yield browser
        browser.close()


def scope_page(browser, name, *, held=False, agent=False):
    context = browser.new_context(locale="ko-KR")
    page = context.new_page()
    errors, writes = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    pages = {"tools": "ui/tools.html", "about": "ui/about.html", "flow": "speech/static/flow.html"}
    responses = {
        "/api/build_f/tools": {"enabled": False, "servers": {}, "config": {"enabled": False, "mcpServers": {}}, "log": []},
        "/api/build_f/iot": {"enabled": False, "devices": []},
    }
    from brain.iot_disclaimer import statement
    responses["/api/build_f/iot/disclaimer"] = {"version": "2026-11-03", "accepted": False, "statement": statement()}
    if held:
        responses["/api/build_f/tools"]["iot_disclaimer"] = {"version": "2026-11-03", "accepted": False, "held": ["iot"]}
    if agent:
        responses["/api/build_f/tools"]["servers"] = {"hermes": {"kind": "agent", "transport": "stdio", "enabled": True, "connected": True,
            "target": "python -m original_protocol", "persona_note": "原文 그대로", "health": {"ok": True, "version": "1.0"},
            "tools": [{"name": "original_tool", "description": "Original tool description 原文", "policy": "confirm"}]}}
        responses["/api/build_f/tools"]["log"] = [{"ts": 1, "server": "hermes", "tool": "original_tool", "ok": True, "policy": "confirmed", "result": "Original result 原文", "quote": "원래 요청"}]
    def route(request):
        url = request.request.url
        path = "/" + url.split("/", 3)[3].split("?", 1)[0]
        if request.request.method not in {"GET", "HEAD"}:
            writes.append((path, request.request.method))
            request.fulfill(status=403, body='{}', content_type="application/json")
        elif path == "/" + name:
            request.fulfill(body=(ROOT / pages[name]).read_text(), content_type="text/html")
        elif path.startswith("/ui/") and (ROOT / path.lstrip("/")).is_file():
            file = ROOT / path.lstrip("/")
            request.fulfill(body=file.read_bytes(), content_type="text/javascript" if file.suffix == ".js" else "text/css")
        else:
            request.fulfill(body=json.dumps(responses.get(path, {})), content_type="application/json")
    context.route("**/*", route)
    page.goto("http://scope.test/" + name)
    page.wait_for_timeout(150)
    return context, page, errors, writes


@pytest.mark.parametrize("name", ["tools", "about", "flow"])
def test_scope_real_dom_static_catalogs(localized_browser, name):
    context, page, errors, writes = scope_page(localized_browser, name)
    try:
        for locale in ["ko", "en", "ko"]:
            page.evaluate("locale => OAI18n.setLocale(locale)", locale)
            mismatch = page.evaluate("""() => [...document.querySelectorAll('[data-i18n]')].filter(n =>
                n.textContent !== OAI18n.t(n.dataset.i18n)).map(n => n.dataset.i18n)""")
            assert not mismatch, mismatch
        assert not errors, errors
        assert not writes, writes
    finally:
        context.close()


def test_scope_tools_preserves_drafts_and_never_accepts(localized_browser):
    context, page, errors, writes = scope_page(localized_browser, "tools")
    try:
        page.locator('.oa-mode [data-mode="pro"]').click()
        page.locator("details").filter(has=page.locator("#rawConfig")).locator("summary").click()
        page.locator("#rawConfig").fill('{"미완성": "원문 ㄱ"}')
        page.locator("#addName").fill("원본-server-name")
        page.locator("#rawConfig").focus()
        page.evaluate("""() => { const n=document.querySelector('#rawConfig'); window.originalDraft=n;
          n.setSelectionRange(2,5); n.dispatchEvent(new CompositionEvent('compositionstart',{data:'ㄱ'})); }""")
        for locale in ["en", "ko"]:
            page.evaluate("locale => OAI18n.setLocale(locale)", locale)
        assert page.locator("#rawConfig").input_value() == '{"미완성": "원문 ㄱ"}'
        assert page.locator("#addName").input_value() == "원본-server-name"
        assert page.evaluate("document.activeElement === originalDraft && originalDraft === document.querySelector('#rawConfig') && originalDraft.selectionStart === 2 && originalDraft.selectionEnd === 5")
        assert not page.locator("#toolsEnabled").is_checked()
        assert not errors, errors
        assert not writes, writes
    finally:
        context.close()


def test_scope_dynamic_tools_preserve_protocols_and_data(localized_browser):
    context, page, errors, writes = scope_page(localized_browser, "tools", agent=True)
    try:
        page.locator('.oa-mode [data-mode="pro"]').click()
        note = page.locator('[data-note="hermes"]')
        assert note.input_value() == "原文 그대로"
        note.fill("아직 저장 안 함 ㄱ")
        policy = page.locator('[data-policy-tool="original_tool"]')
        page.evaluate("window.originalPolicy=document.querySelector('[data-policy-tool]')")
        for locale in ["en", "ko"]:
            page.evaluate("locale => OAI18n.setLocale(locale)", locale)
            assert note.input_value() == "아직 저장 안 함 ㄱ"
            assert policy.input_value() == "confirm"
            assert page.evaluate("originalPolicy === document.querySelector('[data-policy-tool]')")
            assert page.locator("#serversBox").get_by_text("Original tool description 原文", exact=True).count() == 1
            assert "Original result 原文" in page.locator("#logBody").inner_text()
            assert "hermes__original_tool" in page.locator("#logBody").inner_text()
        assert policy.locator('option[value="confirm"]').inner_text() == "승인 필요"
        assert "승인됨" in page.locator("#logBody").inner_text()
        assert not errors, errors
        assert not writes, writes
    finally:
        context.close()


def test_scope_flow_preserves_canvas_and_translates_inspector(localized_browser):
    context, page, errors, writes = scope_page(localized_browser, "flow")
    try:
        assert not errors, errors
        page.locator(".node").first.click()
        page.locator("#zoomIn").click()
        page.evaluate("window.originalNode=document.querySelector('.node')")
        before = page.locator("#world").get_attribute("style")
        for locale in ["en", "ko"]:
            page.evaluate("locale => OAI18n.setLocale(locale)", locale)
            assert page.locator("#world").get_attribute("style") == before
            assert page.evaluate("originalNode === document.querySelector('.node')")
        assert not errors, errors
        assert not writes, writes
        assert re.search(r"[가-힣]", page.locator("#inspector").inner_text())
        for view in ["processes", "tools", "memory", "all", "turn"]:
            page.locator(f'.flow-views [data-view="{view}"]').click()
            page.evaluate("OAI18n.setLocale('en'); OAI18n.setLocale('ko')")
            assert page.locator(".node").count() > 0
        assert not errors, errors
    finally:
        context.close()


@pytest.mark.parametrize("held", [False, True])
def test_scope_korean_statement_never_implies_acceptance(localized_browser, held):
    context, page, errors, writes = scope_page(localized_browser, "tools", held=held)
    try:
        if not held:
            page.locator("#iotConsentOpen").click()
        page.locator("#iotConsent").wait_for(state="visible")
        assert page.locator("#iotConsent").is_visible()
        assert page.locator("#iotConsentText").get_attribute("lang") == "ko"
        assert "책임" in page.locator("#iotConsentText").inner_text()
        assert not page.locator("#iotConsentCheck").is_checked()
        assert page.locator("#iotConsentEnable").is_disabled()
        if held:
            page.locator("#iotConsentCheck").check()
        page.evaluate("OAI18n.setLocale('en'); OAI18n.setLocale('ko')")
        assert page.locator("#iotConsentCheck").is_checked() == held
        page.locator('.oa-consent-lang[data-lang="ja"]').click()
        page.evaluate("OAI18n.setLocale('en'); OAI18n.setLocale('ko')")
        assert page.locator("#iotConsentText").get_attribute("lang") == "ja"
        assert page.locator("#iotConsentCheck").is_checked() == held
        assert not writes, writes
        page.locator("#iotConsentCancel").click()
        assert not page.locator("#iotConsent").is_visible()
        assert not page.locator("#toolsEnabled").is_checked()
        assert not errors, errors
        assert not writes, writes
    finally:
        context.close()


def test_scope_about_keeps_original_license_links(localized_browser):
    context, page, errors, writes = scope_page(localized_browser, "about")
    try:
        links = page.locator("a").evaluate_all("nodes => nodes.map(n => n.getAttribute('href'))")
        page.evaluate("OAI18n.setLocale('en')")
        assert page.locator("a").evaluate_all("nodes => nodes.map(n => n.getAttribute('href'))") == links
        page.evaluate("OAI18n.setLocale('ko')")
        assert page.locator("a").evaluate_all("nodes => nodes.map(n => n.getAttribute('href'))") == links
        assert not errors, errors
        assert not writes, writes
    finally:
        context.close()
