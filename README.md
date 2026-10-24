# Paper Collector

一个面向 LLM 训练与推理的个人论文雷达：每日增量采集 arXiv、以可解释的多信号评分筛选候选、生成中文阅读卡片，并发布为静态仪表盘。

## 产品行为

- 每篇 arXiv 论文只会在首次入选时进入日报；版本号变化不会被当作新论文重复推荐。
- 每日按匹配度、研究质量、新颖性、实用价值和可信度评分；语义相似度作为主要相关性信号，可召回措辞不同的相关论文，并对与近 14 天已推荐论文高度相似者降权。
- 入围 shortlist 的论文全部进入结构化评审；被判定主题相关度过低者在最终选择前剔除，同时保证每日名额不被掏空。
- 网页可切换每日版次，也可选择“全部历史”跨期搜索标题、作者、中英文摘要和主题。历史卡片每次加载 24 篇，筛选始终覆盖完整目录。
- “有用 / 稍后读 / 忽略”会保存在当前浏览器并在刷新后回显；再次点击可取消，也可用“阅读”筛选找回清单。版本号变化仍沿用同一篇论文的标记。
- 页面明确显示版次、采集时间及“规则初筛 / 模型辅助评审”，方便判断数据新鲜度和分数来源。
- arXiv 限流、临时服务错误和读取超时最多尝试 5 次，按 15 / 30 / 60 / 120 秒退避；同时遵守服务器的 `Retry-After`，总请求预算为 5 分钟。超出预算或返回错误数据时停止，不覆盖已有日报。
- 模型连续失败 3 次后，剩余论文使用本地评分和原文摘要，避免服务故障耗尽整个工作流。

## 第一次运行

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/build_site.py
python3 -m http.server 4173 --directory site
```

然后在浏览器打开 `http://127.0.0.1:4173`。静态页面需要 HTTP 服务来读取日报 JSON。

生成数据后，执行：

```bash
python3 scripts/collect.py --config topics.toml
python3 scripts/build_site.py
```

`collect.py` 会读取 `ARXIV_USER_AGENT`；请在 GitHub Actions 的仓库 Secrets 中配置。在没有模型密钥时，系统以可解释的主题、录用状态、代码与引用信号排序，并在页面标注“规则初筛”。日报日期以 `topics.toml` 的 `timezone` 为准（默认 `Asia/Shanghai`），也可用 `--date YYYY-MM-DD` 指定。

如需 embedding 语义召回和 LLM 结构化评审，在 GitHub Secrets 或本地环境中设置 `OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_EMBEDDING_MODEL`，并按需设置 `OPENAI_BASE_URL`（默认 OpenAI `/v1` 地址）。只有初筛 shortlist 会进入结构化评审；服务异常时自动退回本地规则，不会阻断日报保存。

## 每日数据在哪里

- `data/daily/YYYY-MM-DD.json`：每日入选论文和评分原因
- `data/papers/index.json`：跨日报去重后的论文索引
- `site/data/`：GitHub Pages 仪表盘读取的公开静态副本
- `site/data/catalog.json`：按 arXiv 主版本去重后的全历史检索目录

## 使用 GitHub Pages 部署

1. 将仓库保持为公开仓库，并在 GitHub Secrets 配置 `ARXIV_USER_AGENT`。
2. 启用 `.github/workflows/daily.yml`；工作流每日抓取、构建并提交数据快照。
3. 在仓库 **Settings → Pages → Build and deployment** 中，将 Source 设为 **GitHub Actions**。
4. 手动运行一次 **Collect daily papers**，保持 **refresh_papers** 勾选。成功后访问 [论文雷达](https://cheney-chenen.github.io/paper-collector/)；以后每日任务都会同时更新网页。当前计划为每天 UTC 00:30（北京时间 08:30），GitHub 调度可能延迟。

网页和采集可独立发布：推送网页、采集代码、配置或测试到 `main` 时，会测试、重建并发布已有归档，不请求 arXiv。手动运行时取消勾选 **refresh_papers** 也只发布已有数据。这样即使论文源暂时限流，界面修复仍能上线；正常的每日采集失败依然会被明确标记。

GitHub Pages 是公开静态站点。页面上的“有用 / 稍后读 / 忽略”只保存在当前浏览器，不会上传到 GitHub。
