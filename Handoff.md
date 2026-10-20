# Literature Tracker Handoff

本文档用于把项目交接到新电脑或新维护者手中。

## 当前项目状态

- 项目根目录：`D:\codex\wenxian`
- Python 包名：`literature_tracker`
- UI 入口：`ui_app.py`
- CLI 入口：`python -m literature_tracker.cli`
- Conda 环境文件：`environment.yml`
- 当前数据库：`data/literature_tracker.db`
- 可选维护报告：`data/reports/latest_report.md`（手动生成）
- 信源配置：`文献源.csv`，131 个来源均已启用；已覆盖 71 + 27 本期刊，其中 9 本复用原配置、89 本新增。新增期刊统一使用已核对 ISSN 的 Crossref + PubMed，不依赖受限的官网页面；原 42 个来源配置保留。

`data/` 和 `.venv/` 都被 `.gitignore` 忽略。换电脑时，必须单独复制 `data/`，否则新机器只能重新抓取并重建数据库。

## 新电脑接手步骤

1. 克隆代码。

```powershell
git clone <repo-url> wenxian
cd wenxian
```

2. 创建环境。

```powershell
conda env create -f environment.yml
conda activate literature-tracker
```

3. 复制旧电脑数据。

```text
旧电脑: D:\codex\wenxian\data
新电脑: <repo>\data
```

4. 验证项目。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests
python -m literature_tracker.cli build-report
streamlit run ui_app.py
```

## 日常维护流程

完整更新一次文献库：

```powershell
python -m literature_tracker.cli run-all
```

安装每日计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_literature_tracker_task.ps1
```

计划任务通过 `run_literature_tracker_update_hidden.vbs` 无窗口调用 `run_literature_tracker_update.ps1`，日志写入 `data/scheduled_update.log`。流水线状态为 `partial` 或 `failed` 时退出码非零。

如果只想更新某个来源：

```powershell
python -m literature_tracker.cli crawl --source "合成生物学"
python -m literature_tracker.cli process --source "合成生物学"
python -m literature_tracker.cli detect-changes --source "合成生物学"
python -m literature_tracker.cli build-insights --source "合成生物学"
python -m literature_tracker.cli build-report --source "合成生物学"
```

## UI 说明

- `推荐`：默认显示最近 30 天首次入库、命中关注主题或作者的前 10 篇文章，展示匹配理由。支持时间范围和显示篇数选择，评分权重沿用原配置。
- `搜索`：覆盖标题、作者、DOI、摘要、来源和关键词；支持多词同时匹配、来源/关注主题/入库范围筛选及排序，每页 25 篇，提供一份搜索结果 CSV。
- `数据源`：每 10 秒刷新数据源状态与 Source Summary。正常、抓取中、未运行等来源排前，部分失败、失败及访问受限来源排后；保留官网网址。超过两天未成功运行显示为“超过两天未更新”。

界面依赖 Streamlit >=1.56，三个标签页按需渲染。`catalog.py` 只读取 `papers` 和当前评分结果，保留全部文献可搜索，包括尚未评分的记录；不加载完整变化历史。数据库及 WAL 变化使缓存失效，缓存最长 60 秒，也可点击“刷新页面数据”。

手动更新使用后台任务，侧边栏每 5 秒刷新完成状态，抓取期间可切换页面。同一网页服务不会因重复点击同时启动多个手动任务。

`run-all` 默认只执行采集、入库、变化检测和评分；需要维护报告时加 `--report` 或单独运行 `build-report`。原始数据、去重逻辑、历史记录与每日计划任务保留。

## 当前评分规则

评分逻辑在 `literature_tracker/insights/build.py`。

```text
priority_score =
  change_base_score
  + theme_score
  + author_score
  + recent_activity_score
```

当前配置：

```text
change_base_score:
- new_paper: 0.05
- content_updated: 0.10
- correction_notice: 0.16
- retraction_notice: 0.20
- default: 0.12

theme_score = min(0.40, `config/theme_watchlist.csv` 中命中项权重之和)
author_score = min(0.40, `config/author_watchlist.csv` 中命中项权重之和)
recent_activity_score = 0.20，最近 30 天内入库/更新
```

状态映射：

```text
score >= 0.85 -> review
score >= 0.65 -> pending
score < 0.65 -> watchlist
```

## 采集器说明

### 合成生物学

文件：`literature_tracker/collectors/cip.py`

- 平台：`magtech_cip`
- 优先解析 RSS。
- RSS 不可用时回退 `showNewArticle.do`。
- 详情页通过 citation meta 补标题、作者、DOI、PDF。
- Magtech/CIP 的完整摘要在详情页 `摘要/Abstract` 面板中，采集器有专门解析逻辑。

