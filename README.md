# Literature Tracker

文献追踪项目第一阶段骨架，目标是先把以下链路打通：

- 从 [文献源.csv](/D:/codex/wenxian/文献源.csv) 读取来源配置
- 为不同平台选择对应的 collector
- 抓取原始文献条目
- 将抓取结果写入 SQLite
- 预留 `papers / paper_changes / paper_insights / tracking_items` 四层数据表

当前已纳入的来源：

- `合成生物学`
- `Advanced Biotechnology`
- `Journal of Biological Engineering`

## 当前状态

第一阶段已实现：

- 项目骨架和模块目录
- `SourceConfig` 配置加载
- SQLite Repository 和基础 schema
- `magtech_cip` 与 `springer` collector 框架
- `crawl` CLI

第二阶段已实现：

- `raw_records -> papers` 归一化流程
- `process` CLI
- `papers` 表的基础主字段和迁移回填

第三阶段已实现：

- `papers -> paper_changes` 变化检测流程
- `detect-changes` CLI
- `new_paper / content_updated / correction_notice / retraction_notice` 基础规则

第四阶段已实现：

- `paper_changes -> paper_insights / tracking_items`
- `build-insights` CLI
- 基于变化类型、主题信号和近期活跃度的摘要、理由、评分和追踪优先级

第五阶段已实现：

- `build-report` Markdown 报告生成
- `ui_app.py` 本地 Streamlit 界面
- Dashboard / Change Analysis / Tracking Queue / Papers / Report Preview 五个视图

已知限制：

- Springer 站点对非浏览器客户端可能返回 bot challenge，当前代码会显式报错并记录失败
- 当前 UI 还是第一版浏览界面，后续可以继续做更强的筛选、排序和导出

## 环境

- Python `>=3.12`
- 依赖见 [pyproject.toml](/D:/codex/wenxian/pyproject.toml)

当前项目已经建立独立虚拟环境：

- `.venv`

如果需要在新机器或重建环境时重新创建，可执行：

```powershell
C:\ugene-53.0\tools\python3\python.exe -m venv D:\codex\wenxian\.venv
D:\codex\wenxian\.venv\Scripts\python.exe -m pip install -e D:\codex\wenxian
D:\codex\wenxian\.venv\Scripts\python.exe -m pip install "streamlit>=1.44,<2"
```

激活方式：

```powershell
D:\codex\wenxian\.venv\Scripts\Activate.ps1
```

## 快速开始

初始化数据库：

```powershell
D:\codex\wenxian\.venv\Scripts\python.exe -m literature_tracker.cli init-db
```

抓取全部启用来源：

```powershell
D:\codex\wenxian\.venv\Scripts\python.exe -m literature_tracker.cli crawl
```

把 `raw_records` 归一化到 `papers`：

```powershell
D:\codex\wenxian\.venv\Scripts\python.exe -m literature_tracker.cli process
```

从 `papers` 生成 `paper_changes`：

```powershell
D:\codex\wenxian\.venv\Scripts\python.exe -m literature_tracker.cli detect-changes
```

从 `paper_changes` 生成 `paper_insights` 和 `tracking_items`：

```powershell
D:\codex\wenxian\.venv\Scripts\python.exe -m literature_tracker.cli build-insights
```

生成 Markdown 报告：

```powershell
D:\codex\wenxian\.venv\Scripts\python.exe -m literature_tracker.cli build-report
```

启动本地 UI：

```powershell
D:\codex\wenxian\.venv\Scripts\streamlit.exe run D:\codex\wenxian\ui_app.py
```

只抓一个来源，限制 5 条：

```powershell
D:\codex\wenxian\.venv\Scripts\python.exe -m literature_tracker.cli crawl --source "合成生物学" --limit 5
```

## 目录

- [literature_tracker](/D:/codex/wenxian/literature_tracker): 主包
- [literature_tracker/collectors](/D:/codex/wenxian/literature_tracker/collectors): 来源采集器
- [literature_tracker/storage](/D:/codex/wenxian/literature_tracker/storage): SQLite 仓储
- [literature_tracker/tasks](/D:/codex/wenxian/literature_tracker/tasks): 分阶段任务入口
- [ui_app.py](/D:/codex/wenxian/ui_app.py): Streamlit 入口
- [tests](/D:/codex/wenxian/tests): 离线单元测试

## 下一阶段

- `ui`: 增加更细的筛选、排序、搜索和导出
- `report`: 增加日报/周报模板与自动化调度
- `insights`: 引入更细的主题标签和更强的评分规则
