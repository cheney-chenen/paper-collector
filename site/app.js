const state = { papers: [], topic: "all", sort: "score" };
const feedbackEndpoint = window.PAPER_COLLECTOR_FEEDBACK_ENDPOINT || null;

const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[character]));

function currentPapers() {
  return state.papers.filter((paper) => state.topic === "all" || Object.hasOwn(paper.topic_scores || {}, state.topic)).sort((left, right) => state.sort === "updated" ? right.updated.localeCompare(left.updated) : right.score - left.score);
}

function render() {
  const papers = currentPapers();
  const grid = document.querySelector("#papers");
  const template = document.querySelector("#paper-template");
  grid.replaceChildren();
  papers.forEach((paper) => {
    const node = template.content.cloneNode(true);
    const card = node.querySelector(".paper-card");
    const topics = Object.keys(paper.topic_scores || {});
    card.querySelector(".topic").textContent = topics.join(" / ").toUpperCase() || "人工复核";
    card.querySelector(".score span").textContent = paper.score;
    card.querySelector("h2").textContent = paper.title;
    card.querySelector(".authors").textContent = (paper.authors || []).slice(0, 3).join(" · ");
    card.querySelector(".abstract").textContent = paper.summary_zh || paper.abstract;
    card.querySelector(".paper-link").href = paper.pdf_url || paper.abs_url;
    card.querySelector(".reasons").innerHTML = (paper.score_reasons || []).map((reason) => `<span class="reason">${escapeHtml(reason)}</span>`).join("");
    card.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => sendFeedback(paper.paper_id, button.dataset.feedback, button)));
    grid.append(node);
  });
  document.querySelector("#paper-count").textContent = `${papers.length} 篇入选`;
  document.querySelector("#empty").hidden = papers.length !== 0;
}

async function sendFeedback(paperId, action, button) {
  button.classList.add("is-selected");
  localStorage.setItem(`paper-feedback:${paperId}`, action);
  if (!feedbackEndpoint) return;
  try {
    const response = await fetch(feedbackEndpoint, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ paper_id: paperId, action }) });
    if (!response.ok) throw new Error("Feedback service rejected the request");
  } catch (error) { console.warn("Feedback was saved locally but not synced.", error); }
}

async function init() {
  const response = await fetch("data/latest.json", { cache: "no-store" });
  if (!response.ok) throw new Error("Daily paper data is unavailable.");
  const payload = await response.json();
  state.papers = payload.papers || [];
  document.querySelector("#edition").textContent = `${payload.date} / DAILY EDITION`;
  document.querySelector("#summary").textContent = `从 ${state.papers.length} 篇入选论文中，寻找可改变训练或推理实践的那个想法。`;
  const select = document.querySelector("#topic-filter");
  [...new Set(state.papers.flatMap((paper) => Object.keys(paper.topic_scores || {})))].forEach((topic) => select.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(topic)}">${escapeHtml(topic)}</option>`));
  select.addEventListener("change", (event) => { state.topic = event.target.value; render(); });
  document.querySelector("#sort-filter").addEventListener("change", (event) => { state.sort = event.target.value; render(); });
  render();
}

init().catch((error) => { document.querySelector("#summary").textContent = "尚未生成日报。请先运行采集任务。"; console.error(error); });
