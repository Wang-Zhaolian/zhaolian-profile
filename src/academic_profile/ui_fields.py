"""Chinese labels and form fields for the local browser interface."""

from __future__ import annotations

from typing import Any

CATEGORIES = [
    {"id": "education", "label": "教育经历", "icon": "学", "title_field": "degree"},
    {"id": "research", "label": "科研经历", "icon": "研", "title_field": "title"},
    {"id": "publications", "label": "论文", "icon": "文", "title_field": "title"},
    {"id": "projects", "label": "项目", "icon": "项", "title_field": "name"},
    {"id": "awards", "label": "奖项", "icon": "奖", "title_field": "name"},
    {"id": "competitions", "label": "竞赛", "icon": "赛", "title_field": "name"},
    {"id": "coursework", "label": "课程", "icon": "课", "title_field": "course_name"},
    {"id": "skills", "label": "技能", "icon": "技", "title_field": "category"},
    {"id": "presentations", "label": "学术汇报", "icon": "讲", "title_field": "title"},
    {"id": "english", "label": "英语成绩", "icon": "英", "title_field": "test"},
    {"id": "activities", "label": "活动", "icon": "活", "title_field": "name"},
    {"id": "links", "label": "相关链接", "icon": "链", "title_field": "label"},
]

COMMON_FIELDS = [
    {"key": "title", "label": "名称", "type": "text", "required_for_ready": True},
    {"key": "date", "label": "日期", "type": "date", "advanced": False},
    {"key": "start_date", "label": "开始时间", "type": "date", "advanced": False},
    {"key": "end_date", "label": "结束时间", "type": "date", "advanced": False},
]

