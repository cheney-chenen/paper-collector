const PAGE_SIZE = 24;
const state = { papers: [], topic: "all", sort: "score", date: null, query: "", feedback: "all", visibleCount: PAGE_SIZE, storageAvailable: true, editions: [], loading: false, error: false };
const feedbackCache = new Map();
const topicLabels = { pretraining: "预训练", "post-training": "后训练", reasoning: "推理扩展", serving: "推理系统", efficiency: "高效推理" };
const breakdownOrder = ["relevance", "quality", "novelty", "practical", "credibility", "personal"];
const breakdownLabels = { relevance: "匹配", quality: "质量", novelty: "新颖", practical: "实用", credibility: "可信", personal: "偏好" };

const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;" }[character]));
const clamp = (value) => Math.max(0, Math.min(100, value));
const $ = (selector) => document.querySelector(selector);

const canonicalId = (paperId) => String(paperId).replace(/v\d+$/, "");

function savedFeedback(paperId) {
  const key = canonicalId(paperId);
  if (!feedbackCache.has(key)) {
    let value = null;
    try { value = localStorage.getItem(`paper-feedback:${key}`) || localStorage.getItem(`paper-feedback:${paperId}`); }
    catch { state.storageAvailable = false; }
    feedbackCache.set(key, ["useful", "later", "skip"].includes(value) ? value : null);
  }
  return feedbackCache.get(key);
}

function externalUrl(...values) {
  for (const value of values) {
    if (!value) continue;
    try {
      const url = new URL(value);
      if (["https:", "http:"].includes(url.protocol)) return url.href;
    } catch { /* Try the next available paper link. */ }
  }
  return "";
}

function currentPapers() {
  const query = state.query.trim().toLocaleLowerCase();
  return state.papers.filter((paper) => {
    const topicMatches = state.topic === "all" || Object.hasOwn(paper.topic_scores || {}, state.topic);
    const feedback = state.feedback === "all" ? null : savedFeedback(paper.paper_id);
    const feedbackMatches = state.feedback === "all" || (state.feedback === "unread" ? !feedback : feedback === state.feedback);
    const topics = Object.keys(paper.topic_scores || {}).flatMap((topic) => [topic, topicLabels[topic] || ""]);
    const haystack = `${paper.title} ${paper.abstract} ${paper.summary_zh || ""} ${(paper.authors || []).join(" ")} ${topics.join(" ")}`.toLocaleLowerCase();
    return topicMatches && feedbackMatches && (!query || query.split(/\s+/).every((word) => haystack.includes(word)));
  }).sort((left, right) => state.sort === "updated" ? right.updated.localeCompare(left.updated) : right.score - left.score);
}

function renderSkeleton(count = 6) {
  state.loading = true;
  state.error = false;
  const grid = $("#papers");
  grid.setAttribute("aria-busy", "true");
  grid.innerHTML = `<article class="paper-card skeleton" aria-hidden="true">
    <div class="sk sk-top"></div><div class="sk sk-meter"></div>
    <div class="sk sk-title"></div><div class="sk sk-title short"></div>
    <div class="sk sk-line"></div><div class="sk sk-line"></div><div class="sk sk-line short"></div>
    <div class="sk sk-foot"></div>
  </article>`.repeat(count);
  $("#empty").hidden = true;
  $("#load-more").hidden = true;
  $("#retry-load").hidden = true;
  $("#paper-count").textContent = "正在加载…";
}

