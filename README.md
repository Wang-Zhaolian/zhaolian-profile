# Academic Profile CV Database and Generator

`academic-profile` 是运行在个人 Windows 电脑上的学术履历平台。日常通过浏览器界面录入和整理资料；程序把记录保存在可读的 YAML 文件中，并按申请场景生成简历。`data/` 是唯一权威数据源；任何 CV 都不需要再手工维护一份。

平台只监听本机，不依赖数据库服务器或网络即可录入、保存和导出。需要备份时，手动点击界面中的“备份到 GitHub”；首次备份会在当前 GitHub 登录账户中创建 Private 仓库。真实分类文件初始为空，界面不会读取或展示演示数据。

## 日常使用

- 双击桌面上的 **Academic Profile** 快捷方式打开平台。首次制作本机程序包时运行一次 `scripts/build_windows.ps1`；日常使用不需要命令行、Python 或 LaTeX。
- 在“个人资料”中填写姓名；在左侧固定分类中逐条新增记录。可以先保存为草稿，以后补全后再选择“整理完成”。
- 只有整理完成且勾选“用于简历”的记录会进入简历预览。可切换博士申请、科研助理、暑期科研、国内升学和实习版本。
- 预览确认后可下载 PDF、Word 或 LaTeX。PDF 由内置排版生成，不要求安装 LaTeX。
- 平台自动保存到项目目录。联系方式放在本机 `private/contact.yaml`；证明材料请在记录中写本地路径或网址。它们不会上传 GitHub。
- “备份与设置”会清楚显示仓库、待备份状态和上次成功时间。遇到网络、权限或远端冲突时，本机资料仍会保留；冲突不会强制覆盖。

## 系统流程

```text
data/*.yaml
    -> schema and cross-reference validation
    -> profile selection and deterministic CV lint
    -> shared CV content model
    -> cv.tex, cv.docx, and an embedded-layout cv.pdf
```

预览、PDF、Word 和 LaTeX 共用同一份筛选结果，因此各格式内容一致。版式允许略有差异。

## 目录职责

```text
academic-profile/
├── data/                 真实 Master Academic Record，初始为空
├── private/              本地联系方式；contact.yaml 被 Git 忽略
├── evidence/             成绩单、证书、未发表材料等；内容默认被 Git 忽略
├── profiles/             五种申请场景的章节顺序与筛选规则
├── schemas/              每类 YAML 的 JSON Schema 2020-12 约束
├── sample_data/          旧版隔离演示资料；平台不会读取或展示
├── templates/latex/      ATS-friendly 单栏 LaTeX 模板
├── templates/docx/       Word 样式模板
├── src/academic_profile/ 加载、验证、筛选、lint 与生成代码
├── scripts/              模板构建等维护脚本
├── tests/                自动测试
├── output/               生成结果；被 Git 忽略
├── ADD_RECORD.md         以后添加和维护经历的操作手册
├── generate.py           不安装命令行入口时的兼容脚本
└── pyproject.toml        Python 依赖与命令行配置
```

各数据文件的具体用途：

- `basics.yaml`：公开姓名、标题和研究兴趣。私人联系方式不放这里。
- `education.yaml`：学校、学位、专业、GPA、排名与荣誉。
- `research.yaml`：科研问题、个人贡献、方法、结果和科研产出关系。
- `publications.yaml`：论文作者、状态、年份、DOI 与关联科研。
- `projects.yaml`：独立于 Research 的软件、复现和工程项目。
- `awards.yaml` 与 `competitions.yaml`：奖项和竞赛结果。
- `coursework.yaml`：完整课程档案；Profile 只选择高阶且相关的课程。
- `skills.yaml`：按 Programming、ML、Data、Optimization、Research Tools、Development Tools、Languages 分类的技能与证据。
- `presentations.yaml`、`english.yaml`、`activities.yaml`、`links.yaml`：汇报、英语成绩、长期活动和公开链接。

## 源码维护（非日常操作）

需要 Python 3.11 或更新版本。推荐使用 `uv` 创建隔离环境：

```powershell
cd academic-profile
uv sync --extra dev
```

不使用 `uv` 时也可以创建普通虚拟环境，然后执行 `pip install -e ".[dev]"`。

首次填写联系方式时复制示例文件：

```powershell
Copy-Item private/contact.example.yaml private/contact.yaml
```

`private/contact.yaml` 已在 `.gitignore` 中。默认只建议填写姓名、邮箱、GitHub、个人网站和所在城市；不要保存身份证号、家庭地址或不必要的电话号码。

## 先运行虚构样例

以下命令验证并生成五种示例 CV，便于确认本机环境：

```powershell
uv run academic-profile validate --data-dir sample_data/data
uv run academic-profile lint --data-dir sample_data/data
uv run academic-profile generate all `
  --data-dir sample_data/data `
  --contact sample_data/private/contact.yaml `
  --output-root output/sample
```

输出位于 `output/sample/<profile>/cv.tex` 和 `cv.docx`。如果检测到 LaTeX 引擎，同目录还会有 `cv.pdf`。

## 填写真实数据

从 `data/basics.yaml` 和 `data/education.yaml` 开始，再依次录入 Research、Publication、Project、Coursework 和 Award。不要把 `sample_data/` 直接复制成真实数据；逐条参考其结构并替换为你核实过的事实。

所有主要记录使用不会随标题变化的 ID，例如 `research_001`、`paper_001`、`project_001` 和 `course_001`。跨文件关系只引用 ID：

```yaml
# data/publications.yaml
- id: paper_001
  research_id: research_001
