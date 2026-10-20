"""Isolated browser acceptance. Run with uv run --with playwright python ... ."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from academic_profile.ai_workflow import add_proposal_batch, save_note
from academic_profile.categories import default_registry, save_registry
from test_ai_webapp import FakeAuth, FakeProvider, _client, _post


def main():
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    # Fresh synthetic data only; no user credentials, notes or live server.
    home = Path(tempfile.mkdtemp(prefix="ui-refinements-", dir=runtime)) / "home"
    client, app = _client(home, auth=FakeAuth(sharing=False), provider=FakeProvider('{"candidates":[]}'))
    save_registry(home, default_registry())
    revision = client.get("/api/records/coursework").get_json()["revision"]
    saved = _post(client, "/api/records/coursework", {"revision": revision, "record": {
        "course_name": "管理学原理", "institution": "测试大学", "semester": "第一学期", "grade": "优秀",
    }})
    assert saved.status_code == 200
    note = save_note(home, "人工验收用的课程和项目资料")
    add_proposal_batch(home, note["id"], [
        {"category": "coursework", "fields": {"course_name": "转为项目", "semester": "第一学期", "grade": "优秀"}},
        {"category": "coursework", "fields": {"course_name": "应删除的候选"}},
        {"category": "coursework", "fields": {"course_name": "稍后处理的候选", "grade": "良好"}},
    ], [])
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.get_by_role("button", name="管理分类", exact=True).click()
            category = page.locator('[data-settings-category="coursework"]')
            category.locator('summary').click()
            category.locator('[data-managed-field="institution"] [data-delete-field]').click()
            category.locator('[data-managed-field="semester"] [name="label"]').fill("学习阶段")
            category.locator('.add-field-form [name="label"]').fill("个人心得")
            category.locator('.add-field-form [name="type"]').select_option("textarea")
            category.get_by_role("button", name="添加项目", exact=True).click()
            assert category.get_by_role("button", name="保存字段", exact=True).count() == 0
            category.get_by_role("button", name="保存设置", exact=True).click()
            expect(category.locator('[data-managed-field="institution"]')).to_have_count(0)
            expect(page.locator('.toast').filter(has_text="本分类的全部设置已保存")).to_be_visible()
            page.screenshot(path=str(runtime / "refinements-settings.png"))
            cfg = client.get("/api/config").get_json()
            assert any(field["label"] == "个人心得" for field in cfg["fields"]["coursework"])
            assert "institution" not in {field["key"] for field in cfg["fields"]["coursework"]}
            page.locator('#category-nav [data-category="coursework"]').click()
            card = page.locator('.record-card').first
            expect(card.locator('h2')).to_have_text("管理学原理")
            expect(card).to_contain_text("学习阶段：第一学期")
            expect(card).to_contain_text("成绩：优秀")
            assert "course_" not in card.inner_text() and "日期未填" not in card.inner_text()
            page.screenshot(path=str(runtime / "refinements-cards.png"))
            page.get_by_role("button", name="列表", exact=True).click()
            expect(page.locator('.record-table')).to_contain_text("学习阶段：第一学期")
            page.locator('.record-table tbody tr').first.click()
            expect(page.locator('#record-form')).to_be_visible()
            assert page.locator('#record-form [name="institution"]').count() == 0
            page.locator('#modal-host [data-close]').first.click()
            page.locator('.sidebar [data-view="notes"]').click()
            page.locator('[data-open-batch]').first.click()
            first = page.locator('.candidate-card').nth(0)
            first.locator('[data-field="semester"]').locator('..').get_by_role('button', name="删除此项").click()
            assert first.locator('[name="semester"]').count() == 0
            first.locator('.candidate-category-select').select_option("projects")
            first = page.locator('.candidate-card').nth(0)
            first.locator('.candidate-title').fill("人工修改的项目")
            page.locator('.candidate-card').nth(1).get_by_role('button', name="删除此记录").click()
            page.locator('.candidate-card').nth(2).locator('.candidate-action').select_option('skip')
            assert page.get_by_text("采纳此字段", exact=True).count() == 0
            page.screenshot(path=str(runtime / "refinements-review.png"))
            page.get_by_role('button', name="保存审核结果", exact=True).click()
            expect(page.locator('#review-save')).to_have_text("已完成")
            records = client.get('/api/records/projects').get_json()['records']
            assert len(records) == 1 and records[0]['name'] == '人工修改的项目'
            assert client.get('/api/ai/notes').get_json()['notes'][0]['pending_candidates'] == 1
            page.locator('[data-review-close]').first.click()
            page.locator('[data-open-batch]').first.click()
            expect(page.locator('.candidate-card')).to_have_count(1)
            page.locator('.candidate-title').fill('刷新后保留的修改')
            page.locator('[data-review-close]').first.click()
            page.reload()
            page.locator('.sidebar [data-view="notes"]').click()
            page.locator('[data-open-batch]').first.click()
            expect(page.locator('.candidate-title')).to_have_value('刷新后保留的修改')
            # Fail one actual HTTP write once. Both the input and draft must stay.
            failures = [0]
            def once(route):
                if route.request.method == 'POST' and failures[0] == 0:
                    failures[0] += 1
                    route.fulfill(status=409, content_type='application/json', body=json.dumps({'error':'验收模拟并发冲突'}))
                else:
                    route.continue_()
            page.route('**/api/records/coursework', once)
            page.get_by_role('button', name="保存审核结果", exact=True).click()
            expect(page.locator('#review-save')).to_have_text('重试失败项')
            expect(page.locator('.candidate-title')).to_have_value('刷新后保留的修改')
            assert len(client.get('/api/ai/notes').get_json()['notes']) == 1
            page.locator('#review-save').click()
            expect(page.locator('#review-save')).to_have_text('已完成')
            assert client.get('/api/ai/notes').get_json()['notes'] == []
            assert len(client.get('/api/records/coursework').get_json()['records']) == 2
            page.locator('[data-review-close]').first.click()
            expect(page.locator('.note-card')).to_have_count(0)
            page.screenshot(path=str(runtime / 'refinements-empty-drafts.png'))
            assert not errors, errors
            browser.close()
        print('PASS: atomic settings, cards/list, editable review, deletion, deferred persistence, conflict retry, automatic draft removal; no real AI calls.')
        print(f'Synthetic test home: {home}')
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