function renderCard(paper, index, template) {
  const node = template.content.cloneNode(true);
  const card = node.querySelector(".paper-card");
  card.dataset.paperId = paper.paper_id;
  card.classList.add("enter");
  card.style.setProperty("--i", Math.min(index, 14));

  const topics = Object.keys(paper.topic_scores || {});
  card.querySelector(".topic").textContent = topics.map((topic) => topicLabels[topic] || topic).join(" / ") || "人工复核";

  const scoreVal = clamp(Math.round(Number(paper.score) || 0));
  card.querySelector(".score-val").textContent = scoreVal;
  card.querySelector(".score-meter i").dataset.w = scoreVal;

  card.querySelector("h2").textContent = paper.title;
  card.querySelector(".authors").textContent = (paper.authors || []).slice(0, 3).join(" · ");

  const meta = [];
  if (paper.venue) meta.push(`<li>${escapeHtml(paper.venue)}</li>`);
  const codeUrl = externalUrl(paper.code_url);
  if (codeUrl) meta.push(`<li><a href="${escapeHtml(codeUrl)}" target="_blank" rel="noreferrer">代码 ↗</a></li>`);
  if (paper.cited_by_count) meta.push(`<li>被引 ${escapeHtml(paper.cited_by_count)}</li>`);
  const metaEl = card.querySelector(".meta");
  if (meta.length) { metaEl.hidden = false; metaEl.innerHTML = meta.join(""); }

  const abstractEl = card.querySelector(".abstract");
  const fullAbstract = (paper.abstract || "").trim();
  if (paper.summary_zh) {
    const blocks = [`<p class="abstract-zh">${escapeHtml(paper.summary_zh)}</p>`];
    if (fullAbstract) blocks.push(`<p class="abstract-en"><span class="abstract-label">原文摘要</span>${escapeHtml(fullAbstract)}</p>`);
    abstractEl.innerHTML = blocks.join("");
  } else {
    abstractEl.textContent = fullAbstract;
  }
  const abstractToggle = card.querySelector(".abstract-toggle");
  abstractToggle.addEventListener("click", () => {
    const collapsed = abstractEl.classList.toggle("is-collapsed");
    abstractToggle.setAttribute("aria-expanded", String(!collapsed));
    abstractToggle.textContent = collapsed ? "展开全文 ▾" : "收起 ▴";
  });

  const breakdown = paper.score_breakdown || {};
  const rows = breakdownOrder.filter((key) => key in breakdown).map((key) => {
    const value = clamp(Math.round(Number(breakdown[key]) || 0));
    const primary = key === "relevance" ? " is-primary" : "";
    return `<div class="bar${primary}"><span class="bar-k">${breakdownLabels[key] || key}</span><span class="bar-track"><i data-w="${value}"></i></span><b class="bar-v">${value}</b></div>`;
  });
  card.querySelector(".breakdown").innerHTML = rows.length ? `<p class="breakdown-cap">评分构成</p>${rows.join("")}` : "";

  const confidence = Number(paper.confidence || 0);
  const assessed = Object.keys(paper.llm_scores || {}).length > 0;
  card.querySelector(".confidence").textContent = assessed
    ? `模型辅助评审${confidence ? ` · 置信度 ${Math.round(confidence)}` : ""}`
    : "规则初筛 · 建议结合原文判断";

  const risk = card.querySelector(".risk");
  if (paper.risk_zh) { risk.hidden = false; risk.textContent = `注意：${paper.risk_zh}`; }

  const paperLink = card.querySelector(".paper-link");
  const paperUrl = externalUrl(paper.abs_url, paper.pdf_url);
  if (paperUrl) paperLink.href = paperUrl;
  else { paperLink.textContent = "暂无论文链接"; paperLink.setAttribute("aria-disabled", "true"); }
  card.querySelector(".reasons").innerHTML = (paper.score_reasons || []).map((reason) => `<span class="reason">${escapeHtml(reason)}</span>`).join("");

  const feedback = savedFeedback(paper.paper_id);
  if (feedback === "skip") card.classList.add("is-dimmed");
  card.querySelectorAll(".feedback button").forEach((button) => {
    const selected = feedback === button.dataset.feedback;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
    button.addEventListener("click", () => sendFeedback(paper.paper_id, button.dataset.feedback, button, card));
  });
  return node;
}