```

日期只能使用 `YYYY-MM` 或 `YYYY-MM-DD`。生成时会自动显示为 `Sep 2026 - Present` 等格式。英文为主字段；只在需要时增加 `title_zh`、`description_zh` 或 `cv_bullets_zh`，没有中文字段时自动回退到英文。

详细字段、最小记录示例、归档方法和交互式添加见 [ADD_RECORD.md](ADD_RECORD.md)。

## 验证与 CV lint

```powershell
uv run academic-profile validate
uv run academic-profile lint
```

`validate` 检查 YAML Schema、必需字段、重复 ID、日期格式和顺序、空或非法 URL、不存在的跨表引用、论文状态与 Profile 定义。论文状态只允许：

```text
published accepted under_review submitted preprint manuscript
```

`lint` 不使用 AI。它检查可能重复的经历、明显拼写问题、重复空格、过长 bullet、缺少 Institution，以及 Research 中缺少个人贡献等规则。

## Profile 选择规则

五个预置 Profile 位于 `profiles/`：

- `phd`：Education、Research Interests、Research、Publications、Projects、Coursework、Awards、Presentations、Skills。
- `ra`：Research、复现项目、方法、编程、实验和论文。
- `summer_research`：Education、Coursework、Research、Projects、Skills 与 Awards。
- `domestic`：允许更多 GPA、排名、课程、奖项和竞赛内容。
- `internship`：优先 Projects、Skills、Programming 和应用型 Research，减少理论课程。

默认选择必须同时满足：`cv_eligible: true`、没有归档、`priority` 达到 Profile 阈值、标签未被排除。`priority: 1` 最高，`5` 最低。局部覆盖只写需要改变的场景：

```yaml
include_for:
  phd: true
  internship: false
```

`include_for: true` 可以越过优先级和标签规则，但不能让已归档记录重新出现。Generator 不会为了填满页面自动加入弱经历，也不会自动粗暴缩写 `raw_details`；CV 只使用你审核过的 `cv_bullets`。

## 生成不同 CV

```powershell
uv run academic-profile generate phd
uv run academic-profile generate ra
uv run academic-profile generate summer_research
uv run academic-profile generate domestic
uv run academic-profile generate internship
uv run academic-profile generate all
```

也支持兼容命令：

```powershell
python generate.py --profile phd
python generate.py validate
```

只生成一种格式：

```powershell
uv run academic-profile generate phd --format latex
uv run academic-profile generate phd --format docx
uv run academic-profile generate phd --format pdf
```

## LaTeX 与 PDF

LaTeX 模板是无照片、无图标、无技能进度条的单栏学术版式，保留 `.tex` 便于审查。生成命令依次查找 XeLaTeX、LuaLaTeX 和 pdfLaTeX；找到后自动编译两次并保留 PDF。

当前机器如果没有 LaTeX 引擎，命令仍会生成 `.tex` 和 `.docx`，并明确提示安装 TeX Live 或 MiKTeX。含中文内容时优先安装并使用 XeLaTeX 或 LuaLaTeX。安装完成后重新运行原生成命令即可，无需修改数据。

## Word

Word 输出由 `python-docx` 生成并使用 `templates/docx/academic_cv_template.docx` 中的页面和段落样式。修改 `scripts/build_docx_template.py` 后执行：

```powershell
uv run python scripts/build_docx_template.py
```

Word 版本适合要求 `.docx` 的场景或提交前少量人工微调。正式修改应尽快回写 YAML，否则下次生成会覆盖临时改动。

## 新增 Profile

复制一个最接近的 `profiles/*.yaml`，修改 `profile`、`sections`、`max_items`、`max_priority` 和标签规则。文件名必须与 `profile` 值一致。之后可直接运行：

```powershell
uv run academic-profile generate your_profile
```

章节只能引用已有数据类别；`research_interests` 是从 `data/basics.yaml` 读取的虚拟章节。

## 测试

```powershell
uv run pytest
```

测试覆盖 YAML 解析、ID 唯一性、Profile 筛选、日期格式、论文状态、跨表引用、五种 LaTeX 生成和 DOCX 生成。

## Git 与私人备份

仓库应保持 Private。首次提交：

```powershell
git status
git add .
git commit -m "Initialize academic profile database"
```

在 GitHub 上先创建一个空的 Private repository，再连接并推送：

```powershell
git remote add origin <your-private-repository-url>
git branch -M main
git push -u origin main
```

如果使用 GitHub CLI，也必须显式使用私有设置：

```powershell
gh repo create academic-profile --private --source . --remote origin --push
```

推送前始终运行 `git status` 和 `git check-ignore private/contact.yaml evidence/your-file.pdf`。被忽略的私人内容包括 `private/contact.yaml`、`evidence/` 中的材料和全部 `output/`。`data/` 可能仍含 GPA、排名、导师与未发表论文信息，因此即使忽略联系方式，远程仓库也必须保持私有。

## 建议维护节奏

论文投稿、课程结课、竞赛获奖、项目完成或暑研结束时立即更新相应记录。每学期末统一检查一次状态、证据、CV eligibility、priority、失效链接和五种 Profile 的生成结果。
