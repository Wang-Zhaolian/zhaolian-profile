"""Make public screenshots exclusively from temporary fictional records."""
from __future__ import annotations
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from academic_profile.library import initialize_home
from academic_profile.webapp import create_app
from test_ai_webapp import FakeAuth, FakeProvider, _post


def main():
    output = ROOT / "docs/images"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zhaolian-demo-") as directory:
        home = Path(directory)
        initialize_home(home)
        app = create_app(home, ai_auth=FakeAuth(sharing=False), ai_provider=FakeProvider('{"candidates":[]}'))
        client = app.test_client()
        for title, grade, credits, semester in (("数据分析基础", "92", "3", "2026 年春季"),
              ("科学写作与表达", "88", "2", "2026 年春季"), ("研究方法导论", "95", "3", "2026 年秋季"),
              ("开放科学实践", "90", "2", "2026 年秋季")):
            response = _post(client, "/api/records/coursework", {"revision": client.get("/api/records/coursework").json["revision"],
                "record": {"course_name": title, "institution": "示例大学（虚构）", "semester": semester,
                           "credits": credits, "grade": grade, "record_state": "draft"}})
            assert response.status_code == 200
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1500, "height": 1040}, device_scale_factor=1)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                expect(page.locator('.category-grid')).to_be_visible()
                page.screenshot(path=str(output / "overview.png"))
                page.locator('#category-nav [data-category="coursework"]').click()
                expect(page.locator('.record-card')).to_have_count(4)
                page.screenshot(path=str(output / "records.png"))
                page.locator('.sidebar [data-view="settings"]').click()
                expect(page.locator('#backup-repository')).to_have_value('')
                page.locator('#backup-repository').fill('demo/private-library')
                page.get_by_role('button', name='保存备份设置', exact=True).click()
                expect(page.locator('.toast').filter(has_text='备份设置已保存在本机')).to_be_visible()
                expect(page.locator('#backup-repository')).to_have_value('demo/private-library')
                assert client.get('/api/backup/config').json['repository'] == 'demo/private-library'
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
    print('Public fictional screenshots and private-backup settings browser check passed.')


if __name__ == '__main__':
    main()
