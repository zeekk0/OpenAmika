"""Opt-in real browser acceptance against an isolated running OpenAmika.

OPENAMIKA_ACCEPTANCE_URL=http://127.0.0.1:53100 python -m pytest \
    tests/test_live_korean_ui.py -q
Requires Playwright, its Chromium browser, and an isolated supported speech
gateway with a reachable, already-onboarded test brain. No text-only service or
fallback transport is provided. Never uses the user's browser profile. Blocks
non-read HTTP requests and off-origin traffic, including automatic onboarding
voice samples. Does not save app settings, accept permissions, or call a model.
Synthetic browser events here are NOT native OS IME or acoustic acceptance.
"""
import os
from urllib.parse import urlsplit

import pytest

BASE = os.getenv("OPENAMIKA_ACCEPTANCE_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not BASE, reason="Set isolated OPENAMIKA_ACCEPTANCE_URL explicitly")


@pytest.fixture(scope="module")
def browser():
    parsed = urlsplit(BASE)
    assert parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert parsed.port != 53000, "Do not run acceptance against the user's original app"
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        channel = os.getenv("OPENAMIKA_BROWSER_CHANNEL")
        instance = driver.chromium.launch(headless=True, **({"channel": channel} if channel else {}))
        class ReadOnlyBrowser:
            def new_context(self, **options):
                context = instance.new_context(**options)

                def read_only(route):
                    request = route.request
                    target = urlsplit(request.url)
                    if request.method not in {"GET", "HEAD", "OPTIONS"} or (
                        target.scheme in {"http", "https"} and target.netloc != parsed.netloc
                    ):
                        route.abort("blockedbyclient")
                    else:
                        route.continue_()

                context.route("**/*", read_only)
                return context

        try:
            with instance.new_context() as context:
                health = context.request.get(BASE + "/health")
                assert health.ok, "Start the isolated supported speech gateway first"
                payload = health.json()
                assert "device" in payload and "cuda_available" in payload, payload
                assert "text_only" not in payload and "capabilities" not in payload, payload
                persona = context.request.get(BASE + "/api/build_f/persona")
                assert persona.ok and persona.json().get("onboarded") is True, (
                    "Use an already-onboarded isolated test brain to avoid automatic voice requests"
                )
            yield ReadOnlyBrowser()
        finally:
            instance.close()


def ready(page, path):
    response = page.goto(BASE + path, wait_until="domcontentloaded")
    assert response.status == 200
    page.wait_for_function("window.OAI18n && document.querySelector('#oaLocale')")
    page.wait_for_function("document.documentElement.lang === OAI18n.getLocale()")


def assert_translated_text(page):
    untranslated = page.evaluate("""() => [...document.querySelectorAll('[data-i18n]')]
      .filter(el => !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) && !el.isContentEditable)
      .filter(el => el.textContent.trim() !== OAI18n.t(el.getAttribute('data-i18n')).trim())
      .map(el => ({key: el.getAttribute('data-i18n'), children: el.children.length,
                   actual: el.textContent.trim().slice(0, 100)}))""")
    assert not untranslated, untranslated


@pytest.mark.parametrize("path", ["/use", "/setup", "/tools", "/about", "/flow"])
def test_live_korean_page_catalogs_and_language_switch(browser, path):
    with browser.new_context(locale="ko-KR", timezone_id="America/Los_Angeles") as context:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        ready(page, path)
        assert page.locator("html").get_attribute("lang") == "ko"
        assert page.locator("#oaLocale").input_value() == "ko"
        # Actual served module and DOM, not a replacement DOM or extracted source.
        missing = page.evaluate("""() => [...document.querySelectorAll('*')].flatMap(el =>
          [...el.attributes].filter(a => a.name.startsWith('data-i18n')).flatMap(a =>
            OAI18n.t(a.value) === a.value ? [a.value] : []))""")
        assert not missing, missing
        assert_translated_text(page)
        writes = []
        page.on("request", lambda request: writes.append(request.url)
                if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
        page.locator("#oaLocale").select_option("en")
        assert page.locator("html").get_attribute("lang") == "en"
        assert_translated_text(page)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#oaLocale')")
        assert page.locator("html").get_attribute("lang") == "en"
        page.locator("#oaLocale").select_option("ko")
        assert_translated_text(page)
        assert page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone") == "America/Los_Angeles"
        assert not writes, writes
        assert not errors, errors


def test_live_korean_unsaved_input_cross_tab_and_reload(browser):
    with browser.new_context(locale="ko-KR") as context:
        page, other = context.new_page(), context.new_page()
        ready(page, "/use")
        ready(other, "/about")
        field = page.locator("#sayInput")
        text = "민수와 서울, 원문 그대로 ABC 123 🙂"
        field.fill(text)
        field.evaluate("el => el.setSelectionRange(2, 5)")
        before = field.evaluate("el => [el.selectionStart, el.selectionEnd]")
        other.locator("#oaLocale").select_option("en")
        page.wait_for_function("OAI18n.getLocale() === 'en'")
        assert field.input_value() == text
        assert field.evaluate("el => [el.selectionStart, el.selectionEnd]") == before
        other.locator("#oaLocale").select_option("ko")
        page.wait_for_function("OAI18n.getLocale() === 'ko'")
        assert field.input_value() == text


def test_live_korean_storage_unavailable(browser):
    with browser.new_context(locale="ko-KR") as context:
        context.add_init_script("""Object.defineProperty(window, 'localStorage', {
          get() { throw new DOMException('Storage denied', 'SecurityError'); }
        });""")
        page = context.new_page()
        ready(page, "/about")
        assert page.locator("html").get_attribute("lang") == "ko"
        page.locator("#oaLocale").select_option("en")
        assert page.locator("html").get_attribute("lang") == "en"


@pytest.mark.parametrize("saved", ["invalid", "ko-KR"])
def test_live_korean_invalid_saved_locale_uses_browser_language(browser, saved):
    with browser.new_context(locale="ko-KR") as context:
        context.add_init_script(
            "localStorage.setItem('openamika-ui-locale', " + repr(saved) + ");"
        )
        page = context.new_page()
        ready(page, "/use")
        assert page.locator("html").get_attribute("lang") == "ko"
        assert page.locator("#oaLocale").input_value() == "ko"
        assert_translated_text(page)


def test_live_korean_expert_unsaved_persona_and_identity(browser):
    with browser.new_context(locale="ko-KR") as context:
        page = context.new_page()
        ready(page, "/setup")
        page.locator('.oa-mode [data-mode="pro"]').click()
        page.wait_for_function("document.querySelector('#pEditor').value.length > 0")
        editor = page.locator("#pEditor")
        original = editor.input_value()
        draft = original + "\n한국어 초안 ABC 我说： {user_name}"
        editor.fill(draft)
        page.locator("#pUser").fill("이름 미저장")
        page.locator("#pCity").fill("도시 미저장")
        timezone = page.locator("#pTimezone").input_value()
        editor.evaluate("el => el.setSelectionRange(3, 9)")
        writes = []
        page.on("request", lambda request: writes.append(request.url)
                if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
        for locale in ("en", "ko"):
            page.locator("#oaLocale").select_option(locale)
            assert editor.input_value() == draft
            assert editor.evaluate("el => [el.selectionStart, el.selectionEnd]") == [3, 9]
            assert page.locator("#pUser").input_value() == "이름 미저장"
            assert page.locator("#pCity").input_value() == "도시 미저장"
            assert page.locator("#pTimezone").input_value() == timezone
        assert not writes, writes


def test_live_korean_iot_statement_cancel_never_consents(browser):
    with browser.new_context(locale="ko-KR") as context:
        page = context.new_page()
        ready(page, "/tools")
        writes = []
        page.on("request", lambda request: writes.append(request.url)
                if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
        page.locator("#iotConsentOpen").click()
        page.locator("#iotConsent[open]").wait_for()
        page.locator('.oa-consent-lang[data-lang="ko"]').click()
        page.wait_for_function("/[가-힣]/.test(document.querySelector('#iotConsentText').textContent)")
        assert not page.locator("#iotConsentCheck").is_checked()
        assert page.locator("#iotConsentEnable").is_disabled()
        page.locator("#iotConsentCancel").click()
        assert not page.locator("#iotConsent").is_visible()
        assert not writes, writes


def test_live_korean_real_http_refusal_is_localized(browser):
    with browser.new_context(locale="ko-KR") as context:
        page = context.new_page()
        ready(page, "/about")
        error = page.evaluate("""async () => {
          try { await OA.getJSON('/api/nonexistent-korean-acceptance'); }
          catch (error) { return {status: error.status, message: error.message}; }
        }""")
        assert error["status"] == 404
        assert any("가" <= letter <= "힣" for letter in error["message"])
        assert "Not Found" not in error["message"]


@pytest.mark.parametrize("path", ["/use", "/setup", "/tools", "/about", "/flow"])
@pytest.mark.parametrize("width", [320, 1280])
def test_live_korean_responsive_document(browser, path, width):
    with browser.new_context(locale="ko-KR", viewport={"width": width, "height": 900}) as context:
        page = context.new_page()
        ready(page, path)
        page.wait_for_timeout(500)
        sizes = page.evaluate("""() => ({viewport: innerWidth,
          document: document.documentElement.scrollWidth})""")
        assert sizes["document"] <= sizes["viewport"] + 1, sizes
