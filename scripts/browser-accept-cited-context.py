#!/usr/bin/env python3
"""Exercise on-demand cited context with synthetic saved answers in Chrome.

The controlled answer client and retrieval population test persistence and UI
behavior, not model quality. Source text uses the real TXT ingestion path.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

from fastapi.testclient import TestClient
from fastapi.responses import PlainTextResponse
import uvicorn
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from synthetic_browser_environment import isolate_environment
from case_intelligence.workbench import create_workbench_app

ACTOR = 'development-taylor-morgan'
MARKUP = '<script>window.syntheticInjection=true</script> & <img src=x onerror=alert(1)>'
STATEMENTS = (
    'The synthetic Cedar gauge recorded 18 psi.',
    'The synthetic Birch reference gauge recorded 12 psi.',
    'The synthetic Elm observer paused the exercise.',
    'The synthetic Pine note says the cause remains unresolved.',
)
NAMES = ('Generated Cedar reading.txt', 'Generated Birch reference.txt',
         'Generated Elm observation.txt', 'Generated Pine limitation.txt')
SOURCES = (STATEMENTS[0] + ' ' + MARKUP + '\n' +
           '\n'.join('Synthetic retained context line. ' * 22 for _ in range(14)),
           STATEMENTS[1], STATEMENTS[2], STATEMENTS[3])


class SyntheticAnswerClient:
    available = True

    def generate(self, *, evidence, **kwargs):
        by_name = {item.source_name: item.evidence_id for item in evidence}
        return dict(answerable=True,
            claims=[dict(text=' '.join(STATEMENTS[:3]), evidence_ids=[by_name[name] for name in NAMES[:3]])],
            limitation=dict(text=STATEMENTS[3], evidence_ids=[by_name[NAMES[3]]]), missing_information='')


def app_at(runtime):
    return create_workbench_app(runtime, generator=SyntheticAnswerClient(), auth_mode='test')


def seed(runtime):
    with TestClient(app_at(runtime)) as client:
        bench = client.app.state.workbench
        bench.answers.close()
        bench.research.close()
        bench.full_review.close()
        matter = bench.create_matter('Generated cited context comparison', 'Synthetic browser fixture', ACTOR)
        store = bench.source_store(matter)
        documents = tuple(store.store_stream(name, 'text/plain', io.BytesIO(text.encode()))[0]
                          for name, text in zip(NAMES, SOURCES))
        bench._sync_source_catalog(matter, documents)
        citations = tuple(bench._citation(matter, bench._candidate(matter, document,
            document.parsed_units()[0], 1)) for document in documents)
        assert len(citations[0].excerpt) > 6_000
        bench._answer_search = lambda *args, **kwargs: citations
        conversations = []
        messages = []
        for title in ('Generated comparison first', 'Generated comparison second'):
            conversation = bench.workspace.create_conversation(matter.matter_id, title, actor_id=ACTOR)
            message = bench.ask(matter, conversation, 'Compare the Cedar, Birch and Elm exercise observations and the unresolved cause.')
            assert message.payload['kind'] == 'generated'
            assert len(message.payload['claims'][0]['citations']) == 3
            assert len(message.payload['limitation']['citations']) == 1
            assert all('excerpt' not in value for value in message.payload['claims'][0]['citations'])
            conversations.append(conversation.conversation_id)
            messages.append(message.message_id)
        return dict(slug=matter.slug, conversations=conversations, messages=messages,
                    document_id=documents[0].document_id, payload=message.payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chrome-binary', type=Path, required=True)
    parser.add_argument('--chromedriver', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Choose an empty output directory.')
    isolate_environment()
    checks = []
    driver = None

    def record(message):
        checks.append(message)
        print(message, flush=True)

    with tempfile.TemporaryDirectory(prefix='recordbench-cited-context-browser-') as temporary:
        runtime = Path(temporary).resolve() / 'runtime'
        seeded = seed(runtime)
        app = app_at(runtime)
        requests = []
        network = dict(fail_next=False, hold_next=False, holding=False)

        @app.middleware('http')
        async def synthetic_network_control(request, call_next):
            if '/cited-context/' in request.url.path:
                requests.append((request.url.path, request.query_params.get('format', 'html')))
                if network['fail_next']:
                    network['fail_next'] = False
                    return PlainTextResponse('Synthetic temporary failure', status_code=503)
                if network['hold_next']:
                    network['hold_next'] = False
                    network['holding'] = True
                    deadline = time.monotonic() + 10
                    while network['holding'] and time.monotonic() < deadline:
                        await asyncio.sleep(.02)
                    network['holding'] = False
            return await call_next(request)

        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        base = f'http://127.0.0.1:{listener.getsockname()[1]}'
        prefix = f'/matters/{seeded["slug"]}'
        conversation_path = prefix + '?conversation=' + seeded['conversations'][0]
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False, ws='none'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            options = Options()
            options.binary_location = str(args.chrome_binary)
            for flag in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1440,1100'):
                options.add_argument(flag)
            driver = webdriver.Chrome(service=Service(str(args.chromedriver)), options=options)
            driver.set_page_load_timeout(30)
            wait = WebDriverWait(driver, 20, ignored_exceptions=(StaleElementReferenceException,))
            wait.until(lambda _: server.started)

            def cards(root=None):
                return (root or driver).find_elements(By.CSS_SELECTOR, '[data-cited-context]')

            def summary(card):
                return card.find_element(By.TAG_NAME, 'summary')

            def excerpt(card):
                return card.find_element(By.CSS_SELECTOR, '[data-context-excerpt]')

            def open_card(card, key=Keys.ENTER):
                summary(card).send_keys(key)
                wait.until(lambda _: card.get_attribute('open') is not None)
                wait.until(lambda _: excerpt(card).is_displayed() and bool(excerpt(card).text))

            def no_overflow():
                assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'), 'Page overflows horizontally'
                assert driver.execute_script('return [...document.querySelectorAll("[data-cited-context][open]")].every(e => e.scrollWidth <= e.clientWidth + 1)'), 'Comparison overflows horizontally'
                assert driver.execute_script('return [...document.querySelectorAll(".workspace-main, .assistant-thread")].every(e => e.scrollWidth <= e.clientWidth + 1)'), 'Review pane overflows horizontally'

            def tab_to(selector, limit=180):
                for _ in range(limit):
                    active = driver.switch_to.active_element
                    if driver.execute_script('return arguments[0].matches(arguments[1])', active, selector):
                        return active
                    active.send_keys(Keys.TAB)
                raise AssertionError('Control is not keyboard reachable: ' + selector)

            def unobstructed(element):
                return driver.execute_script('''const box = arguments[0].getBoundingClientRect();
                    const x = box.left + box.width / 2, y = box.top + box.height / 2;
                    const hit = document.elementFromPoint(x, y);
                    return x >= 0 && x < innerWidth && y >= 0 && y < innerHeight &&
                        (hit === arguments[0] || arguments[0].contains(hit));''', element)

            driver.get(base + conversation_path)
            assert len(cards()) == 4, 'Every claim and limitation citation needs its own comparison'
            assert not requests, 'Collapsed comparisons must not request excerpts'
            assert all(not excerpt(card).text for card in cards())
            record('Four distinct claim and limitation comparisons start collapsed without fetching or retaining excerpts')

            # Reach the first native disclosure from the document's initial focus.
            focus = tab_to('[data-cited-context] > summary')
            network['fail_next'] = True
            focus.send_keys(Keys.ENTER)
            first = cards()[0]
            retry = wait.until(lambda _: first.find_element(By.CSS_SELECTOR, '[data-context-retry]')
                               if first.find_element(By.CSS_SELECTOR, '[data-context-retry]').is_displayed() else None)
            assert not excerpt(first).text
            tab_to('[data-context-retry]', limit=15)
            network['hold_next'] = True
            retry.send_keys(Keys.ENTER)
            wait.until(lambda _: network['holding'])
            assert 'Checking access' in first.find_element(By.CSS_SELECTOR, '[data-context-status]').text
            assert not excerpt(first).text
            network['holding'] = False
            wait.until(lambda _: excerpt(first).is_displayed() and bool(excerpt(first).text))
            record('Native Tab and Enter open the comparison; a temporary failure exposes reachable retry and loading status')

            long_excerpt = excerpt(first)
            displayed = long_excerpt.get_attribute('textContent')
            assert displayed and len(displayed) <= 6_000 and SOURCES[0].startswith(displayed)
            assert MARKUP in displayed
            assert not long_excerpt.find_elements(By.CSS_SELECTOR, 'script, img')
            assert driver.execute_script('return window.syntheticInjection !== true')
            assert len(requests) == 2
            for card, statement in zip(cards()[1:], STATEMENTS[1:]):
                open_card(card, Keys.SPACE)
                assert statement in excerpt(card).text
            assert len({card.find_element(By.CSS_SELECTOR, '[data-context-source]').text for card in cards()}) == 4
            record('Each source context remains separate; Space opens disclosures, long text is bounded and source markup is escaped')

            long_excerpt.send_keys(Keys.HOME)
            before_scroll = driver.execute_script('return arguments[0].scrollTop', long_excerpt)
            long_excerpt.send_keys(Keys.PAGE_DOWN)
            wait.until(lambda _: driver.execute_script('return arguments[0].scrollTop', long_excerpt) > before_scroll)
            long_excerpt.send_keys(Keys.TAB)
            assert driver.switch_to.active_element == first.find_element(By.CSS_SELECTOR, '[data-context-source-link]')
            assert driver.switch_to.active_element.is_displayed()
            no_overflow()
            driver.execute_script('arguments[0].scrollIntoView({block:"start",behavior:"instant"})', first)
            driver.save_screenshot(str(output / 'cited-context-desktop.png'))
            record('Keyboard users can scroll the bounded long excerpt and reach its full-source link on desktop')

            for width in (390, 320):
                driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', dict(width=width, height=844, deviceScaleFactor=1, mobile=False))
                no_overflow()
                summary(first).send_keys(Keys.ENTER)
                open_card(first)
                long_excerpt = excerpt(first)
                long_excerpt.send_keys(Keys.PAGE_DOWN)
                long_excerpt.send_keys(Keys.TAB)
                assert driver.switch_to.active_element == first.find_element(By.CSS_SELECTOR, '[data-context-source-link]')
                assert driver.switch_to.active_element.is_displayed()
                no_overflow()
                wait.until(lambda _: unobstructed(driver.switch_to.active_element), 'Focused source link is obscured')
                driver.execute_script('arguments[0].scrollIntoView({block:"start",behavior:"instant"})', first)
                no_overflow()
                driver.save_screenshot(str(output / f'cited-context-{width}.png'))
            fallback = first.get_attribute('data-context-url')
            first.find_element(By.CSS_SELECTOR, '[data-context-source-link]').send_keys(Keys.ENTER)
            wait.until(lambda _: '/sources/' in driver.current_url)
            assert STATEMENTS[0] in driver.find_element(By.TAG_NAME, 'body').text
            record('Expanded comparisons fit 390- and 320-pixel widths; the unobstructed keyboard link opens the full current source')

            driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled', {'value': True})
            driver.get(base + fallback)
            assert STATEMENTS[0] in driver.find_element(By.TAG_NAME, 'body').text
            assert '&lt;script&gt;window.syntheticInjection=true&lt;/script&gt;' in driver.page_source
            assert not driver.find_elements(By.CSS_SELECTOR, 'img[src="x"]')
            driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled', {'value': False})
            record('The direct comparison page remains readable without JavaScript and escapes source markup')

            driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
            # Full-source navigation can remember its default chat; reset only
            # this synthetic origin's preferences so the next explicit choice
            # changes the selected conversation rather than selecting it again.
            driver.execute_script('localStorage.clear()')
            driver.get(base + prefix + '/notebook?conversation=' + seeded['conversations'][0])
            dock = driver.find_element(By.CSS_SELECTOR, '[data-assistant-dock]')
            if not driver.find_element(By.CSS_SELECTOR, '[data-assistant-conversation-picker]').is_displayed():
                driver.find_element(By.CSS_SELECTOR, '[data-assistant-expand]').send_keys(Keys.ENTER)
            before_requests = len(requests)
            Select(driver.find_element(By.CSS_SELECTOR, '[data-assistant-conversation-picker]')).select_by_value(seeded['conversations'][1])
            wait.until(EC.staleness_of(dock))
            dock = driver.find_element(By.CSS_SELECTOR, '[data-assistant-dock]')
            assert len(cards(dock)) == 4
            assert len(requests) == before_requests
            open_card(cards(dock)[2], Keys.SPACE)
            assert STATEMENTS[2] in excerpt(cards(dock)[2]).text
            no_overflow()
            driver.save_screenshot(str(output / 'cited-context-assistant.png'))
            record('Switching saved chats replaces the assistant fragment and preserves all lazily loaded comparison controls')

            for width in (390, 320):
                driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', dict(width=width, height=844, deviceScaleFactor=1, mobile=False))
                if not summary(cards(dock)[0]).is_displayed():
                    driver.find_element(By.CSS_SELECTOR, '[data-assistant-expand]').send_keys(Keys.ENTER)
                long_card = cards(dock)[0]
                if long_card.get_attribute('open') is not None:
                    summary(long_card).send_keys(Keys.ENTER)
                open_card(long_card)
                long_excerpt = excerpt(long_card)
                long_excerpt.send_keys(Keys.PAGE_DOWN)
                long_excerpt.send_keys(Keys.TAB)
                assert driver.switch_to.active_element == long_card.find_element(By.CSS_SELECTOR, '[data-context-source-link]')
                wait.until(lambda _: unobstructed(driver.switch_to.active_element), 'Assistant source link is obscured')
                no_overflow()
                driver.save_screenshot(str(output / f'cited-context-assistant-{width}.png'))
            record('The replaced assistant comparison fits 390 and 320 pixels, with independently scrollable excerpt and unobstructed keyboard source link')

            driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
            driver.get(base + conversation_path)
            first = cards()[0]
            open_card(first)
            summary(first).send_keys(Keys.ENTER)
            bench = app.state.workbench
            matter = bench.matter(seeded['slug'], ACTOR)
            store = bench.source_store(matter)
            with store.mutation_guard():
                document = store.get(seeded['document_id'])
                document.version_id = 'f' * 32
                store._save()
                bench._sync_source_catalog(matter, [document])
            before_requests = len(requests)
            summary(first).send_keys(Keys.SPACE)
            wait.until(lambda _: len(requests) > before_requests)
            wait.until(lambda _: not excerpt(first).is_displayed() and
                       'Checking access' not in first.find_element(By.CSS_SELECTOR, '[data-context-status]').text)
            assert not excerpt(first).get_attribute('textContent')
            assert not first.find_element(By.CSS_SELECTOR, '[data-context-source-link]').is_displayed()
            open_card(cards()[1])
            assert STATEMENTS[1] in excerpt(cards()[1]).text
            saved = bench.workspace.messages(matter.matter_id, seeded['conversations'][1])[-1]
            assert saved.payload == seeded['payload']
            driver.execute_script('arguments[0].scrollIntoView({block:"start",behavior:"instant"})', first)
            driver.save_screenshot(str(output / 'cited-context-changed.png'))
            record('Reopening revalidates the historical version, clears changed context, leaves sibling citations usable and preserves stored answers')

            (output / 'receipt.json').write_text(json.dumps(dict(synthetic_only=True, passed=True, checks=checks,
                browser=driver.capabilities.get('browserVersion'), screenshots=sorted(path.name for path in output.glob('*.png'))), indent=2))
        except Exception as exc:
            if driver:
                driver.save_screenshot(str(output / 'failure.png'))
                print(json.dumps(driver.execute_script('''const pane=document.querySelector('.workspace-main');
                    const composer=document.querySelector('.composer-wrap');
                    const rect=e => e ? ({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,
                        width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}) : null;
                    return {focus:rect(document.activeElement),composer:rect(composer),pane:rect(pane),
                        scrollTop:pane?.scrollTop,clientHeight:pane?.clientHeight,
                        composerHeight:pane&&getComputedStyle(pane).getPropertyValue('--review-composer-height'),
                        scrollPadding:pane&&getComputedStyle(pane).scrollPaddingBottom,
                        paneWidth:pane&&[pane.clientWidth,pane.scrollWidth],
                        overflowing:pane?[...pane.querySelectorAll('*')].filter(e=>e.scrollWidth>e.clientWidth+1)
                            .slice(0,12).map(e=>({tag:e.tagName,classes:e.className,width:e.clientWidth,scroll:e.scrollWidth})):[]};''')), flush=True)
            (output / 'receipt.json').write_text(json.dumps(dict(synthetic_only=True, passed=False,
                checks=checks, error=type(exc).__name__), indent=2))
            raise
        finally:
            network['holding'] = False
            if driver:
                driver.quit()
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()


if __name__ == '__main__':
    main()
