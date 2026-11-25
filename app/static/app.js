"use strict";

/**
 * Discover (search + automatic analysis) and History (read-only browse of
 * saved analyses) share one detail-panel presentation but keep fully
 * independent state -- switching views never carries a stale selection
 * from one into the other (spec §3.5):
 *
 *  - Discover: currentQuery / searchResults / searchResultsByUrl /
 *    selectedUrl, plus analysisByUrl -- one map keyed by URL replacing
 *    separate "saved results" and "in-flight requests" maps. Each entry
 *    is exactly one of {status:'pending'}, {status:'ready', analysis},
 *    {status:'error', message}. A 'pending' entry doubles as the
 *    in-flight marker (re-selecting it reuses the request rather than
 *    firing a second POST); a failed request leaves a durable 'error'
 *    entry rather than a blank or stuck loader.
 *  - History: historyAnalyses / historyAnalysesById / historySelectedId /
 *    historyError. Selecting a history card never calls OpenAI or the
 *    news provider (spec §3.4) -- GET /api/analyses already returns the
 *    complete resource, so detail rendering is a pure, instant, local
 *    read from historyAnalysesById.
 *
 * Race safety: a POST already in flight for article A is never aborted
 * when the user selects B instead -- it's left to finish (so A's result
 * still gets cached/persisted even though it's no longer selected), and
 * its completion handler only re-renders the detail panel if
 * `state.selectedUrl` still equals A's URL at that point. Search uses
 * AbortController instead, since an outdated search's results should
 * never appear at all.
 *
 * Focus management: selecting an article/analysis on a narrow (mobile)
 * layout moves focus to the newly-shown detail heading, since the list
 * visually disappears there; "Back" returns focus to the card that was
 * selected. Desktop never needs this -- both panels stay visible and
 * reachable in normal tab order regardless of selection.
 */

const DESKTOP_MEDIA_QUERY = "(min-width: 768px)"; // must match styles.css's master-detail breakpoint

const state = {
  currentQuery: "",
  searchResults: null, // null = no search yet; [] = searched, zero results
  searchResultsByUrl: new Map(),
  selectedUrl: null,
  analysisByUrl: new Map(),

  historyAnalyses: null, // null = not loaded yet; [] = loaded, empty; array = loaded, has items
  historyAnalysesById: new Map(),
  historySelectedId: null,
  historyError: null,
};

let searchAbortController = null;

// --- DOM references (cached once; the page never reloads) -----------------

const navDiscoverButton = document.getElementById("nav-discover");
const navHistoryButton = document.getElementById("nav-history");
const discoverView = document.getElementById("discover-view");
const historyView = document.getElementById("history-view");

const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const searchStatus = document.getElementById("search-status");
const discoverMasterDetail = document.getElementById("discover-master-detail");
const discoverArticleList = document.getElementById("discover-article-list");
const discoverDetailPanel = document.getElementById("discover-detail-panel");
const discoverBackButton = document.getElementById("discover-back-button");

const historyStatus = document.getElementById("history-status");
const historyMasterDetail = document.getElementById("history-master-detail");
const historyArticleList = document.getElementById("history-article-list");
const historyDetailPanel = document.getElementById("history-detail-panel");
const historyBackButton = document.getElementById("history-back-button");

const articleCardTemplate = document.getElementById("article-card-template");
const historyCardTemplate = document.getElementById("history-card-template");
const detailMetadataTemplate = document.getElementById("detail-metadata-template");
const detailLoadingTemplate = document.getElementById("detail-loading-template");
const detailSuccessTemplate = document.getElementById("detail-success-template");
const detailErrorTemplate = document.getElementById("detail-error-template");

// --- API ---------------------------------------------------------------

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function extractErrorMessage(body) {
  // The server already returns a client-safe, non-technical `detail`
  // string for every error it maps (spec §6.5/§10 -- never raw provider
  // errors). Pydantic's own 422 shape is an array instead of a string;
  // that should never actually happen for snapshots we built ourselves
  // from search results, but fall back gracefully regardless.
  if (body && typeof body.detail === "string") return body.detail;
  return "Something went wrong. Please try again.";
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(extractErrorMessage(await safeJson(response)));
  }
  return response.json();
}

function searchArticles(query, signal) {
  return requestJson(`/api/articles?query=${encodeURIComponent(query)}`, { signal });
}

function createAnalysis(snapshot) {
  return requestJson("/api/analyses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(snapshot),
  });
}

function fetchHistory() {
  return requestJson("/api/analyses");
}

// --- Formatting helpers --------------------------------------------------