### Springer 来源

文件：`literature_tracker/collectors/springer.py`

- 平台：`springer`
- Advanced Biotechnology、Journal of Biological Engineering 和 Annals of Microbiology 通过通用 `CrossrefCollector` 按 ISSN 抓取，避免 Springer 列表页的 Client Challenge。
- 保留 DOI、标题、作者、发表日期、Crossref 主题和可用摘要；个别记录可能没有摘要。

### 通用期刊来源

文件：`literature_tracker/collectors/generic.py`

- 平台：`sciencedirect`、`oup`、`scientific_american`、`asm`、`science`、`cell`、`nature`、`microbiology_research`、`wiley`。
- 优先解析 RSS/eTOC feed；只有 `collector_kind` 含 `html_detail` 时才进入详情页补 citation meta。Science 和 Cell Press 直接使用 feed 元数据，避免详情页拦截被误报为部分失败。
- ScienceDirect RSS 不提供真实摘要；Metabolic Engineering 固定使用官方 RSS，采集器会用 OpenAlex/PubMed 尝试补 DOI、关键词和可用摘要，不再请求受限的期刊首页或详情页。
- UI 中 `Keywords` 是出版社/外部元数据关键词；评分命中的主题另以 `Themes` 显示。
- 已验证可读 RSS：ScienceDirect Metabolic Engineering、OUP Synthetic Biology、Cell Trends in Microbiology、Wiley Journal of Eukaryotic Microbiology、Wiley Yeast、Scientific American。
- 新增并验证：5 个 Science/AAAS eTOC、14 个 Cell Press feed，以及 Nature、Nature Methods、Nature Chemical Biology、Communications Biology、Nature Reviews Microbiology。
- 原受限的 7 个 Nature 系列来源，以及 Journal of Bacteriology、Microbiology，均已切换为 `crossref_api+pubmed` 并启用。官网网址和平台字段保留，采集使用已核验的 ISSN API 地址。
- 缺失摘要按 DOI 批量检索 PubMed，并核对 DOI 和标题；无收录不标为故障。PubMed 网络失败不丢弃 Crossref 记录，来源显示为“部分失败”。Microbiology 使用电子 ISSN `1465-2080`，不得按名称匹配同名期刊。
- API 请求带限速、最多 3 次尝试和文件缓存（`data/metadata_cache/`）；Crossref 缓存 10 分钟，PubMed 缓存 6 小时。遵守 `Retry-After`，长时间限流推迟到下次更新。
- 98 本期刊目录见 `期刊信息源_98本_20261019.md` / `.json`。目录中验证过的 RSS 仍作为参考保存；新增 89 本的实际采集入口以 `文献源.csv` 中的 Crossref URL 为准。合并后共 101 个 Crossref 来源，其中 98 个补查 PubMed。每日 13:00 和网页“立即更新”都会读取扩展后的同一配置，不新增第二套计划任务。
- Crossref 仅查询 `type:journal-article`，避免 Wiley 等平台最新记录为无标题的整期/整卷时占用采集限额；标题中的 HTML/XML 行内排版标签会转为纯文本。

## 已知注意事项

- 2026-10-15 修复了通用标题误配外部 DOI 引起的 `papers.raw_record_id` 冲突。新入库逻辑保留变化/跟踪历史，不确定的身份冲突保留为独立条目。历史元数据修复入口：`python -m literature_tracker.tasks.repair_metadata --apply`（自动备份、可重复执行）。

- PowerShell 控制台有时会显示中文乱码，但文件本身是 UTF-8。
- `data/reports/` 会不断生成历史报告；如果只需要最新报告，可以保留 `latest_report.md` 和最近一次 timestamp 报告。
- `Publisher Correction` 类型文献可能没有摘要，但 DOI/URL 有效时仍保留。
- 多个海外出版社对非浏览器请求有限制；采集器会给出 blocked non-browser access 错误，属于站点访问限制，不是数据结构损坏。
- `literature_tracker.egg-info`、`__pycache__`、`.pytest_cache` 都是可删除缓存。
- 详情页补全失败不会用空字段覆盖已有摘要、作者、日期或 DOI；该次来源运行标记为 `partial`，数据源页显示为“部分失败”。
- 内容更新按具体字段记录，事件元数据中的 `changed_fields` 和 `field_changes` 可用于复核变化原因。

## 交接前检查清单

- `git status -sb` 查看代码是否还有未提交更改。
- `python -m unittest discover -s tests` 确认测试通过。
- `python -m literature_tracker.cli build-report` 确认报告能生成。
- `streamlit run ui_app.py` 确认 UI 能打开。
- 复制 `data/literature_tracker.db` 和必要报告到新电脑。
