"""Native macOS bundle acceptance with fictional data and zero AI inference."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from academic_profile.library import initialize_home
from academic_profile.ai_workflow import save_note, add_proposal_batch
from playwright.sync_api import sync_playwright, expect


def api(url, value=None):
    with urlopen(Request(url, data=json.dumps(value).encode() if value is not None else None,
        headers={'Content-Type': 'application/json', 'X-Academic-Profile': 'mac-acceptance'}), timeout=10) as response:
        return json.load(response)


def start(app, home):
    executable = app / 'Contents/MacOS/昭濂个人履历库'
    process = subprocess.Popen([str(executable)])
    marker = home / 'private/desktop-server.local.json'
    for _ in range(150):
        try:
            value = json.loads(marker.read_text(encoding='utf-8'))
            url = f"http://127.0.0.1:{value['port']}"
            if api(url + '/api/health')['version'] == '0.4.0':
                assert process.wait(timeout=10) == 0
                return url, value
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(.2)
    raise RuntimeError('Native Mac app failed to start')


def stop(url):
    api(url + '/api/shutdown', {})
    for _ in range(80):
        try:
            api(url + '/api/health')
        except OSError:
            return
        time.sleep(.1)
    raise RuntimeError('Isolated Mac server did not stop')


def main():
    original_app = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='zhaolian-mac-') as directory:
        container = Path(directory) / '带空格的 迁移文件夹'
        app = container / '启动程序' / original_app.name
        app.parent.mkdir(parents=True)
        shutil.copytree(original_app, app, symlinks=True)
        home = container / '个人资料'
        identity = initialize_home(home)
        (container / 'portable-library.json').write_text(json.dumps({'library': '个人资料', 'library_id': identity}), encoding='utf-8')
        url = None
        try:
            url, marker = start(app, home)
            assert api(url + '/api/dashboard')['total'] == 0
            auth_url = api(url + '/api/ai/connect', {})['authorization_url']
            host = parse_qs(urlparse(auth_url).query)['ext_agent_host_id'][0]
            # This starts local OAuth bookkeeping only, not a remote login/request.
            duplicate_url, duplicate = start(app, home)
            assert duplicate_url == url and duplicate['pid'] == marker['pid']
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1400, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('dialog', lambda dialog: dialog.accept())
                page.route('**/api/ai/status', lambda route: route.fulfill(json={'connected': True, 'sharing': True}))
                page.route('**/api/ai/models', lambda route: route.fulfill(json={'models': [
                    {'slug': 'fake-first', 'display_name': '模拟一'}, {'slug': 'fake-chosen', 'display_name': '模拟二'}]}))
                page.route('https://**', lambda route: route.abort())
                page.goto(url)
                expect(page.locator('.category-grid')).to_be_visible()
                page.get_by_role('button', name='管理分类', exact=True).click()
                category = page.locator('[data-settings-category="coursework"]')
                category.locator('summary').click()
                category.locator('[data-managed-field="semester"] [name="label"]').fill('学习阶段')
                category.get_by_role('button', name='保存设置', exact=True).click()
                expect(page.locator('.toast').filter(has_text='本分类的全部设置已保存')).to_be_visible()
                page.locator('#category-nav [data-category="coursework"]').click()
                page.locator('#new-record').click()
                page.locator('#record-form [name="course_name"]').fill('Mac虚构验收课程')
                page.locator('#record-form [name="semester"]').fill('第一学期')
                page.get_by_role('button', name='保存记录', exact=True).click()
                expect(page.locator('.record-card h2')).to_have_text('Mac虚构验收课程')
                page.locator('#record-search').fill('第一学期')
                expect(page.locator('.record-card')).to_have_count(0)
                page.locator('#record-search').fill('Mac虚构')
                expect(page.locator('.record-card')).to_have_count(1)
                page.locator('.sidebar [data-view="settings"]').click()
                expect(page.locator('#settings-model')).to_be_visible()
                page.locator('#settings-model').select_option('fake-chosen')
                expect(page.locator('.toast').filter(has_text='模型')).to_be_visible()
                note = save_note(home, 'Mac本机虚构草稿')
                add_proposal_batch(home, note['id'], [{'category': 'coursework', 'fields': {'course_name': 'Mac候选课程'}}], [])
                page.locator('.sidebar [data-view="notes"]').click()
                page.locator('[data-open-batch]').first.click()
                expect(page.locator('.candidate-title')).to_have_value('Mac候选课程')
                page.get_by_role('button', name='保存审核结果', exact=True).click()
                expect(page.locator('#review-save')).to_have_text('已完成')
                assert api(url + '/api/ai/notes')['notes'] == []
                assert not errors, errors
                browser.close()
            stop(url)
            url = None
            moved = Path(directory) / '第二个位置'
            shutil.move(container, moved)
            home = moved / '个人资料'
            app = moved / '启动程序' / original_app.name
            url, _ = start(app, home)
            assert api(url + '/api/health')['library_id'] == identity
            assert len(api(url + '/api/records/coursework')['records']) == 2
            assert api(url + '/api/preferences')['ai_model'] == 'fake-chosen'
            second_url = api(url + '/api/ai/connect', {})['authorization_url']
            assert parse_qs(urlparse(second_url).query)['ext_agent_host_id'][0] == host
            print('PASS: native Mac startup, repeat launch, real Keychain encryption/restart, complete-folder move, records, settings, search, review, model memory; no real AI requests.')
        finally:
            if url:
                stop(url)


if __name__ == '__main__':
    main()