function formatPublishedAt(iso) {
  if (!iso) return "Date unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Date unknown";
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function capitalize(word) {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function buildSnapshot(article) {
  return {
    url: article.url,
    title: article.title,
    source: article.source,
    published_at: article.published_at,
    description: article.description,
    content: article.content,
  };
}

function isDesktopLayout() {
  return window.matchMedia(DESKTOP_MEDIA_QUERY).matches;
}

function moveFocusToDetailHeading(panel) {
  const heading = panel.querySelector("h2, h3");
  if (heading) {
    heading.setAttribute("tabindex", "-1");
    heading.focus();
  }
}

function focusSelectedCard(listContainer) {
  listContainer.querySelector(".article-card.is-selected")?.focus();
}

// --- Shared: empty/error placeholder paragraphs ----------------------------

function buildEmptyState(message) {
  const p = document.createElement("p");
  p.className = "empty-state";
  p.textContent = message;
  return p;
}

function buildErrorState(message) {
  const p = document.createElement("p");
  p.className = "error-message";
  p.setAttribute("role", "alert");
  p.textContent = message;
  return p;
}

// --- Shared: detail panel metadata / success blocks ------------------------
// Used by both Discover (a NormalizedArticle) and History (adapted from an
// AnalysisResource) -- same presentation either way (spec §3.1).

function buildMetadataNode(article) {
  const fragment = detailMetadataTemplate.content.cloneNode(true);
  fragment.querySelector(".detail-metadata__source").textContent = article.source || "Unknown source";
  fragment.querySelector(".detail-metadata__published").textContent = formatPublishedAt(article.published_at);
  fragment.querySelector(".detail-metadata__title").textContent = article.title;

  const descriptionEl = fragment.querySelector(".detail-metadata__description");
  if (article.description) {
    descriptionEl.textContent = article.description;
  } else {
    descriptionEl.hidden = true;
  }

  const link = fragment.querySelector(".detail-metadata__link");
  if (/^https?:\/\//i.test(article.url)) {
    link.href = article.url;
  } else {
    link.remove(); // defence in depth: never render a link we can't vouch for
  }

  return fragment;
}

function buildSuccessNode(analysis) {
  const fragment = detailSuccessTemplate.content.cloneNode(true);
  fragment.querySelector(".detail-summary").textContent = analysis.summary;

  const sentimentEl = fragment.querySelector(".sentiment-label");
  sentimentEl.textContent = capitalize(analysis.sentiment);
  sentimentEl.classList.add(`sentiment-label--${analysis.sentiment}`);

  fragment.querySelector(".detail-scope-note").textContent =
    analysis.content_scope === "excerpt"
      ? "Based on the available article excerpt."
      : "Based on the full article text.";

  return fragment;
}

function buildErrorNode(message) {
  const fragment = detailErrorTemplate.content.cloneNode(true);
  fragment.querySelector(".error-message").textContent = message;
  return fragment;
}

// --- Rendering: Discover article list -------------------------------------

function renderArticleList() {
  discoverArticleList.replaceChildren();

  if (state.searchResults === null) {
    discoverArticleList.appendChild(buildEmptyState("Search for a topic above to see recent articles."));
    return;
  }

  if (state.searchResults.length === 0) {
    discoverArticleList.appendChild(buildEmptyState("No recent articles found for this search."));
    return;
  }

  for (const article of state.searchResults) {
    discoverArticleList.appendChild(buildArticleCard(article));
  }
}

function buildArticleCard(article) {
  const fragment = articleCardTemplate.content.cloneNode(true);
  const button = fragment.querySelector(".article-card");
  const badge = fragment.querySelector(".article-card__badge");
  const sourceEl = fragment.querySelector(".article-card__source");
  const publishedEl = fragment.querySelector(".article-card__published");
  const titleEl = fragment.querySelector(".article-card__title");
  const descriptionEl = fragment.querySelector(".article-card__description");

  button.dataset.url = article.url;

  // analysis_id is the server's search-time hint (spec §6.1); a status of
  // 'ready' in our own cache is fresher if the user already analysed it
  // earlier in this same session.
  const alreadyAnalysed = article.analysis_id != null || state.analysisByUrl.get(article.url)?.status === "ready";
  badge.hidden = !alreadyAnalysed;

  sourceEl.textContent = article.source || "Unknown source";
  publishedEl.textContent = formatPublishedAt(article.published_at);
  titleEl.textContent = article.title;

  if (article.description) {
    descriptionEl.textContent = article.description;
  } else {
    descriptionEl.hidden = true;
  }

  const isSelected = article.url === state.selectedUrl;
  button.classList.toggle("is-selected", isSelected);
  button.setAttribute("aria-pressed", String(isSelected));

  return fragment;
}

discoverArticleList.addEventListener("click", (event) => {
  const card = event.target.closest(".article-card");
  if (!card) return;
  const article = state.searchResultsByUrl.get(card.dataset.url);
  if (article) selectArticle(article);
});

// --- Rendering: Discover detail panel --------------------------------------

function renderDetailPanel() {
  const panel = discoverDetailPanel;
  for (const child of Array.from(panel.children)) {
    if (child !== discoverBackButton) child.remove();
  }

  if (!state.selectedUrl) {
    panel.appendChild(buildEmptyState("Select an article to see its summary and sentiment."));
    return;
  }

  const article = state.searchResultsByUrl.get(state.selectedUrl);
  if (!article) return; // selection refers to a result no longer in the current list

  panel.appendChild(buildMetadataNode(article));

  const entry = state.analysisByUrl.get(state.selectedUrl);
  if (!entry || entry.status === "pending") {
    panel.appendChild(detailLoadingTemplate.content.cloneNode(true));
  } else if (entry.status === "ready") {
    panel.appendChild(buildSuccessNode(entry.analysis));
  } else if (entry.status === "error") {
    panel.appendChild(buildErrorNode(entry.message));
  }
}

// Retry is an error-recovery action only, never a normal prerequisite
// (spec §3.3) -- it's the one path that bypasses the "already have an
// entry" guard in ensureAnalysis.
discoverDetailPanel.addEventListener("click", (event) => {
  if (!event.target.closest(".retry-button")) return;
  const article = state.searchResultsByUrl.get(state.selectedUrl);
  if (article) ensureAnalysis(article, { force: true });
});

discoverBackButton.addEventListener("click", () => {
  // Mobile view-state only: the selection itself is preserved, so
  // re-opening the same article shows its already-cached state instantly.
  discoverMasterDetail.classList.remove("master-detail--showing-detail");
  discoverBackButton.hidden = true;
  focusSelectedCard(discoverArticleList);
});

// --- Selection + analysis ------------------------------------------------

function selectArticle(article) {
  state.selectedUrl = article.url;
  discoverMasterDetail.classList.add("master-detail--showing-detail");
  discoverBackButton.hidden = false;

  renderArticleList(); // updates is-selected highlighting
  renderDetailPanel();
  ensureAnalysis(article);

  if (!isDesktopLayout()) moveFocusToDetailHeading(discoverDetailPanel);
}

function ensureAnalysis(article, { force = false } = {}) {
  const existing = state.analysisByUrl.get(article.url);
  if (existing) {
    if (existing.status === "pending" || existing.status === "ready") return;
    if (existing.status === "error" && !force) return;
  }

  state.analysisByUrl.set(article.url, { status: "pending" });
  if (state.selectedUrl === article.url) renderDetailPanel();

  createAnalysis(buildSnapshot(article))
    .then((analysis) => {
      state.analysisByUrl.set(article.url, { status: "ready", analysis });
    })
    .catch((error) => {
      state.analysisByUrl.set(article.url, { status: "error", message: error.message });
    })
    .finally(() => {
      // The request always runs to completion and updates the cache/badge
      // even if the user has since selected something else (spec §3.5) --
      // only the currently-visible detail panel is guarded against a
      // stale response overwriting whatever's now on screen.
      renderArticleList();
      if (state.selectedUrl === article.url) renderDetailPanel();
    });
}

// --- Search ---------------------------------------------------------------

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return; // mirrors the server's own validation; avoids a pointless round trip
  runSearch(query);
});

