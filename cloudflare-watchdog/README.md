# Cloudflare Watchdog

这个 Worker 是 `Daily AI News` 的独立定时看门狗，用来规避 GitHub Actions `schedule` 偶发数小时延迟或完全不生成 run 的问题。

## 工作方式

Cloudflare 每天北京时间：

- 09:01
- 09:06
- 09:11
- 09:16

调用 GitHub 的 `workflow_dispatch`。GitHub 原来的 09:00 / 09:05 / 09:10 / 09:15 `schedule` 继续保留为第二层兜底。

外部触发统一传入 `retry_mode=true`。主程序会检查 `data/state/last_delivery.json`：

- 当天尚未成功发送：正常抓取并推飞书；
- 当天已经成功发送：直接退出，不重复推送。

## GitHub Secrets

部署前在仓库 `Settings -> Secrets and variables -> Actions` 新增：

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `GITHUB_DISPATCH_TOKEN`

`GITHUB_DISPATCH_TOKEN` 只用于 Cloudflare Worker 调用本仓库的 Actions workflow dispatch。建议使用 GitHub fine-grained PAT，只授权这个仓库，并给 Actions 写权限，不要给多余仓库权限。

Cloudflare API Token 建议只给 Workers Scripts 编辑权限。

三个 Secret 配好后，到：

`Actions -> Deploy Cloudflare Watchdog -> Run workflow`

手动执行一次。以后修改 `cloudflare-watchdog/**` 会自动重新部署。

## 健康检查

部署后 Worker 的 `/health` 会返回 JSON，只用于确认 Worker 在线，不会触发日报。
