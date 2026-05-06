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
  - `Dashboard`：来源、变化、跟踪状态概览。
  - `Change Analysis`：按批次查看新文献。
- 导出 Tracking CSV、Changes CSV、Papers CSV 和 Markdown 报告。

## 当前跟踪源

配置文件：[文献源.csv](./文献源.csv)

| 来源 | 网站 | 平台 | 抓取入口 | 说明 |
|---|---|---|---|---|
| 合成生物学 | `https://synbioj.cip.com.cn/CN/2096-8280/home.shtml` | `magtech_cip` | RSS `rss_zxly_2096-8280.xml` | RSS 优先，失败时回退最新文章列表；详情页补 DOI、作者、摘要、PDF |
| Advanced Biotechnology | `https://link.springer.com/journal/44307` | `springer` | `/articles` | Springer 列表页 + 详情页 citation meta |
| Journal of Biological Engineering | `https://link.springer.com/journal/13036` | `springer` | `/online-first` | online-first 优先，必要时 fallback 到 `/articles` |

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
python -m literature_tracker.cli crawl
python -m literature_tracker.cli process
python -m literature_tracker.cli detect-changes
python -m literature_tracker.cli build-insights
python -m literature_tracker.cli build-report
```

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

theme_score = min(0.40, 0.15 * 命中主题数)

author_score = 0.40，只要命中重点作者列表

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
  collectors/      # 网站采集器：CIP/Magtech、Springer
  detectors/       # 变化检测
  insights/        # 摘要、理由、评分和 tracking item 构建
  processors/      # raw_records -> papers 规范化
  storage/         # SQLite schema 和 repository
  tasks/           # CLI 任务编排
  ui/              # Streamlit 应用
tests/             # 单元测试
config/            # 作者 watchlist 等配置
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

## 注意事项

- Springer 页面有时会缺少标准摘要，特别是 `Publisher Correction` 或 commentary 类型页面。
- `合成生物学` 的 Magtech/CIP 页面完整摘要位于页面正文的 `摘要/Abstract` 面板中，采集器已做专门解析。
- 新电脑迁移时，代码可以走 git；数据库和报告需要单独复制 `data/`。