async function runSearch(query) {
  state.currentQuery = query;

  if (searchAbortController) searchAbortController.abort();
  searchAbortController = new AbortController();
  const { signal } = searchAbortController;

  searchStatus.textContent = "Searching…";

  try {
    const data = await searchArticles(query, signal);

    state.searchResults = data.articles;
    state.searchResultsByUrl = new Map(data.articles.map((article) => [article.url, article]));
    state.selectedUrl = null;
    discoverMasterDetail.classList.remove("master-detail--showing-detail");
    discoverBackButton.hidden = true;

    searchStatus.textContent = data.articles.length ? "" : "No recent articles found for this search.";
    renderArticleList();
    renderDetailPanel();
  } catch (error) {
    if (error.name === "AbortError") return; // superseded by a newer search; ignore silently
    searchStatus.textContent = error.message;
  }
}

// --- History ---------------------------------------------------------------

async function loadHistory() {
  state.historyError = null;
  historyStatus.textContent = "Loading history…";
  renderHistoryList();

  try {
    const data = await fetchHistory();
    state.historyAnalyses = data.analyses;
    state.historyAnalysesById = new Map(data.analyses.map((analysis) => [analysis.id, analysis]));
    historyStatus.textContent = data.analyses.length
      ? ""
      : "No analyses yet. Select an article in Discover to create one.";
  } catch (error) {
    state.historyError = error.message;
    historyStatus.textContent = error.message;
  }

  renderHistoryList();
  renderHistoryDetailPanel(); // in case the selected row's data changed or disappeared on reload
}

