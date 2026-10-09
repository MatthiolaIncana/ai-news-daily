# AI News Daily

一个面向个人 AI 工具链的全自动新闻日报：每天北京时间 09:00 自动运行，对过去约 30 小时新闻做来源、变化信号、工作流影响、去重和规则评分，只推送真正可能影响现有工作流的更新。

## 当前默认关注

- Seedance / AI 视频生成
- Whisper / faster-whisper / Silero VAD / 说话人分离
- 剪映 / CapCut / 自动剪辑 / MCP
- AI 短剧 / 红果短剧
- AI 图像生成
- GPT / Claude / Gemini / Codex / Agent
- GitHub 优秀开源工具

第一版只使用 Python 3.12 标准库，不调用任何付费大模型 API，也不依赖 pip 安装第三方包。

## GitHub 上线步骤

1. 新建一个 **Public** 仓库，建议名称：`ai-news-daily`。
2. 把本项目全部文件上传到仓库根目录。
3. 在飞书群里创建「自定义机器人」，复制 Webhook 地址。
4. 打开 GitHub 仓库：`Settings -> Secrets and variables -> Actions -> New repository secret`。
5. Secret 名称填：`FEISHU_WEBHOOK`；值填飞书机器人 Webhook。
6. 打开 `Actions -> Daily AI News -> Run workflow`，先手动运行一次。
7. 飞书收到测试日报后，无需再操作；系统每天北京时间 09:00 自动推送。

当前采用纯 GitHub Actions 方案：北京时间 09:17 / 09:27 / 09:37 / 09:47 四次独立错峰触发。第一次成功推送后会写入当天成功状态，后续重试自动跳过。这样避免依赖外部平台，同时避开 GitHub Actions 整点高峰。

## 如何新增监控内容

优先只改两个配置文件，不修改主程序：

- `config/topics.toml`：关注主题、关键词、权重、影响说明。
- `config/sources.toml`：RSS、GitHub Release Feed、Google News 查询。

例如增加 Tibo，在 `topics.toml` 加：

```toml
[topics.tibo]
label = "Tibo"
weight = 5
keywords = ["tibo", "tibo ai"]
impact = "重点判断是否出现重置信号、模型能力或使用规则变化。"
```

在 `sources.toml` 加：

```toml
[[sources]]
name = "GoogleNews-Tibo"
type = "google_news"
trust = 3
query = "Tibo AI"
```

## 当前推送策略

- 目标为每天北京时间 09:17 左右送达；GitHub Actions 在 09:17/09:27/09:37/09:47 独立重试，首次成功后后续自动跳过。
- 检查过去 30 小时，降低调度延迟造成的漏报概率。
- 最低分数 13；按分类分别设定每日配额，不再用所有分类共享的总上限。
- 相似标题自动去重。
- 营销、融资等低价值内容默认过滤。
- 单个来源失败不影响其他来源；日报底部显示抓取异常。
- 没有达到阈值的新闻也发“今日无重要更新”，用于确认任务仍在运行。
- `keepalive.yml` 每月只产生一次保活提交，降低公共仓库长期无人工活动后定时工作流被停用的风险。

## 测试

```bash
python -m unittest discover -s tests -v
python src/main.py --dry-run
```

## 文件结构

```text
.github/workflows/daily-news.yml                 # 日报执行 + GitHub cron 兜底
.github/workflows/keepalive.yml                   # 每月低频保活
config/topics.toml                # 主题和评分
config/sources.toml               # 新闻来源
src/main.py                       # 采集、过滤、去重、评分、飞书推送
tests/test_core.py                # 核心逻辑测试
```


### 分类配额

- Seedance / AI视频：最多 5 条
- 字幕 / Whisper / VAD：最多 5 条
- 剪映 / CapCut / 自动化：最多 4 条
- AI短剧 / 红果：最多 4 条
- AI图像：最多 3 条
- GPT / Claude / Gemini / Agent：最多 3 条
- GitHub 开源工具：最多 2 条

某一类当天不足配额时不会用低价值新闻补满，只推送实际达到阈值的内容。


## 检索与质量门

- 候选池采用宽搜索：尽量把与各主题相关的新内容先抓进来，不在搜索阶段强制要求标题出现 release/update/API 等词。
- 最终推送采用严格质量门：只有真正发生变化、且可能影响现有工作流的内容才进入日报。
- 这样优先降低漏报风险，同时不通过降低质量门来增加条数。

## 质量门

日报不是“关键词新闻集合”。一条内容要进入推送，通常需要同时满足：

- 命中当前工作流主题；
- 出现明确变化信号，例如发布、更新、新版本、API、价格、弃用、准确率、质量修复等；
- 命中至少一个实际工作流影响点，例如角色一致性、字幕时间轴、说话人分离、批量剪辑、平台规则、工具调用、价格或限额；
- 达到最低质量分 13。

以下内容默认剔除或明显降权：

- 融资、股价、财报、招聘、明星、赞助稿；
- “Top 10 / 必看 / 盘点 / 教程 / 是什么 / 怎么用 / 观点 / 访谈 / 预测 / 传闻”等泛内容；
- 只有关键词、没有具体变化的文章；
- 一般评测、上手、对比类文章（除非同时包含非常明确的新变化）。

官方 GitHub Release 等高可信更新优先级最高；同一事件的重复标题会去重，只保留更高分版本。


## 定时可靠性：纯 GitHub 重试

当前不依赖任何外部定时服务。

`Daily AI News` 使用四个错峰的 GitHub Actions schedule：

- 09:17
- 09:27
- 09:37
- 09:47

全部使用 `Asia/Shanghai` 时区。当天任何一次成功发送后，`data/state/last_delivery.json` 会记录当天成功状态，后续重试会自动退出，不重复发送。