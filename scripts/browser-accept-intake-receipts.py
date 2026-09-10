#!/usr/bin/env python3
"""Synthetic receipt recovery through real Chrome and disposable loopback state."""
from __future__ import annotations

import argparse
import io
import json
import socket
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from case_intelligence.generation import UnavailableGenerator  # noqa: E402
from case_intelligence.intake_receipts import IntakeReceipts  # noqa: E402
from case_intelligence.managed_storage import StoragePolicy  # noqa: E402
from case_intelligence.workbench import create_workbench_app  # noqa: E402

ACTOR = 'development-taylor-morgan'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def until(predicate, message, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chrome-binary', type=Path, required=True)
    parser.add_argument('--chromedriver', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    downloads = output / 'downloads'
    downloads.mkdir(exist_ok=True)
    report = {'synthetic_only': True, 'passed': False, 'checks': []}
    def record_check(message):
        report['checks'].append(message)
        print(message, flush=True)
    driver = server = thread = sock = None
    with tempfile.TemporaryDirectory(prefix='recordbench-intake-browser-') as d:
        root = Path(d)
        folder = root / 'Generated-selection'
        fixtures = {
            'North/report.txt': b'Synthetic north copper journal passage.\n',
            'South/report.txt': b'Synthetic south amber journal passage.\n',
            'Copies/copy.txt': b'Synthetic north copper journal passage.\n',
            'Attention/damaged.pdf': b'Not a PDF file.\n',
            'Unsupported/opaque.bin': b'Generated unsupported bytes',
            'Empty/empty.txt': b'',
            'Large/large.txt': b'x' * (128 * 1024 + 1),
        }
        for relative, body in fixtures.items():
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        app = create_workbench_app(root / 'runtime', generator=UnavailableGenerator(),
            auth_mode='test', background_ingestion=True, ingestion_workers=1,
            storage_policy=StoragePolicy(matter_quota_bytes=1024*1024, upload_session_bytes=256*1024,
                document_file_bytes=128*1024, media_file_bytes=128*1024, reserve_bytes=0))
        bench = app.state.workbench
        receipts = IntakeReceipts(bench.workspace)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        until(lambda: server.started, 'Synthetic server did not start')
        base = f'http://127.0.0.1:{port}'
        options = Options()
        options.binary_location = str(args.chrome_binary)
        options.page_load_strategy = 'none'
        for flag in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--no-proxy-server', '--window-size=1440,1000'):
            options.add_argument(flag)
        options.add_experimental_option('prefs', {'download.default_directory': str(downloads), 'download.prompt_for_download': False})
        options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
        try:
            driver = webdriver.Chrome(service=Service(str(args.chromedriver)), options=options)
            driver.set_page_load_timeout(30)
            wait = WebDriverWait(driver, 25, ignored_exceptions=(StaleElementReferenceException,))
            def page_has_text(text):
                try:
                    return text in driver.find_element(By.TAG_NAME, 'body').text
                except WebDriverException as exc:
                    # Chrome can report this stale-node condition as an
                    # inspector error while a form submission replaces the page.
                    if "Node with given id does not belong to the document" not in exc.msg:
                        raise
                    return False

            original_get = driver.get
            def navigate(url):
                original_get(url)
                wait.until(lambda current: current.execute_script('return document.readyState') in {'interactive', 'complete'})
            driver.get = navigate

            def create_matter(name):
                driver.get(base + '/matters/new')
                driver.find_element(By.ID, 'matter-name').send_keys(name)
                driver.find_element(By.ID, 'matter-descriptor').send_keys('Generated receipt acceptance')
                driver.find_element(By.CSS_SELECTOR, '.matter-form button[type=submit]').click()
                wait.until(lambda x: '/setup' in x.current_url)
                slug = urlparse(driver.current_url).path.split('/')[2]
                wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-folder-input]').is_enabled())
                return bench.matter(slug, ACTOR)

            def confirm():
                button = driver.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]')
                driver.execute_script('arguments[0].scrollIntoView({block:"center",behavior:"instant"});', button)
                wait.until(lambda current: current.execute_script('const r=arguments[0].getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight;', button))
                button.click()

            def completed(matter):
                sessions = bench.workspace.recent_upload_sessions(matter.matter_id, ACTOR)
                return sessions and all(s.state in {'complete', 'partial'} for s in sessions) and not any(bench.workspace.active_matter_work_counts(matter.matter_id).values())

            matter = create_matter('Synthetic nested receipt')
            # Lose an actual successful confirmation response while browser
            # storage is unavailable. Retrying must reuse its in-memory key.
            driver.execute_script(r'''
                Object.defineProperty(window, 'localStorage', {configurable:true, get() {throw new DOMException('Synthetic storage denied', 'SecurityError');}});
                window.receiptOriginalFetch = window.fetch;
                window.receiptLostResponse = false;
                window.fetch = async (...args) => {
                    const response = await window.receiptOriginalFetch(...args);
                    if (!window.receiptLostResponse && /\/intake-receipts$/.test(String(args[0])) && args[1]?.method === 'POST') {
                        window.receiptLostResponse = true;
                        throw new Error('Synthetic confirmation response lost');
                    }
                    return response;
                };
            ''')
            driver.find_element(By.CSS_SELECTOR, '[data-folder-input]').send_keys(str(folder))
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Upload 4 ready files')
            confirm()
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-state]').text == 'Selection receipt paused')
            require(len(receipts.recent(matter.matter_id, ACTOR)) == 1, 'Lost response created extra receipts')
            confirm()
            until(lambda: completed(matter), 'Retried folder upload did not finish')
            saved = receipts.recent(matter.matter_id, ACTOR)
            require(len(saved) == 1, 'Storage-denied retry duplicated selection')
            receipt = saved[0]
            require(receipt['counts']['recorded'] == 7 and receipt['counts']['received'] == 4
                and receipt['counts']['skipped'] == 3 and receipt['counts']['searchable'] == 3
                and receipt['counts']['failed'] == 1, 'Selection/transfer/processing accounting differs')
            record_check('Nested selection and storage-denied lost-response retry preserve every row without duplicate receipts')
            driver.find_element(By.CSS_SELECTOR, '[data-intake-receipt-open]').click()
            wait.until(lambda x: len(x.find_elements(By.CSS_SELECTOR, '[data-intake-row]')) == 7)
            driver.refresh()
            require(len(driver.find_elements(By.CSS_SELECTOR, '[data-intake-row]')) == 7, 'Reload lost selected rows')
            require('Unsupported/opaque.bin' in driver.find_element(By.TAG_NAME, 'body').text, 'Reload lost skipped path')
            driver.save_screenshot(str(output / 'synthetic-nested-receipt.png'))
            source_links = [a.get_attribute('href') for a in driver.find_elements(By.LINK_TEXT, 'Open source')]
            require(len(source_links) == 3, 'Exact source links missing')
            receipt_url = driver.current_url
            for source_url in source_links:
                driver.get(source_url)
                require('journal passage' in driver.find_element(By.TAG_NAME, 'body').text, 'Source link opened wrong content')
            record_check('Reload retains skipped reasons; receipt opens all three exact source passages')
            driver.get(receipt_url)
            driver.find_element(By.LINK_TEXT, 'Structured version').click()
            receipt_file = until(lambda: next(downloads.glob('selected-file-receipt*.json'), None), 'Browser receipt download did not finish')
            data = json.loads(receipt_file.read_text())
            require(len(data['items']) == 7 and data['counts']['received'] == 4, 'Downloaded receipt is incomplete')
            driver.get(base + f'/matters/{matter.slug}/close')
            export_link = driver.find_element(By.CSS_SELECTOR, f'a[href="/matters/{matter.slug}/export"]')
            export_link.click()
            bundle_file = until(lambda: next(downloads.glob('*.zip'), None), 'Browser bundle download did not finish')
            with zipfile.ZipFile(io.BytesIO(bundle_file.read_bytes())) as archive:
                names = [n for n in archive.namelist() if n.startswith('intake/')]
                require(len(names) == 3, 'Complete bundle omitted receipt formats')
                exported = json.loads(archive.read(next(n for n in names if n.endswith('.json'))))
                require(exported == data, 'Bundle and individual receipt differ')
            record_check('Normal browser receipt and final-export downloads contain a coherent complete selection')

            driver.get(base + f'/matters/{matter.slug}/setup')
            driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(folder/'Unsupported/opaque.bin'))
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Save selection receipt')
            confirm()
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-state]').text == 'Selection receipt saved')
            saved = receipts.recent(matter.matter_id, ACTOR)
            require(len(saved) == 2 and saved[0]['counts']['skipped'] == 1 and saved[0]['counts']['received'] == 0, 'All-skipped selection was not saved')
            record_check('All-skipped selection creates a useful receipt without transferring bytes')

            interrupted = create_matter('Synthetic interrupted receipt')
            resume_file = root/'resume.txt'
            resume_body = b'Synthetic exact resumed source.\n' * 100
            resume_file.write_bytes(resume_body)
            driver.execute_script('''
                window.receiptOriginalFetch = window.fetch;
                window.receiptPartialStored = false;
                window.fetch = async (url, options) => {
                    if (options?.method === 'PUT' && String(url).includes('/upload-sessions/')) {
                        if (!window.receiptPartialStored) {
                            await window.receiptOriginalFetch(url, {...options, body: options.body.slice(0, 7)});
                            window.receiptPartialStored = true;
                        }
                        throw new Error('Synthetic interrupted transfer');
                    }
                    return window.receiptOriginalFetch(url, options);
                };
            ''')
            driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(resume_file))
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Upload 1 ready file')
            confirm()
            wait.until(lambda x: x.execute_script('return window.receiptPartialStored === true'))
            previous = receipts.recent(interrupted.matter_id, ACTOR)[0]
            require(previous['counts']['partial'] == 1, 'Interrupted bytes were not recorded')
            driver.refresh()
            driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(resume_file))
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Upload 1 ready file')
            confirm()
            until(lambda: completed(interrupted), 'Reloaded upload did not resume')
            current = receipts.recent(interrupted.matter_id, ACTOR)
            require(len(current) == 1 and current[0]['receipt_id'] == previous['receipt_id'], 'Reload created a second selection receipt')
            require(current[0]['counts']['received'] == current[0]['counts']['searchable'] == 1, 'Resumed receipt did not become searchable')
            require(len(bench.workspace.recent_upload_sessions(interrupted.matter_id, ACTOR)) == 1, 'Reload duplicated the upload session')
            document = next(iter(bench.source_store(interrupted).documents.values()))
            require((bench.source_store(interrupted).files/document.stored_name).read_bytes() == resume_body, 'Resumed bytes differ')
            record_check('Interrupted seven-byte transfer resumes after reload with one receipt/session and exact final bytes')
            cancelled = create_matter('Synthetic cancelled selection')
            driver.execute_script(r'''
                window.receiptOriginalFetch = window.fetch;
                window.fetch = (url, options) => {
                    if (options?.method === 'PUT') return new Promise((resolve, reject) => {
                        options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once:true});
                    });
                    return window.receiptOriginalFetch(url, options);
                };
            ''')
            driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(resume_file))
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Upload 1 ready file')
            confirm()
            until(lambda: bench.workspace.recent_upload_sessions(cancelled.matter_id, ACTOR), 'Cancellation fixture did not start')
            cancel_button = driver.find_element(By.CSS_SELECTOR, '[data-upload-cancel]')
            driver.execute_script('arguments[0].scrollIntoView({block:"center",behavior:"instant"});', cancel_button)
            cancel_button.click()
            until(lambda: bench.workspace.recent_upload_sessions(cancelled.matter_id, ACTOR)[0].state == 'cancelled', 'Cancel did not finish')
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-form]').get_attribute('aria-busy') is None)
            driver.execute_script('window.fetch = window.receiptOriginalFetch; arguments[0].value="";', driver.find_element(By.CSS_SELECTOR, '[data-file-input]'))
            driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(resume_file))
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Upload 1 ready file')
            confirm()
            until(lambda: len(receipts.recent(cancelled.matter_id, ACTOR)) == 2 and receipts.recent(cancelled.matter_id, ACTOR)[0]['counts']['searchable'] == 1, 'Reselection after cancellation did not finish')
            record_check('Explicit cancellation retains its receipt and permits a later deliberate selection')
            # A valid filename can still be excluded by matter-wide capacity.
            # Its original selection observation must survive a later file check.
            capacity_matter = create_matter('Synthetic capacity receipt')
            reserved_sessions = []
            remaining = bench.storage_policy.matter_quota_bytes - 1024
            while remaining:
                batch = []
                batch_size = min(remaining, bench.storage_policy.upload_session_bytes)
                remaining -= batch_size
                while batch_size:
                    size = min(batch_size, bench.storage_policy.document_file_bytes)
                    batch_size -= size
                    name = f'earlier-{len(reserved_sessions)}-{len(batch)}.txt'
                    batch.append({'display_name': name, 'relative_path': 'Earlier/' + name,
                        'media_type': 'text/plain', 'expected_size': size})
                session, _ = bench.create_upload_session(capacity_matter, ACTOR, 'Earlier generated upload', batch)
                reserved_sessions.append(session)
            capacity_file = root/'capacity-limited.txt'
            capacity_body = b'Generated capacity fixture.\n' * 100
            capacity_file.write_bytes(capacity_body)
            driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(capacity_file))
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Save selection receipt')
            require('upload capacity remaining' in driver.find_element(By.CSS_SELECTOR, '[data-upload-preflight-items]').text,
                'Synthetic selection was not excluded by actual matter capacity')
            confirm()
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-state]').text == 'Selection receipt saved')
            capacity_receipt = receipts.recent(capacity_matter.matter_id, ACTOR)[0]
            snapshot = receipts.snapshot(capacity_matter.matter_id, ACTOR, capacity_receipt['receipt_id'])
            row = snapshot['items'][0]
            require(row['preflight_state'] == 'valid' and row['reviewed_state'] == 'over_limit'
                and 'capacity' in row['reviewed_reason'], 'Capacity reason was replaced by the later file check')
            require(len(bench.workspace.recent_upload_sessions(capacity_matter.matter_id, ACTOR)) == len(reserved_sessions),
                'Capacity-excluded selection unexpectedly created an upload session')
            receipt_path = f"/matters/{capacity_matter.slug}/intake/{capacity_receipt['receipt_id']}"
            driver.get(base + receipt_path)
            require('capacity-limited upload plan' in driver.find_element(By.TAG_NAME, 'body').text,
                'Reloaded receipt lost the reviewed capacity reason')
            before = set(downloads.glob('*.csv'))
            driver.find_element(By.CSS_SELECTOR, 'a[data-download][href$="format=csv"]').click()
            exported = until(lambda: next((p for p in downloads.glob('*.csv') if p not in before and p.stat().st_size), None),
                'Capacity receipt download did not finish')
            require('capacity-limited upload plan' in exported.read_text(encoding='utf-8-sig'),
                'CSV lost the reviewed capacity reason')
            for session in reserved_sessions:
                bench.workspace.cancel_upload_session(capacity_matter.matter_id, ACTOR, session.upload_session_id)
            require(capacity_file.read_bytes() == capacity_body, 'Capacity fixture original changed')
            record_check('Actual capacity exclusions retain their selection reason through reload and download, separately from valid filename checks')

            for index, invalid_name in enumerate(('   ', 'Generated\u202e name')):
                correction_matter = create_matter(f'Synthetic collection correction {index + 1}')
                if index == 1:
                    driver.execute_script("Object.defineProperty(window, 'localStorage', {configurable:true, get() {throw new DOMException('Synthetic storage denied', 'SecurityError');}});")
                driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(folder/'North/report.txt'))
                wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Upload 1 ready file')
                field = driver.find_element(By.CSS_SELECTOR, '[data-upload-collection-name]')
                field.clear()
                field.send_keys(invalid_name)
                confirm()
                wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-state]').text == 'Selection receipt paused')
                require(not receipts.recent(correction_matter.matter_id, ACTOR), 'Invalid name unexpectedly created a receipt')
                field.clear()
                field.send_keys('Corrected generated collection')
                confirm()
                until(lambda: completed(correction_matter), 'Corrected collection name could not confirm the same selected files')
                corrected = receipts.recent(correction_matter.matter_id, ACTOR)
                require(len(corrected) == 1 and corrected[0]['collection_name'] == 'Corrected generated collection',
                    'Retry restored a rejected name or created extra receipts')
                if index == 0:
                    old_link = driver.find_element(By.CSS_SELECTOR, '[data-intake-receipt-open]').get_attribute('href')
                    driver.execute_script("document.querySelector('[data-file-input]').value = '';")
                    driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(folder/'Unsupported/opaque.bin'))
                    wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Save selection receipt')
                    require(not driver.find_element(By.CSS_SELECTOR, '[data-intake-receipt-link]').is_displayed(),
                        'A new unconfirmed selection still opens the prior receipt')
                    confirm()
                    wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-state]').text == 'Selection receipt saved')
                    require(driver.find_element(By.CSS_SELECTOR, '[data-intake-receipt-open]').get_attribute('href') != old_link,
                        'A newly saved selection still points at its predecessor')
                    record_check('A new unconfirmed selection hides the prior receipt link and confirmation opens its own receipt')
            record_check('Rejected collection names can be corrected without reselecting files or clearing storage, including storage-denied retries')

            full_matter = create_matter('Synthetic receipt capacity recovery')
            # Exercise the real default limit with sealed skips and bound empty uploads;
            # the browser then attempts one additional actual selection.
            def full_receipt_count():
                return bench.workspace.connection.execute('SELECT count(*) FROM workbench_intake_receipt WHERE matter_id=?', (full_matter.matter_id,)).fetchone()[0]
            unbound_receipt_id = ''
            for index in range(1_000):
                bound = index >= 10
                title = f'Generated pending selection {index + 1}'
                receipt = receipts.create(full_matter.matter_id, ACTOR, selection_key=f'{index:032x}',
                    selection_fingerprint='e' * 64, selected_count=1, eligible_indexes=[0] if bound else [],
                    collection_name=title)
                receipts.append(full_matter.matter_id, ACTOR, receipt['receipt_id'], start=0,
                    files=[{'name': 'record.txt' if bound else 'opaque.bin',
                        'relative_path': 'Generated/record.txt' if bound else 'Generated/opaque.bin',
                        'size': 48, 'media_type': 'text/plain' if bound else ''}],
                    reviewed_states=['valid' if bound else 'unsupported'], document_limit=1024, media_limit=2048,
                    malware_scan_mode='off', scanner_ready=True)
                receipts.seal(full_matter.matter_id, ACTOR, receipt['receipt_id'])
                if bound:
                    latest_session, _ = bench.create_upload_session(full_matter, ACTOR, title,
                        [{'display_name': 'record.txt', 'relative_path': 'Generated/record.txt',
                            'media_type': 'text/plain', 'expected_size': 48}],
                        intake_receipt_id=receipt['receipt_id'], intake_ordinals=[0])
                elif not unbound_receipt_id:
                    unbound_receipt_id = receipt['receipt_id']
            driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(folder/'Unsupported/opaque.bin'))
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Save selection receipt')
            confirm()
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-state]').text == 'Selection receipt paused')
            require('receipt capacity is full' in driver.find_element(By.TAG_NAME, 'body').text,
                'The real receipt count limit did not give a recovery message')
            require(full_receipt_count() == 1_000, 'Rejected selection exceeded receipt capacity')
            removable = receipts.recent(full_matter.matter_id, ACTOR)[0]
            def discard_from_browser(receipt_id):
                driver.get(base + f"/matters/{full_matter.slug}/intake/{receipt_id}")
                toggle = driver.find_element(By.CSS_SELECTOR, '.intake-receipt-discard summary')
                driver.execute_script('arguments[0].scrollIntoView({block:"center",behavior:"instant"});', toggle)
                toggle.click()
                driver.find_element(By.CSS_SELECTOR, '.intake-receipt-discard input[name=confirm]').click()
                driver.find_element(By.CSS_SELECTOR, '.intake-receipt-discard button').click()
                wait.until(lambda _: page_has_text('Receipt discarded.'))
            discard_from_browser(removable['receipt_id'])
            require(bench.workspace.upload_session_record(full_matter.matter_id, ACTOR,
                latest_session.upload_session_id).state == 'cancelled', 'Empty upload remained active after owner cleanup')
            require(full_receipt_count() == 999, 'Owner discard did not release receipt capacity')
            driver.find_element(By.CSS_SELECTOR, '[data-file-input]').send_keys(str(folder/'Unsupported/opaque.bin'))
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-confirm]').text == 'Save selection receipt')
            confirm()
            wait.until(lambda x: x.find_element(By.CSS_SELECTOR, '[data-upload-preflight-state]').text == 'Selection receipt saved')
            require(full_receipt_count() == 1_000, 'Selection could not recover after owner cleanup')
            discard_from_browser(unbound_receipt_id)
            require(full_receipt_count() == 999, 'Owner cleanup of a sealed all-skipped receipt did not release capacity')
            record_check('Real receipt capacity refuses excess selections; owner cleanup cancels an empty bound upload, admits a new receipt and also removes sealed skips')

            for relative, body in fixtures.items():
                require((folder/relative).read_bytes() == body, 'Original selected fixture changed')
            record_check('All external originals remain byte-identical')
            report['passed'] = True
            print(json.dumps(report, indent=2))
        except Exception:
            if driver:
                try:
                    driver.save_screenshot(str(output/'failure.png'))
                    (output/'browser-errors.json').write_text(json.dumps(driver.get_log('browser'), indent=2))
                except Exception:
                    pass
            raise
        finally:
            (output/'receipt-browser-result.json').write_text(json.dumps(report, indent=2)+'\n')
            if driver:
                driver.quit()
            if server:
                server.should_exit = True
            if thread:
                thread.join(15)
            if sock:
                sock.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