function renderHistoryList() {
  historyArticleList.replaceChildren();

  if (state.historyError) {
    historyArticleList.appendChild(buildErrorState(state.historyError));
    return;
  }

  if (state.historyAnalyses === null) {
    historyArticleList.appendChild(buildEmptyState("Loading history…"));
    return;
  }

  if (state.historyAnalyses.length === 0) {
    historyArticleList.appendChild(
      buildEmptyState("No analyses yet. Select an article in Discover to create one.")
    );
    return;
  }

  for (const analysis of state.historyAnalyses) {
    historyArticleList.appendChild(buildHistoryCard(analysis));
  }
}

function buildHistoryCard(analysis) {
  const fragment = historyCardTemplate.content.cloneNode(true);
  const button = fragment.querySelector(".article-card");
  const sourceEl = fragment.querySelector(".article-card__source");
  const publishedEl = fragment.querySelector(".article-card__published");
  const titleEl = fragment.querySelector(".article-card__title");
  const sentimentEl = fragment.querySelector(".sentiment-label");

  button.dataset.id = String(analysis.id);
  sourceEl.textContent = analysis.source || "Unknown source";
  publishedEl.textContent = formatPublishedAt(analysis.published_at);
  titleEl.textContent = analysis.title;
  sentimentEl.textContent = capitalize(analysis.sentiment);
  sentimentEl.classList.add(`sentiment-label--${analysis.sentiment}`);

  const isSelected = analysis.id === state.historySelectedId;
  button.classList.toggle("is-selected", isSelected);
  button.setAttribute("aria-pressed", String(isSelected));

  return fragment;
}

historyArticleList.addEventListener("click", (event) => {
  const card = event.target.closest(".article-card");
  if (!card) return;
  const analysis = state.historyAnalysesById.get(Number(card.dataset.id));
  if (analysis) selectHistoryItem(analysis);
});

function renderHistoryDetailPanel() {
  const panel = historyDetailPanel;
  for (const child of Array.from(panel.children)) {
    if (child !== historyBackButton) child.remove();
  }

  if (!state.historySelectedId) {
    panel.appendChild(buildEmptyState("Select an analysis to view its summary and sentiment."));
    return;
  }

  const analysis = state.historyAnalysesById.get(state.historySelectedId);
  if (!analysis) return; // selection refers to a row no longer in the current list

  // Same detail presentation as Discover (spec §3.1): adapt the resource's
  // article_url to the `url` field buildMetadataNode expects.
  panel.appendChild(
    buildMetadataNode({
      url: analysis.article_url,
      title: analysis.title,
      source: analysis.source,
      published_at: analysis.published_at,
      description: analysis.description,
    })
  );
  // No loading/error state possible here: GET /api/analyses already
  // returned the complete resource, so this is a pure, instant, local
  // read -- never a fresh call to OpenAI or the news provider (spec §3.4).
  panel.appendChild(buildSuccessNode(analysis));
}

function selectHistoryItem(analysis) {
  state.historySelectedId = analysis.id;
  historyMasterDetail.classList.add("master-detail--showing-detail");
  historyBackButton.hidden = false;

  renderHistoryList();
  renderHistoryDetailPanel();

  if (!isDesktopLayout()) moveFocusToDetailHeading(historyDetailPanel);
}

historyBackButton.addEventListener("click", () => {
  historyMasterDetail.classList.remove("master-detail--showing-detail");
  historyBackButton.hidden = true;
  focusSelectedCard(historyArticleList);
});

// --- View switching ---------------------------------------------------------

navDiscoverButton.addEventListener("click", () => switchView("discover"));
navHistoryButton.addEventListener("click", () => switchView("history"));

function switchView(view) {
  const showDiscover = view === "discover";
  discoverView.hidden = !showDiscover;
  historyView.hidden = showDiscover;

  if (showDiscover) {
    navDiscoverButton.setAttribute("aria-current", "page");
    navHistoryButton.removeAttribute("aria-current");
  } else {
    navHistoryButton.setAttribute("aria-current", "page");
    navDiscoverButton.removeAttribute("aria-current");
    loadHistory(); // always refreshed on activation -- a new analysis made in
    // Discover since the last visit must be reflected, and this is a cheap
    // read-only call, not an external provider request.
  }
}

// --- Initial render (JS is the source of truth from here on) --------------

renderArticleList();
renderDetailPanel();
renderHistoryList();
renderHistoryDetailPanel();
