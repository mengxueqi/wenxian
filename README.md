# Literature Tracker

监控指定期刊和网站的文章更新，采集标题、作者、日期、DOI、摘要、关键词和原文链接，按现有关注主题、作者及权重推荐，并提供全文献库检索。

## 功能概览

- **推荐**：默认显示最近 30 天首次入库、命中关注主题或作者的前 10 篇文章；可选择 7 天、90 天或全部，以及 10、20、50 篇。显示推荐理由，评分权重保持原配置。
- **搜索**：检索标题、作者、DOI、摘要、来源、关键词及关注主题；多个词按同时匹配处理。支持来源、主题、入库时间筛选，按发表时间、入库时间、推荐分或标题排序，每页 25 篇。
- **数据源**：每 10 秒刷新来源状态和 Source Summary，正常及抓取中的来源排前，部分失败、失败和访问受限的来源排后；保留可点击的官网网址。
- **立即更新**：在后台执行采集、去重入库、更新检测和推荐评分，抓取期间可继续浏览；同一服务内重复点击不启动重复任务。原有每日计划任务保留。
- **导出**：仅在搜索页提供当前全部搜索结果 CSV，包含作者、摘要、DOI、关键词和原文链接。

界面只读取当前文章和推荐结果，不加载全部变化历史，不自动构建报告或多份导出。数据缓存最多保留 60 秒，检测到数据库或 WAL 文件变化会重新读取；“刷新页面数据”可主动刷新。仅渲染选中的标签页，需要 Streamlit >=1.56。

## 当前跟踪源

配置文件：[文献源.csv](./文献源.csv)

当前配置 131 个来源，均已启用。其中 101 个通过 Crossref 按 ISSN 采集，98 个同时使用 PubMed 补充缺失摘要。官网地址用于阅读，API 地址用于采集。

已纳入 [71 + 27 本期刊信息源清单](./期刊信息源_98本_20261019.md)：其中 9 本复用原配置，新增 89 本使用 `crossref_api+pubmed`，没有重复添加。原 42 个来源的配置保持不变。新增来源与“立即更新”和每日 13:00 计划任务使用同一信源表，不需要单独启动；接口没有摘要时保留标题、作者和 DOI，不下载全文。

- **Nature 系列**：Nature、Nature Methods、Nature Chemical Biology、Communications Biology、Nature Reviews Microbiology 使用原有 feed；Nature Biotechnology、Nature Communications、Nature Microbiology、Nature Genetics、Nature Cell Biology、Nature Metabolism、Nature Biomedical Engineering 改用 Crossref + PubMed，避免依赖受限网页。
- **Science 系列**：Science、Science Advances、Science Translational Medicine、Science Signaling、Science Immunology，使用 AAAS 官方 eTOC feed，直接采用 feed 中的 DOI、作者和摘要元数据。
- **Cell Press 系列**：Cell、Molecular Cell、Cell Systems、Cell Metabolism、Cell Chemical Biology、Cell Host & Microbe、Developmental Cell、Current Biology、Immunity、Trends in Biotechnology、Trends in Cell Biology、Trends in Genetics、Trends in Biochemical Sciences，以及原有 Trends in Microbiology；使用 in-press/current feed 元数据。
- **其他来源**：合成生物学、Advanced Biotechnology、Journal of Biological Engineering、Metabolic Engineering、Synthetic Biology、Scientific American、Annals of Microbiology、Journal of Eukaryotic Microbiology、Yeast；Journal of Bacteriology 和 Microbiology 改用 Crossref + PubMed。Microbiology 按电子 ISSN `1465-2080` 标识，避免匹配到同名期刊。

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
```

`data/` 被 `.gitignore` 忽略，不会随 git 自动同步。

## 常用命令

完整流水线：

```powershell
python -m literature_tracker.cli run-all
```

该命令依次执行抓取、规范化、变化检测和推荐评分。任一来源抓取失败或详情补全不完整时返回非零退出码，供计划任务识别异常。Markdown 报告改为可选：`python -m literature_tracker.cli run-all --report`，也可单独运行 `build-report`。各阶段独立命令保留供维护使用。

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

计划任务由无窗口的 `wscript.exe` 启动，在后台执行采集、入库、变化检测和推荐评分。错过 13:00 时在电脑恢复可用后补执行，已有任务运行时不重复启动。日志位于 `data/scheduled_update.log`，脚本优先使用 `.venv\Scripts\python.exe`。修改安装脚本后需重新运行安装命令，已有任务才会更新。

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
  catalog.py       # 轻量文章目录、推荐筛选、检索和搜索导出
  presentation.py  # 运行状态、CSV 和可选维护报告
  ui/              # 推荐、搜索、数据源
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

保留原始记录、变化历史和评分记录，用于去重、元数据更新与问题排查；不在网页中展示内部追踪状态。未评分文章仍可在搜索中找到。推荐页仅筛选有主题或作者命中的文章，不改动原评分公式。

## 规则配置

- `config/theme_watchlist.csv`：`theme_name`、以 `|` 分隔的关键词、`score_weight`、`enabled`。
- `config/author_watchlist.csv`：作者名、别名、关注领域、`score_weight`、`enabled`。
- 修改配置后再次运行 `build-insights` 或 `run-all` 即可重新计算；不需要修改 Python 代码。

`collector_kind=crossref_api+pubmed` 的来源使用 Crossref 获取最近 100 条文章记录，按 `type:journal-article` 排除整期、整卷条目，并清理标题中的出版社排版标签。仅对缺少摘要的记录按 DOI 批量查询 PubMed，并同时核对标题。未收录或未提供摘要属于正常缺失；PubMed 网络失败保留 Crossref 记录，并将来源标为“部分失败”。[Crossref 类型筛选说明](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/)

元数据 API 请求间隔至少 0.4 秒，遇到网络错误、429、502、503、504 最多尝试 3 次，并遵守 `Retry-After`；服务器要求等待超过 30 秒时推迟到下一次更新，不提前重试。`data/metadata_cache/` 缓存 Crossref 响应 10 分钟、PubMed 响应 6 小时，避免重复请求。

内容更新采用字段级检测，覆盖标题、作者、摘要、发布日期、DOI、语言、关键词、PDF 地址及撤稿/更正状态。详情页补全失败会保留已有完整字段，在“数据源”页显示为“部分失败”。

DOI 补全后发现同一文献的两个条目时，会合并并保留来源、变化历史和跟踪信息；标题不能确认为同一文献时保留独立记录，将冲突写入 `identity_conflict` 元数据。`Editorial Board` 等通用标题不会仅凭标题获取外部 DOI。

对已确认的 Editorial Board/OpenAlex 历史错配，可先运行只读检查：

```powershell
python -m literature_tracker.tasks.repair_metadata
```

加 `--apply` 会先在 `data/backups/` 生成 SQLite 一致性备份，再清除这类已确认的错误关联；该修复可重复执行。

## 注意事项

- 101 个来源通过 Crossref ISSN API 抓取，避免依赖出版社网页；其中 98 个使用 PubMed 补充可核验的摘要。接口未提供摘要时仍保留 DOI、标题、作者和发表日期。
- `合成生物学` 的 Magtech/CIP 页面完整摘要位于页面正文的 `摘要/Abstract` 面板中，采集器已做专门解析。
- 新电脑迁移时，代码可以走 git；数据库和报告需要单独复制 `data/`。
