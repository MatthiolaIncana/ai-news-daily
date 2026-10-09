# cron-job.org Watchdog

用于给 `Daily AI News` 提供独立于 GitHub Actions schedule 的外部定时兜底。

## 原理

cron-job.org 在北京时间以下时间调用 GitHub REST API：

- 09:01
- 09:06
- 09:11
- 09:16

调用目标：

`POST https://api.github.com/repos/MatthiolaIncana/ai-news-daily/actions/workflows/daily-news.yml/dispatches`

请求头：

- `Authorization: Bearer <你的 GITHUB_DISPATCH_TOKEN>`
- `Accept: application/vnd.github+json`
- `X-GitHub-Api-Version: 2022-11-28`
- `Content-Type: application/json`

请求 Body：

```json
{
  "ref": "main",
  "inputs": {
    "retry_mode": "true",
    "trigger_source": "cron-job.org",
    "scheduled_time": "external"
  }
}
```

外部触发时 `retry_mode=true`，所以主程序会先检查 `data/state/last_delivery.json`。当天已经成功发过飞书时，后续触发会直接退出，不重复推送。

## GitHub Token 权限

建议使用 Fine-grained personal access token：

- Resource owner: `MatthiolaIncana`
- Repository access: Only select repositories → `ai-news-daily`
- Repository permissions → Actions: Read and write

该 Token 不要提交到仓库，也不要放到公开文本中，只保存在 cron-job.org 请求头中。
