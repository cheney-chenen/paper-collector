const state = { papers: [], topic: "all", sort: "score", date: null, query: "" };
const topicLabels = { pretraining: "预训练", "post-training": "后训练", reasoning: "推理扩展", serving: "推理系统", efficiency: "高效推理" };
const breakdownOrder = ["relevance", "quality", "novelty", "practical", "credibility", "personal"];
const breakdownLabels = { relevance: "匹配", quality: "质量", novelty: "新颖", practical: "实用", credibility: "可信", personal: "偏好" };

const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;" }[character]));
const clamp = (value) => Math.max(0, Math.min(100, value));
const $ = (selector) => document.querySelector(selector);

function currentPapers() {
  const query = state.query.trim().toLocaleLowerCase();
  return state.papers.filter((paper) => {
    const topicMatches = state.topic === "all" || Object.hasOwn(paper.topic_scores || {}, state.topic);
    const haystack = `${paper.title} ${paper.abstract} ${(paper.authors || []).join(" ")} ${Object.keys(paper.topic_scores || {}).join(" ")}`.toLocaleLowerCase();
    return topicMatches && (!query || haystack.includes(query));
  }).sort((left, right) => state.sort === "updated" ? right.updated.localeCompare(left.updated) : right.score - left.score);
}

function renderSkeleton(count = 6) {
  const grid = $("#papers");
  grid.setAttribute("aria-busy", "true");
  grid.innerHTML = `<article class="paper-card skeleton" aria-hidden="true">
    <div class="sk sk-top"></div><div class="sk sk-meter"></div>
    <div class="sk sk-title"></div><div class="sk sk-title short"></div>
    <div class="sk sk-line"></div><div class="sk sk-line"></div><div class="sk sk-line short"></div>
    <div class="sk sk-foot"></div>
  </article>`.repeat(count);
  $("#empty").hidden = true;
}

function renderCard(paper, index, template) {
  const node = template.content.cloneNode(true);
  const card = node.querySelector(".paper-card");
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
  if (paper.code_url) meta.push(`<li><a href="${escapeHtml(paper.code_url)}" target="_blank" rel="noreferrer">代码 ↗</a></li>`);
  if (paper.cited_by_count) meta.push(`<li>被引 ${escapeHtml(paper.cited_by_count)}</li>`);
  const metaEl = card.querySelector(".meta");
  if (meta.length) { metaEl.hidden = false; metaEl.innerHTML = meta.join(""); }

  card.querySelector(".abstract").textContent = paper.summary_zh || paper.abstract;

  const breakdown = paper.score_breakdown || {};
  const rows = breakdownOrder.filter((key) => key in breakdown).map((key) => {
    const value = clamp(Math.round(Number(breakdown[key]) || 0));
    const primary = key === "relevance" ? " is-primary" : "";
    return `<div class="bar${primary}"><span class="bar-k">${breakdownLabels[key] || key}</span><span class="bar-track"><i data-w="${value}"></i></span><b class="bar-v">${value}</b></div>`;
  });
  card.querySelector(".breakdown").innerHTML = rows.length ? `<p class="breakdown-cap">评分构成</p>${rows.join("")}` : "";

  const confidence = Number(paper.confidence || 0);
  card.querySelector(".confidence").textContent = confidence ? `置信度 ${confidence >= 75 ? "高" : confidence >= 50 ? "中" : "低"} · ${Math.round(confidence)}` : "";

  const risk = card.querySelector(".risk");
  if (paper.risk_zh) { risk.hidden = false; risk.textContent = `注意：${paper.risk_zh}`; }

  card.querySelector(".paper-link").href = paper.pdf_url || paper.abs_url;
  card.querySelector(".reasons").innerHTML = (paper.score_reasons || []).map((reason) => `<span class="reason">${escapeHtml(reason)}</span>`).join("");

  const savedFeedback = localStorage.getItem(`paper-feedback:${paper.paper_id}`);
  if (savedFeedback === "skip") card.classList.add("is-dimmed");
  card.querySelectorAll(".feedback button").forEach((button) => {
    const selected = savedFeedback === button.dataset.feedback;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
    button.addEventListener("click", () => sendFeedback(paper.paper_id, button.dataset.feedback, button, card));
  });
  return node;
}

