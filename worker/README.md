# Feedback Worker

Cloudflare Pages 负责只读仪表盘；这个 Worker 负责把经过 Access 认证的反馈写入私有 GitHub 仓库的 `data/feedback/`。

## 必需配置

- `GITHUB_REPOSITORY`：例如 `owner/paper-collector`
- `GITHUB_TOKEN`：Fine-grained PAT，只授予该私有仓库 **Contents: Read and write** 权限
- `CF_ACCESS_AUD`：Cloudflare Access application audience
- `CF_ACCESS_TEAM_DOMAIN`：例如 `your-team.cloudflareaccess.com`

在 Worker 上设置 `FEEDBACK_ALLOWED_ORIGIN` 为 Pages 的准确 HTTPS origin。Worker 会验证 Access JWT 的签名、Audience 和 issuer；浏览器不接触 GitHub 令牌。

部署后，在 Cloudflare Pages 的环境变量中设置 `PAPER_COLLECTOR_FEEDBACK_ENDPOINT`（或在构建时写入 `site/app.js`），并把 Worker 路径置于同一个 Access application 下。
