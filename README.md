# AI News Daily

一个面向个人 AI 工具链的全自动新闻日报：每天北京时间 09:00 自动运行，对过去约 30 小时新闻做去重、主题识别和规则评分，只把最相关的 0~10 条推送到飞书。

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

GitHub Actions 的 schedule 由平台调度，09:00 是目标时间；平台繁忙时可能延迟几分钟。

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

- 每天北京时间 09:00 运行一次。
- 检查过去 30 小时，降低调度延迟造成的漏报概率。
- 最低分数 8，每日最多 10 条。
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
.github/workflows/daily-news.yml  # 每日 09:00 推送
.github/workflows/keepalive.yml   # 每月低频保活
config/topics.toml                # 主题和评分
config/sources.toml               # 新闻来源
src/main.py                       # 采集、过滤、去重、评分、飞书推送
tests/test_core.py                # 核心逻辑测试
```
