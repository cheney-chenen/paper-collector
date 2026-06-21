# Paper Collector

一个面向 LLM 训练与推理的个人论文雷达：每日增量采集 arXiv、以可解释的多信号评分筛选候选、生成中文阅读卡片，并发布为静态仪表盘。

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
- `site/data/`：GitHub Pages 仪表盘读取的公开静态副本

## 使用 GitHub Pages 部署

1. 将仓库保持为公开仓库，并在 GitHub Secrets 配置 `ARXIV_USER_AGENT`。
2. 启用 `.github/workflows/daily.yml`；工作流每日抓取、构建并提交数据快照。
3. 在仓库 **Settings → Pages → Build and deployment** 中，将 Source 设为 **GitHub Actions**。
4. 手动运行一次 **Collect daily papers**。成功后访问 `https://cheney-cen.github.io/paper-collector/`；以后每次日报任务都会同时更新该网页。

GitHub Pages 是公开静态站点。页面上的“有用 / 稍后读 / 忽略”只保存在当前浏览器，不会上传到 GitHub。