FIELD_DEFINITIONS: dict[str, list[dict[str, Any]]] = {
    "education": [
        ("institution", "学校", "text", False), ("school", "院系", "text", True),
        ("degree", "学位", "text", False), ("major", "专业", "text", False),
        ("start_date", "开始时间", "date", False),
        ("expected_graduation", "预计毕业时间", "date", False),
        ("gpa", "GPA", "text", True), ("gpa_scale", "GPA 满分", "text", True),
        ("rank", "排名", "text", True), ("rank_total", "总人数", "text", True),
        ("honors", "荣誉", "list", True), ("location", "地点", "text", True),
        ("institution_zh", "学校中文名", "text", True),
        ("degree_zh", "学位中文名", "text", True),
        ("major_zh", "专业中文名", "text", True),
        ("cv_bullets", "用于简历的要点", "list", True),
        ("cv_bullets_en", "英文简历要点", "list", True),
        ("cv_bullets_zh", "中文简历要点", "list", True),
    ],
    "research": [
        ("title", "科研名称", "text", False), ("institution", "学校或机构", "text", False),
        ("advisor", "导师", "text", False), ("start_date", "开始时间", "date", False),
        ("end_date", "结束时间", "date", False),
        ("status", "科研阶段", "select:idea,literature,method,experiment,writing,submitted,completed", True),
        ("research_area", "研究方向", "text", False),
        ("research_question", "研究问题", "textarea", True),
        ("description", "经历描述", "textarea", False),
        ("my_contribution", "个人贡献", "list", False),
        ("methods", "研究方法", "list", True), ("tools", "工具", "list", True),
        ("results", "研究结果", "list", True), ("outputs", "成果说明", "list", True),
        ("paper_ids", "关联论文", "relation:publications", True),
        ("presentation_ids", "关联汇报", "relation:presentations", True),
        ("skill_ids", "关联技能", "relation:skills", True),
        ("repository", "代码仓库链接", "url", True),
        ("evidence", "证明材料路径或网址", "list", True),
        ("cv_bullets", "用于简历的要点", "list", True),
        ("title_zh", "科研名称中文译文", "text", True),
        ("description_zh", "经历描述中文译文", "textarea", True),
        ("raw_details", "详细经历（原始事实）", "textarea", True),
        ("cv_bullets_en", "英文简历要点", "list", True),
        ("cv_bullets_zh", "中文简历要点", "list", True),
    ],
    "publications": [
        ("title", "论文标题", "text", False), ("authors", "作者（每行一位）", "list", False),
        ("my_author_position", "我的作者顺序", "text", False), ("venue", "期刊或会议", "text", False),
        ("year", "年份", "number", False),
        ("status", "论文状态", "select:published,accepted,under_review,submitted,preprint,manuscript", False),
        ("doi", "DOI", "text", True), ("url", "论文链接", "url", True),
        ("arxiv", "arXiv 编号", "text", True),
        ("research_id", "关联科研", "relation_one:research", True),
        ("citation", "引用格式", "textarea", True), ("notes", "备注", "textarea", True),
        ("title_zh", "论文标题中文译文", "text", True),
        ("cv_bullets", "用于简历的要点", "list", True),
    ],
    "projects": [
        ("name", "项目名称", "text", False), ("type", "项目类型", "text", False),
        ("start_date", "开始时间", "date", False), ("end_date", "结束时间", "date", False),
        ("status", "项目状态", "select:planned,active,completed,archived", True),
        ("description", "项目描述", "textarea", False),
        ("my_contribution", "个人贡献", "list", False),
        ("tech_stack", "使用技术（每行一项）", "list", False),
        ("repository", "代码仓库链接", "url", True), ("demo", "演示链接", "url", True),
        ("results", "结果", "list", True), ("skill_ids", "关联技能", "relation:skills", True),
        ("competition_ids", "关联竞赛", "relation:competitions", True),
        ("cv_bullets", "用于简历的要点", "list", True),
        ("name_zh", "项目名称中文译文", "text", True),
        ("raw_details", "详细项目经历（原始事实）", "textarea", True),
    ],
    "awards": [
        ("name", "奖项名称", "text", False), ("level", "级别", "text", False),
        ("organizer", "颁发机构", "text", False), ("date", "获奖日期", "date", False),
        ("result", "获奖结果", "text", False), ("team", "团队奖", "bool", True),
        ("role", "个人角色", "text", True), ("description", "说明", "textarea", True),
        ("evidence", "证明材料路径或网址", "list", True),
        ("cv_bullets", "用于简历的要点", "list", True),
    ],
    "competitions": [
        ("name", "竞赛名称", "text", False), ("level", "级别", "text", False),
        ("organizer", "主办方", "text", False), ("date", "日期", "date", False),
        ("result", "比赛结果", "text", False), ("team", "团队参赛", "bool", True),
        ("role", "个人角色", "text", True), ("description", "说明", "textarea", True),
        ("project_id", "关联项目", "relation_one:projects", True),
        ("evidence", "证明材料路径或网址", "list", True),
        ("cv_bullets", "用于简历的要点", "list", True),
    ],
    "coursework": [
        ("course_name", "课程名称", "text", False), ("institution", "学校", "text", False),
        ("semester", "学期", "text", False), ("credits", "学分", "text", True),
        ("grade", "成绩", "text", False), ("rank_if_known", "已知课程排名", "text", True),
        ("category", "课程类别", "text", False),
        ("level", "课程难度", "select:introductory,intermediate,advanced,graduate", False),
        ("topics", "课程主题（每行一项）", "list", True),
        ("skill_ids", "关联技能", "relation:skills", True),
        ("transcript_visible", "成绩单上可见", "bool", False), ("notes", "备注", "textarea", True),
    ],
    "skills": [
        ("category", "技能类别", "select:Programming,ML,Data,Optimization,Research Tools,Development Tools,Languages", False),
        ("items", "技能（每行一项）", "list", False), ("level", "掌握情况说明", "text", True),
        ("evidence", "使用或成果证据", "list", True), ("last_used", "最近使用", "date", True),
    ],
    "presentations": [
        ("title", "报告或海报标题", "text", False), ("event", "会议或活动", "text", False),
        ("date", "日期", "date", False), ("location", "地点", "text", True),
        ("research_id", "关联科研", "relation_one:research", True),
        ("url", "报告链接", "url", True), ("evidence", "材料路径或网址", "list", True),
        ("cv_bullets", "用于简历的要点", "list", True),
    ],
    "english": [
        ("test", "考试名称", "text", False), ("score", "总分", "text", False),
        ("date", "考试日期", "date", False),
        ("subscores", "单项成绩（每行一项，例如 Reading: 28）", "map", True),
        ("evidence", "成绩单路径或网址", "list", True),
    ],
    "activities": [
        ("name", "活动名称", "text", False), ("organization", "组织", "text", False),
        ("role", "个人角色", "text", False), ("start_date", "开始时间", "date", False),
        ("end_date", "结束时间", "date", True),
        ("status", "活动状态", "select:planned,active,completed,archived", True),
        ("description", "活动描述", "textarea", True),
        ("cv_bullets", "用于简历的要点", "list", True),
    ],
    "links": [
        ("label", "链接名称", "text", False), ("url", "网址", "url", False),
    ],
}

# Required only when a user explicitly marks a record as ready. Drafts may be
# incomplete, so browser controls never block saving a draft.
READY_REQUIRED = {
    "education": {"institution", "degree", "major", "start_date", "expected_graduation"},
    "research": {"title", "institution", "start_date", "status"},
    "publications": {"title", "authors", "my_author_position", "year", "status"},
    "projects": {"name", "type", "start_date", "status"},
    "awards": {"name", "level", "organizer", "date", "result"},
    "competitions": {"name", "level", "organizer", "date", "result"},
    "coursework": {"course_name", "institution", "semester", "category", "level", "transcript_visible"},
    "skills": {"category", "items"},
    "presentations": {"title", "event", "date"},
    "english": {"test", "score", "date"},
    "activities": {"name", "organization", "role", "start_date", "status"},
    "links": {"label", "url"},
}

# Expose fields as JSON serializable mappings to the frontend.
FORM_FIELDS: dict[str, list[dict[str, Any]]] = {}
for category, definitions in FIELD_DEFINITIONS.items():
    FORM_FIELDS[category] = [
        {
            "key": key, "label": label, "type": kind, "advanced": advanced,
            "required_for_ready": key in READY_REQUIRED[category],
        }
        for key, label, kind, advanced in definitions
    ]

PROFILE_LABELS = {
    "phd": "博士申请",
    "ra": "科研助理申请",
    "summer_research": "暑期科研申请",
    "domestic": "国内升学申请",
    "internship": "实习申请",
}
