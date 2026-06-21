# Paper Collector

一个面向 LLM 训练与推理的个人论文雷达：每日增量采集 arXiv、以可解释的多信号评分筛选候选、生成中文阅读卡片，并发布为受保护的静态仪表盘。

## 第一次运行

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/build_site.py --date 2026-06-22
python3 -m http.server 4173 --directory site
```

然后在浏览器打开 `http://127.0.0.1:4173`。静态页面需要 HTTP 服务来读取日报 JSON。

生成数据后，执行：

```bash
python3 scripts/collect.py --config topics.toml
python3 scripts/build_site.py
```

`collect.py` 会读取 `ARXIV_USER_AGENT`；在 GitHub Actions 中这个值已默认配置。第一版在没有模型密钥时仍会以可解释的主题、录用状态、代码与引用信号稳定排序。

如需自动生成中文阅读摘要，在 GitHub Secrets 或本地环境中设置 `OPENAI_API_KEY`、`OPENAI_MODEL`，并按需设置 `OPENAI_BASE_URL`（默认 OpenAI `/v1` 地址）。仅最终入选的 12 篇论文摘要会发送给该服务；服务异常不会阻断日报保存。

## 每日数据在哪里

- `data/daily/YYYY-MM-DD.json`：每日入选论文和评分原因
- `data/papers/index.json`：跨日报去重后的论文索引
- `data/feedback/*.json`：网页写回的“有用 / 忽略 / 稍后读”反馈事件
- `site/data/`：仪表盘读取的公开静态副本（部署时由 Cloudflare Access 保护）

## 部署

1. 将仓库保持为私有仓库，并在 GitHub Secrets 配置 `ARXIV_USER_AGENT`。
2. 启用 `.github/workflows/daily.yml`；工作流每日抓取、构建并提交数据快照。
3. 将 `site/` 连接到 Cloudflare Pages，并用 Cloudflare Access 限制访问者。
4. 在 `worker/` 配置仅可写入本仓库的 GitHub Fine-grained PAT 和 Cloudflare Access Audience；Worker 把反馈写进私有仓库，不让浏览器持有 GitHub 密钥。
5. 将部署后的 Worker URL 填入 `site/config.js` 的 `PAPER_COLLECTOR_FEEDBACK_ENDPOINT`；该 URL 可公开，真正的访问控制由 Cloudflare Access JWT 完成。

部署前请阅读 `worker/README.md`，它列出了 Access JWT 校验所需的环境变量。