function render() {
  const papers = currentPapers();
  const grid = $("#papers");
  const template = $("#paper-template");
  grid.replaceChildren();
  grid.setAttribute("aria-busy", "false");
  papers.forEach((paper, index) => grid.append(renderCard(paper, index, template)));

  // Fill score meters and breakdown bars on the next frame so the width transition plays.
  requestAnimationFrame(() => grid.querySelectorAll("i[data-w]").forEach((bar) => { bar.style.width = `${bar.dataset.w}%`; }));

  $("#paper-count").textContent = papers.length === state.papers.length ? `${papers.length} 篇入选` : `${papers.length} / ${state.papers.length} 篇`;
  const empty = $("#empty");
  empty.textContent = state.query || state.topic !== "all" ? "没有符合当前筛选的论文。换个关键词或查看全部主题。" : "这期没有新的入选论文；历史推荐仍可在“全部历史”中查看。";
  empty.hidden = papers.length !== 0;
  updateToolbar();
}

function updateToolbar() {
  const hasQuery = state.query.trim() !== "";
  $("#search-clear").hidden = !hasQuery;
  $("#filter-reset").hidden = !(hasQuery || state.topic !== "all" || state.sort !== "score");
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
  state.date = payload.date;
  state.papers = payload.papers || [];
  $("#edition").textContent = date === "all" ? "ALL EDITIONS / PAPER ARCHIVE" : `${payload.date} / DAILY EDITION`;
  const candidateCount = Number(payload.candidate_count || 0);
  $("#summary").textContent = date === "all"
    ? `在 ${state.papers.length} 篇历史推荐中检索值得重访的方法。`
    : candidateCount
      ? `从 ${candidateCount} 篇未见候选中筛出 ${state.papers.length} 篇，比较研究质量、新颖性与实用价值。`
      : `从 ${state.papers.length} 篇入选论文中，比较匹配度、研究质量、新颖性与实用价值。`;
  rebuildTopicFilter();
  render();
}

function showError(message) {
  const grid = $("#papers");
  grid.replaceChildren();
  grid.setAttribute("aria-busy", "false");
  const empty = $("#empty");
  empty.textContent = message || "数据加载失败，请稍后重试。";
  empty.hidden = false;
}

function sendFeedback(paperId, action, button, card) {
  button.parentElement.querySelectorAll("button").forEach((item) => { item.classList.remove("is-selected"); item.setAttribute("aria-pressed", "false"); });
  button.classList.add("is-selected");
  button.setAttribute("aria-pressed", "true");
  localStorage.setItem(`paper-feedback:${paperId}`, action);
  if (card) card.classList.toggle("is-dimmed", action === "skip");
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

  const historyResponse = await fetch("data/history.json", { cache: "no-store" });
  const history = historyResponse.ok ? await historyResponse.json() : [];
  const dateSelect = $("#date-filter");
  dateSelect.add(new Option("全部历史", "all"));
  [...history].sort().reverse().forEach((date) => dateSelect.add(new Option(date, date)));
  dateSelect.addEventListener("change", async (event) => {
    dateSelect.disabled = true;
    try { await loadEdition(event.target.value); }
    catch (error) { showError(); console.error(error); }
    finally { dateSelect.disabled = false; }
  });

  $("#topic-filter").addEventListener("change", (event) => { state.topic = event.target.value; render(); });
  $("#sort-filter").addEventListener("change", (event) => { state.sort = event.target.value; render(); });
  const searchInput = $("#search-input");
  searchInput.addEventListener("input", (event) => { state.query = event.target.value; render(); });
  $("#search-clear").addEventListener("click", () => { searchInput.value = ""; state.query = ""; render(); searchInput.focus(); });
  $("#filter-reset").addEventListener("click", () => {
    state.topic = "all"; state.sort = "score"; state.query = "";
    $("#topic-filter").value = "all"; $("#sort-filter").value = "score"; searchInput.value = "";
    render();
  });

  await loadEdition(history.at(-1) || null);
  if (state.date && [...dateSelect.options].some((option) => option.value === state.date)) dateSelect.value = state.date;
}

init().catch((error) => { showError("尚未生成日报。请先运行采集任务。"); $("#summary").textContent = "尚未生成日报。请先运行采集任务。"; console.error(error); });
