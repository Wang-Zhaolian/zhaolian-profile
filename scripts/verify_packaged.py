"""Exercise a real desktop bundle with isolated data and mocked browser AI."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from playwright.sync_api import sync_playwright, expect
from academic_profile.ai_workflow import add_proposal_batch, save_note


def request(url, payload=None):
    value = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json", "X-Academic-Profile": "isolated-acceptance"})
    with urllib.request.urlopen(value, timeout=5) as response:
        return json.load(response)


def start(executable, environment, home):
    launcher = subprocess.Popen([str(executable)], env=environment, cwd=executable.parent,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + 40
    marker = home / "private/desktop-server.local.json"
    while time.monotonic() < deadline:
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            url = f"http://127.0.0.1:{value['port']}"
            info = request(url + "/api/health")
            if info.get("version") == "0.3.0":
                launcher.wait(timeout=10)
                assert launcher.returncode == 0
                return url, value
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(.2)
    raise RuntimeError(f"Packaged startup timed out; log: {home / '.runtime/server.log'}")


def stop(url):
    request(url + "/api/shutdown", {})
    for _ in range(60):
        try:
            request(url + "/api/health")
        except OSError:
            return
        time.sleep(.1)
    raise RuntimeError("Isolated test server did not exit")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    test_root = Path(tempfile.mkdtemp(prefix="packaged-acceptance-", dir=runtime))
    local = test_root / "windows-local-data"
    home = local / "ZhaolianProfile"
    environment = dict(os.environ, LOCALAPPDATA=str(local))
    environment.pop("ZHAOLIAN_PROFILE_HOME", None)
    url = None
    try:
        url, marker = start(executable, environment, home)
        assert request(url + "/api/dashboard")["total"] == 0
        assert request(url + "/api/backup/config")["repository"] == ""
        assert not request(url + "/api/ai/status")["connected"]
        duplicate = subprocess.run([str(executable)], env=environment, cwd=executable.parent, timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert duplicate.returncode == 0
        assert json.loads((home / "private/desktop-server.local.json").read_text())["pid"] == marker["pid"]
        for name in ("static/app.js", "static/app.css", "templates/index.html", "static/branding/app.ico"):
            source = (ROOT / name).read_bytes()
            bundled = (executable.parent / "_internal" / name).read_bytes()
            if not name.endswith('.ico'):
                source = source.replace(b'\r\n', b'\n')
                bundled = bundled.replace(b'\r\n', b'\n')
            assert hashlib.sha256(bundled).digest() == hashlib.sha256(source).digest()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 1040})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.route("**/api/ai/status", lambda route: route.fulfill(json={"connected": True, "sharing": True}))
            page.route("**/api/ai/models", lambda route: route.fulfill(json={"models": [
                {"slug": "test-first", "display_name": "模拟模型一"}, {"slug": "test-chosen", "display_name": "模拟模型二"}]}))
            page.route("https://**", lambda route: route.abort())
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
            page.locator('#record-form [name="course_name"]').fill('独立验收课程')
            page.locator('#record-form [name="semester"]').fill('第一学期')
            page.get_by_role('button', name='保存记录', exact=True).click()
            expect(page.locator('.record-card')).to_have_count(1)
            page.locator('.record-card').first.click()
            page.locator('#record-form [name="course_name"]').fill('修改后的验收课程')
            page.get_by_role('button', name='保存记录', exact=True).click()
            expect(page.locator('.record-card h2')).to_have_text('修改后的验收课程')
            page.locator('#record-search').fill('第一学期')
            expect(page.locator('.record-card')).to_have_count(0)
            page.locator('#record-search').fill('验收课程')
            expect(page.locator('.record-card')).to_have_count(1)
            page.locator('.sidebar [data-view="settings"]').click()
            expect(page.locator('#settings-model')).to_be_visible()
            page.locator('#settings-model').select_option('test-chosen')
            expect(page.locator('.toast').filter(has_text='模型')).to_be_visible()
            assert request(url + '/api/preferences')['ai_model'] == 'test-chosen'
            page.locator('#backup-repository').fill('example/isolated-private')
            page.get_by_role('button', name='保存备份设置', exact=True).click()
            expect(page.locator('.toast').filter(has_text='备份设置已保存在本机')).to_be_visible()
            # Prepare fictional candidates locally; never invoke the real provider.
            note = save_note(home, '仅供验收的课程资料')
            add_proposal_batch(home, note['id'], [{'category': 'coursework', 'fields': {'course_name': '候选验收课程'}}], [])
            page.locator('.sidebar [data-view="notes"]').click()
            page.locator('[data-open-batch]').first.click()
            expect(page.locator('.candidate-title')).to_have_value('候选验收课程')
            fail = [True]
            def once(route):
                if route.request.method == 'POST' and fail[0]:
                    fail[0] = False
                    route.fulfill(status=409, json={'error': '模拟并发冲突'})
                else:
                    route.continue_()
            page.route('**/api/records/coursework', once)
            page.get_by_role('button', name='保存审核结果', exact=True).click()
            expect(page.locator('#review-save')).to_have_text('重试失败项')
            expect(page.locator('.candidate-title')).to_have_value('候选验收课程')
            page.locator('#review-save').click()
            expect(page.locator('#review-save')).to_have_text('已完成')
            assert request(url + '/api/ai/notes')['notes'] == []
            assert len(request(url + '/api/records/coursework')['records']) == 2
            assert not errors, errors
            browser.close()
        # A date may stay empty even after completing an otherwise valid record.
        records = request(url + '/api/records/awards')
        result = request(url + '/api/records/awards', {'revision': records['revision'], 'record': {
            'name': '虚构验收奖项', 'level': '校级', 'organizer': '示例机构', 'result': '获奖', 'record_state': 'ready'}})
        assert result['record']['record_state'] == 'ready'
        identity = request(url + '/api/health')['library_id']
        stop(url)
        url = None
        url, _ = start(executable, environment, home)
        assert request(url + '/api/health')['library_id'] == identity
        assert len(request(url + '/api/records/coursework')['records']) == 2
        assert request(url + '/api/preferences')['ai_model'] == 'test-chosen'
        assert request(url + '/api/backup/config')['repository'] == 'example/isolated-private'
        assert any(field['label'] == '学习阶段' for field in request(url + '/api/config')['fields']['coursework'])
        print('PASS: real packaged startup, duplicate reuse, exit/restart, blank library, resources, record edits, title search, settings, model persistence, review conflict/retry, draft removal, optional date.')
        print(f'Isolated acceptance directory: {test_root}')
    finally:
        if url:
            stop(url)


if __name__ == '__main__':
    main()
