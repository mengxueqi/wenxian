# Literature Tracker

用于跟踪指定期刊/网站的新文献、内容变化、勘误/撤稿信号，并在 Streamlit UI 中维护一个按评分排序的文献关注队列。

## 功能概览

- 抓取配置源中的最新文献记录。
- 将原始记录规范化为文献库 `papers`。
- 检测新文献、内容更新、勘误、撤稿等变化。
- 根据变化类型、主题命中、重点作者命中、近期入库活跃度计算 `priority_score`。
- 提供 Streamlit UI：
  - `Focus`：最近 30 天入库、评分最高的 10 篇文献。
  - `Library`：完整文献队列，支持来源、状态、变化类型、关键词、最低分筛选。
  - `Dashboard`：来源、变化、跟踪状态及抓取/流水线健康状态概览。
  - `Change Analysis`：按批次查看新文献。
- 导出 Tracking CSV、Changes CSV、Papers CSV 和 Markdown 报告。

## 当前跟踪源

配置文件：[文献源.csv](./文献源.csv)

当前共配置 42 个来源，其中 33 个 `active`、9 个 `blocked`。完整 URL、平台、状态和限制以 CSV 为准。

- **Nature 系列**：Nature、Nature Methods、Nature Chemical Biology、Communications Biology、Nature Reviews Microbiology 可直接抓取；Nature Biotechnology、Nature Communications、Nature Microbiology、Nature Genetics、Nature Cell Biology、Nature Metabolism、Nature Biomedical Engineering 当前因官方 feed 返回 Client Challenge 标记为 `blocked`。
- **Science 系列**：Science、Science Advances、Science Translational Medicine、Science Signaling、Science Immunology，使用 AAAS 官方 eTOC feed，直接采用 feed 中的 DOI、作者和摘要元数据。
- **Cell Press 系列**：Cell、Molecular Cell、Cell Systems、Cell Metabolism、Cell Chemical Biology、Cell Host & Microbe、Developmental Cell、Current Biology、Immunity、Trends in Biotechnology、Trends in Cell Biology、Trends in Genetics、Trends in Biochemical Sciences，以及原有 Trends in Microbiology；使用 in-press/current feed 元数据。
- **其他来源**：合成生物学、Advanced Biotechnology、Journal of Biological Engineering、Metabolic Engineering、Synthetic Biology、Scientific American、Annals of Microbiology、Journal of Eukaryotic Microbiology、Yeast；Journal of Bacteriology 和 Microbiology 当前为 `blocked`。

## 新电脑部署

推荐使用 Conda / Miniconda。

```powershell
git clone <repo-url> wenxian
cd wenxian
conda env create -f environment.yml
conda activate literature-tracker
```

如果已经有环境，也可以手动安装：

```powershell
python -m pip install -e ".[ui]"
```

初始化数据库：

```powershell
python -m literature_tracker.cli init-db
```

如果要迁移旧电脑已有数据，请把旧电脑的 `data/` 目录复制到新电脑项目根目录。最关键文件是：

```text
data/literature_tracker.db
data/reports/latest_report.md
```

`data/` 被 `.gitignore` 忽略，不会随 git 自动同步。

## 常用命令

完整流水线：

```powershell
python -m literature_tracker.cli run-all
```

该命令依次执行抓取、规范化、变化检测、评分和报告。任一来源抓取失败或详情补全不完整时会返回非零退出码，适合计划任务识别异常。各阶段仍可使用原有独立命令调试。

只抓取某个来源：

```powershell
python -m literature_tracker.cli crawl --source "合成生物学"
python -m literature_tracker.cli process --source "合成生物学"
python -m literature_tracker.cli detect-changes --source "合成生物学"
python -m literature_tracker.cli build-insights --source "合成生物学"
python -m literature_tracker.cli build-report --source "合成生物学"
```

启动 UI：

```powershell
streamlit run ui_app.py
```

安装每日自动更新任务（默认每天 13:00）：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_literature_tracker_task.ps1
```

也可指定其他时间：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_literature_tracker_task.ps1 -DailyAt "06:30"
```

计划任务由无窗口的 `wscript.exe` 启动，在后台静默执行文献抓取、入库、变化检测、评分和报告生成。错过 13:00 时会在电脑恢复可用后补执行，已有任务运行时不会重复启动。日志位于 `data/scheduled_update.log`，脚本优先使用 `.venv\Scripts\python.exe`。修改安装脚本后需重新运行一次安装命令，系统中已有任务才会更新。

运行测试：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests
```

## 评分体系

评分在 [literature_tracker/insights/build.py](./literature_tracker/insights/build.py) 中实现。

```text
priority_score =
  change_base_score
  + theme_score
  + author_score
  + recent_activity_score

final_score = round(min(priority_score, 0.99), 2)
```

当前权重：

```text
change_base_score 最高 0.20
- new_paper: 0.05
- content_updated: 0.10
- correction_notice: 0.16
- retraction_notice: 0.20
- 其他: 0.12

theme_score = min(0.40, 各命中主题的 score_weight 之和)

author_score = min(0.40, 各命中作者的 score_weight 之和)

recent_activity_score = 0.20，最近 30 天内入库/更新
```

分档：

```text
score >= 0.85 -> high -> review
score >= 0.65 -> medium -> pending
score < 0.65 -> low -> watchlist
```

## 项目结构

```text
literature_tracker/
  collectors/      # 网站采集器：CIP/Magtech、Springer、通用 RSS/HTML 期刊页
  detectors/       # 变化检测
  insights/        # 摘要、理由、评分和 tracking item 构建
  processors/      # raw_records -> papers 规范化
  storage/         # SQLite schema 和 repository
  tasks/           # CLI 任务编排
  ui/              # Streamlit 应用
tests/             # 单元测试
config/            # 作者、主题和评分权重配置
data/              # SQLite 数据库和报告，git 忽略
```

## 数据说明

SQLite 数据库默认位于：

```text
data/literature_tracker.db
```

核心表：

- `sources`：跟踪源配置快照。
- `raw_records`：采集到的原始文献记录。
- `papers`：规范化后的文献。
- `paper_changes`：新文献、内容更新、勘误、撤稿等变化记录。
- `paper_insights`：每条变化对应的评分、摘要、理由和元数据。
- `tracking_items`：每篇文献当前应关注的最高优先级记录。

## 规则配置

- `config/theme_watchlist.csv`：`theme_name`、以 `|` 分隔的关键词、`score_weight`、`enabled`。
- `config/author_watchlist.csv`：作者名、别名、关注领域、`score_weight`、`enabled`。
- 修改配置后再次运行 `build-insights` 或 `run-all` 即可重新计算；不需要修改 Python 代码。

内容更新采用字段级检测，当前覆盖标题、作者、摘要、发布日期、DOI、语言、关键词、PDF 地址以及撤稿/更正状态。详情页补全失败会保留已有完整字段，并在 Dashboard 中标记为 `partial`。

## 注意事项

- 3 个 Springer 来源通过 Crossref ISSN API 抓取，避免网页反爬；Crossref 未提供摘要时仍保留 DOI、标题、作者和发表日期。
- `合成生物学` 的 Magtech/CIP 页面完整摘要位于页面正文的 `摘要/Abstract` 面板中，采集器已做专门解析。
- 新电脑迁移时，代码可以走 git；数据库和报告需要单独复制 `data/`。
