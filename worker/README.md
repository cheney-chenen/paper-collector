# Feedback Worker

> 当前 GitHub Pages 部署不使用此 Worker；反馈只保存在浏览器。此目录仅保留为未来将仓库重新设为私有并启用 Cloudflare Access 时的扩展代码。

这个 Worker 可把经过 Cloudflare Access 认证的反馈写入私有 GitHub 仓库的 `data/feedback/`。不要在当前公开仓库中启用，否则阅读反馈也会公开。

## 未来启用时所需配置

- `GITHUB_REPOSITORY`：私有仓库的 `owner/name`
- `GITHUB_TOKEN`：仅授予该私有仓库 **Contents: Read and write** 的 Fine-grained PAT
- `CF_ACCESS_AUD`：Cloudflare Access application audience
- `CF_ACCESS_TEAM_DOMAIN`：例如 `your-team.cloudflareaccess.com`
- `FEEDBACK_ALLOWED_ORIGIN`：受保护仪表盘的准确 HTTPS origin

Worker 会验证 Access JWT 的签名、Audience 和 issuer；浏览器不接触 GitHub 令牌。