function render({ append = false } = {}) {
  const papers = currentPapers();
  const grid = $("#papers");
  const template = $("#paper-template");
  const start = append ? grid.children.length : 0;
  if (!append) grid.replaceChildren();
  grid.setAttribute("aria-busy", "false");
  papers.slice(start, state.visibleCount).forEach((paper, index) => grid.append(renderCard(paper, index, template)));

  // On the next frame, fill score meters/breakdown bars (so the width transition plays) and
  // reveal the "展开全文" toggle only on cards whose abstract is actually clipped. Re-run after
  // web fonts load, since line heights — and thus overflow — can shift once the font swaps in.
  const settle = () => {
    grid.querySelectorAll("i[data-w]").forEach((bar) => { bar.style.width = `${bar.dataset.w}%`; });
    grid.querySelectorAll(".abstract.is-collapsed").forEach((el) => {
      const toggle = el.nextElementSibling;
      if (el.scrollHeight > el.clientHeight + 4) {
        if (toggle) toggle.hidden = false;
      } else {
        el.classList.remove("is-collapsed");
        if (toggle) toggle.hidden = true;
      }
    });
  };
  requestAnimationFrame(settle);
  if (document.fonts?.ready) document.fonts.ready.then(settle);

  const shown = Math.min(papers.length, state.visibleCount);
  $("#paper-count").textContent = shown < papers.length ? `已显示 ${shown} / ${papers.length} 篇` : papers.length === state.papers.length ? `共 ${papers.length} 篇` : `${papers.length} / ${state.papers.length} 篇`;
  const loadMore = $("#load-more");
  loadMore.hidden = shown >= papers.length;
  loadMore.textContent = `再看 ${Math.min(PAGE_SIZE, papers.length - shown)} 篇（还剩 ${papers.length - shown} 篇）`;
  const empty = $("#empty");
  empty.textContent = state.feedback !== "all"
    ? "当前筛选下没有这类阅读标记。切到“全部历史”查看跨期清单，或重置筛选。"
    : state.query || state.topic !== "all" ? "没有符合当前筛选的论文。换个关键词或查看全部主题。" : "这期没有新的入选论文；历史推荐仍可在“全部历史”中查看。";
  empty.hidden = papers.length !== 0;
  updateToolbar();
}

function filterAndRender() {
  if (state.loading || state.error) return;
  state.visibleCount = PAGE_SIZE;
  render();
}

function updateToolbar() {
  const hasQuery = state.query.trim() !== "";
  $("#search-clear").hidden = !hasQuery;
  $("#filter-reset").hidden = !(hasQuery || state.topic !== "all" || state.sort !== "score" || state.feedback !== "all");
  const note = $("#storage-note");
  note.classList.toggle("is-warning", !state.storageAvailable);
  note.textContent = state.storageAvailable
    ? "阅读标记保存在当前浏览器，可在“全部历史”中找回。再次点击可取消标记。"
    : "当前浏览器无法保存阅读标记。本次打开期间仍可使用，关闭页面后可能丢失。";
}

function rebuildTopicFilter() {
  const select = $("#topic-filter");
  select.replaceChildren(new Option("全部主题", "all"));
  [...new Set(state.papers.flatMap((paper) => Object.keys(paper.topic_scores || {})))].sort().forEach((topic) => select.add(new Option(topicLabels[topic] || topic, topic)));
  state.topic = "all";
  select.value = "all";
}

async function loadEdition(date) {
  renderSkeleton();
  const path = date === "all" ? "data/catalog.json" : date ? `data/${date}.json` : "data/latest.json";
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`Daily paper data is unavailable: ${path}`);
  const payload = await response.json();
  if (!Array.isArray(payload.papers)) throw new Error("Invalid paper data");
  state.date = date === "all" ? "all" : payload.date;
  state.papers = payload.papers || [];
  $("#edition").textContent = date === "all" ? "ALL EDITIONS / PAPER ARCHIVE" : `${payload.date} / DAILY EDITION`;
  $("#edition-headline").innerHTML = date === "all" ? "历史里，<em>值得重访</em>什么？" : "这一期，<em>值得打开</em>什么？";
  const generated = new Date(payload.generated_at);
  const generatedText = Number.isFinite(generated.getTime())
    ? ` · 采集于北京时间 ${new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(generated)}`
    : "";
  $("#edition-note").textContent = date === "all"
    ? `${state.editions.length} 期归档 · 最新一期 ${state.editions.at(-1) || "—"}`
    : `${payload.date} 入选清单${generatedText}`;
  const candidateCount = Number(payload.candidate_count || 0);
  $("#summary").textContent = date === "all"
    ? `在 ${state.papers.length} 篇历史推荐中检索值得重访的方法。`
    : candidateCount
      ? `从 ${candidateCount} 篇未见候选中筛出 ${state.papers.length} 篇，比较研究质量、新颖性与实用价值。`
      : `从 ${state.papers.length} 篇入选论文中，比较匹配度、研究质量、新颖性与实用价值。`;
  rebuildTopicFilter();
  state.loading = false;
  filterAndRender();
}

