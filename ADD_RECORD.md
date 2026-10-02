# 添加和维护学术记录

这个项目采用事件驱动更新。完成科研、结课、投稿、获奖、竞赛结束或完成重要项目时，更新一次对应 YAML；每学期末再做一次统一审计。

## 哪些内容应该进入系统

只记录具有长期履历价值且已经形成可描述成果的内容，例如正式课程成绩、科研项目、论文、重要软件项目、奖项、竞赛结果、学术汇报、语言成绩和有证据支持的技术能力。每日任务、论文阅读进度、研究日志和临时想法留在 Research OS，不写入这里。

## 选择正确文件

| 事件 | 文件 | ID 前缀 |
| --- | --- | --- |
| 入学、转专业、毕业信息变化 | `data/education.yaml` | `education_` |
| 科研项目开始或形成阶段成果 | `data/research.yaml` | `research_` |
| 投稿、录用或发表 | `data/publications.yaml` | `paper_` |
| 独立软件、复现或工程项目 | `data/projects.yaml` | `project_` |
| 获得奖项 | `data/awards.yaml` | `award_` |
| 竞赛产生正式结果 | `data/competitions.yaml` | `competition_` |
| 课程结课并得到最终成绩 | `data/coursework.yaml` | `course_` |
| 技能获得可验证的新证据 | `data/skills.yaml` | `skill_` |
| 完成学术报告或海报 | `data/presentations.yaml` | `presentation_` |
| 获得英语考试成绩 | `data/english.yaml` | `english_` |
| 形成长期有意义的活动经历 | `data/activities.yaml` | `activity_` |
| 增加公开主页或作品链接 | `data/links.yaml` | `link_` |

## 手工添加流程

1. 复制同一文件中最接近的记录，或参考 `sample_data/data/`。
2. 分配从未使用过的稳定 ID。标题变更时不要修改 ID。
3. 日期只写 `YYYY-MM` 或 `YYYY-MM-DD`。
4. 详细材料写入 `raw_details`、`description` 和 `my_contribution`；用于正式 CV 的句子单独写入 `cv_bullets`。
5. 新记录默认使用 `cv_eligible: false`，内容和证据确认后再改为 `true`。
6. `priority` 使用 1 到 5，1 最高。Profile 只自动选择达到其优先级阈值的记录。
7. 通过 `paper_ids`、`research_id`、`skill_ids` 等 ID 建立关系，不复制另一条记录的完整内容。
8. 运行 `uv run academic-profile validate` 和 `uv run academic-profile lint`。
9. 生成目标 CV 并人工阅读。

## 最小研究记录示例

```yaml
- id: research_002
  title: Your research title
  institution: Your institution
  advisor: Advisor name
  start_date: 2026-09
  status: active
  research_area: Research area
  research_question: The concrete question being studied
  description: One factual description of the work
  my_contribution:
    - What you personally designed or implemented
  methods: []
  tools: []
  results: []
  outputs: []
  paper_ids: []
  presentation_ids: []
  skill_ids: []
  evidence: []
  raw_details: []
  cv_bullets:
    - A checked application-ready sentence that states your action and its result.
  cv_eligible: false
  priority: 3
  tags: []
```

## 交互式添加

`uv run python add.py research` 会逐项询问核心字段并分配下一个 ID。它把 `cv_eligible` 默认设为 `false`，因此添加后仍需手工补充贡献、证据和 CV bullets，再运行验证。

## 修改和归档

直接修改原记录，不要创建标题略有不同的副本。停止用于 CV 的经历设置 `archived: true`；不要删除历史记录。Profile 临时覆盖可使用：

```yaml
include_for:
  phd: true
  internship: false
```

只填写需要覆盖默认规则的 Profile，不需要列出全部五种场景。

