# Literature Tracker Handoff

本文档用于把项目交接到新电脑或新维护者手中。

## 当前项目状态

- 项目根目录：`D:\codex\wenxian`
- Python 包名：`literature_tracker`
- UI 入口：`ui_app.py`
- CLI 入口：`python -m literature_tracker.cli`
- Conda 环境文件：`environment.yml`
- 当前数据库：`data/literature_tracker.db`
- 最新报告：`data/reports/latest_report.md`

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

- `Focus`：最近 30 天内入库、评分最高的 10 篇文献。展示卡片格式与 `Library` 一致。
- `Library`：完整 tracking queue，支持搜索、来源、状态、变化类型、关键词、最低优先级筛选。
- `Dashboard`：来源统计、变化类型、tracking status、各来源抓取状态和下游流水线状态；超过两天未成功运行显示为 `stale`。
- `Change Analysis`：按新文献批次查看变化。

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
- Advanced Biotechnology、Journal of Biological Engineering 和 Annals of Microbiology 通过 Crossref ISSN API 抓取，避免 Springer 列表页的 Client Challenge。
- 保留 DOI、标题、作者、发表日期、Crossref 主题和可用摘要；个别记录可能没有摘要。

### 通用期刊来源

文件：`literature_tracker/collectors/generic.py`

- 平台：`sciencedirect`、`oup`、`scientific_american`、`asm`、`science`、`cell`、`nature`、`microbiology_research`、`wiley`。
- 优先解析 RSS/eTOC feed；只有 `collector_kind` 含 `html_detail` 时才进入详情页补 citation meta。Science 和 Cell Press 直接使用 feed 元数据，避免详情页拦截被误报为部分失败。
- ScienceDirect RSS 不提供真实摘要；Metabolic Engineering 固定使用官方 RSS，采集器会用 OpenAlex/PubMed 尝试补 DOI、关键词和可用摘要，不再请求受限的期刊首页或详情页。
- UI 中 `Keywords` 是出版社/外部元数据关键词；评分命中的主题另以 `Themes` 显示。
- 已验证可读 RSS：ScienceDirect Metabolic Engineering、OUP Synthetic Biology、Cell Trends in Microbiology、Wiley Journal of Eukaryotic Microbiology、Wiley Yeast、Scientific American。
- 新增并验证：5 个 Science/AAAS eTOC、14 个 Cell Press feed，以及 Nature、Nature Methods、Nature Chemical Biology、Communications Biology、Nature Reviews Microbiology。
- 7 个 Nature 系列官方 feed 当前返回 Client Challenge，已保留在 `文献源.csv` 并标记为 `blocked`，不会进入默认抓取。
- ASM 和 MicrobiologyResearch 在 requests 环境下返回 Cloudflare `Just a moment`；`文献源.csv` 中暂时标为 `blocked`，需要后续 browser-backed fetcher 才能稳定抓取。

## 已知注意事项

- PowerShell 控制台有时会显示中文乱码，但文件本身是 UTF-8。
- `data/reports/` 会不断生成历史报告；如果只需要最新报告，可以保留 `latest_report.md` 和最近一次 timestamp 报告。
- `Publisher Correction` 类型文献可能没有摘要，但 DOI/URL 有效时仍保留。
- 多个海外出版社对非浏览器请求有限制；采集器会给出 blocked non-browser access 错误，属于站点访问限制，不是数据结构损坏。
- `literature_tracker.egg-info`、`__pycache__`、`.pytest_cache` 都是可删除缓存。
- 详情页补全失败不会再用空字段覆盖已有摘要、作者、日期或 DOI；该次来源运行会标记为 `partial`，错误可在 Dashboard 查看。
- 内容更新按具体字段记录，事件元数据中的 `changed_fields` 和 `field_changes` 可用于复核变化原因。

## 交接前检查清单

- `git status -sb` 查看代码是否还有未提交更改。
- `python -m unittest discover -s tests` 确认测试通过。
- `python -m literature_tracker.cli build-report` 确认报告能生成。
- `streamlit run ui_app.py` 确认 UI 能打开。
- 复制 `data/literature_tracker.db` 和必要报告到新电脑。