function showError(message) {
  state.loading = false;
  state.error = true;
  const grid = $("#papers");
  grid.replaceChildren();
  grid.setAttribute("aria-busy", "false");
  const empty = $("#empty");
  empty.textContent = message || "论文清单暂时无法加载。请检查网络连接后重新加载。";
  empty.hidden = false;
  $("#load-more").hidden = true;
  $("#retry-load").hidden = false;
  $("#paper-count").textContent = "加载未完成";
}

function sendFeedback(paperId, action, button, card) {
  const selected = savedFeedback(paperId) === action ? null : action;
  const key = canonicalId(paperId);
  feedbackCache.set(key, selected);
  try {
    if (selected) localStorage.setItem(`paper-feedback:${key}`, selected);
    else {
      localStorage.removeItem(`paper-feedback:${key}`);
      localStorage.removeItem(`paper-feedback:${paperId}`);
    }
  } catch { state.storageAvailable = false; }
  button.parentElement.querySelectorAll("button").forEach((item) => { item.classList.remove("is-selected"); item.setAttribute("aria-pressed", "false"); });
  button.classList.toggle("is-selected", selected === action);
  button.setAttribute("aria-pressed", String(selected === action));
  if (card) card.classList.toggle("is-dimmed", selected === "skip");
  if (state.feedback !== "all") { filterAndRender(); $("#feedback-filter").focus(); }
  else updateToolbar();
}

function watchStickyToolbar() {
  const sentinel = $("#toolbar-sentinel");
  const toolbar = $(".toolbar");
  if (!sentinel || !toolbar || !("IntersectionObserver" in window)) return;
  new IntersectionObserver(([entry]) => toolbar.classList.toggle("is-stuck", !entry.isIntersecting)).observe(sentinel);
}

async function init() {
  renderSkeleton();
  watchStickyToolbar();
  $("#retry-load").addEventListener("click", () => location.reload());
  const dateSelect = $("#date-filter");
  dateSelect.disabled = true;

  const historyResponse = await fetch("data/history.json", { cache: "no-store" });
  if (!historyResponse.ok) throw new Error("Paper archive is unavailable");
  const history = (await historyResponse.json()).sort();
  state.editions = history;
  dateSelect.add(new Option("全部历史", "all"));
  [...history].sort().reverse().forEach((date) => dateSelect.add(new Option(date, date)));
  dateSelect.addEventListener("change", async (event) => {
    dateSelect.disabled = true;
    try { await loadEdition(event.target.value); }
    catch (error) { showError(); console.error(error); }
    finally { dateSelect.disabled = false; }
  });

  $("#topic-filter").addEventListener("change", (event) => { state.topic = event.target.value; filterAndRender(); });
  $("#sort-filter").addEventListener("change", (event) => { state.sort = event.target.value; filterAndRender(); });
  $("#feedback-filter").addEventListener("change", (event) => { state.feedback = event.target.value; filterAndRender(); });
  const searchInput = $("#search-input");
  searchInput.addEventListener("input", (event) => { state.query = event.target.value; filterAndRender(); });
  $("#search-clear").addEventListener("click", () => { searchInput.value = ""; state.query = ""; filterAndRender(); searchInput.focus(); });
  $("#filter-reset").addEventListener("click", () => {
    state.topic = "all"; state.sort = "score"; state.query = ""; state.feedback = "all";
    $("#feedback-filter").value = "all";
    $("#topic-filter").value = "all"; $("#sort-filter").value = "score"; searchInput.value = "";
    filterAndRender();
  });
  $("#load-more").addEventListener("click", () => { state.visibleCount += PAGE_SIZE; render({ append: true }); });

  try { await loadEdition(history.at(-1) || null); }
  finally { dateSelect.disabled = false; }
  if (state.date && [...dateSelect.options].some((option) => option.value === state.date)) dateSelect.value = state.date;
}

init().catch((error) => {
  showError("论文清单暂时无法加载。请检查网络连接后重新加载。");
  $("#summary").textContent = "论文清单加载未完成。";
  console.error(error);
});
