// Edit this before distributing the extension -- point it at your deployed
// backend, and add this extension's chrome-extension://<id> origin to the
// backend's CORS_ORIGINS once you know the id (see the extension's README).
const API_BASE_URL = "http://localhost:8000";

const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("status-text");
const statusDotsEl = document.getElementById("status-dots");
const resultEl = document.getElementById("result");
const resultCountsEl = document.getElementById("result-counts");
const resultSummaryEl = document.getElementById("result-summary");
const resultClaimsEl = document.getElementById("result-claims");

const VERDICT_ICON = { SUPPORTED: "✅", REFUTED: "❌", UNVERIFIABLE: "❓" };
const VERDICT_LABEL = { SUPPORTED: "True", REFUTED: "False", UNVERIFIABLE: "Unclear" };

let claimCardsById = new Map(); // claim_id -> {card, badge, reasoning} while a check is in flight

init();

async function init() {
  const id = new URLSearchParams(location.search).get("id");
  if (!id) {
    showStatus("Nothing to check -- open this from the right-click menu.", true);
    return;
  }

  const stored = await chrome.storage.session.get(id);
  const payload = stored[id];
  chrome.storage.session.remove(id);

  if (!payload) {
    showStatus("This check has expired -- right-click and try again.", true);
    return;
  }

  showStatus("Checking -- this can take a few seconds...", false);

  try {
    const formData = new FormData();

    if (payload.type === "text") {
      if (!payload.text || !payload.text.trim()) {
        showStatus("No text was selected to check.", true);
        return;
      }
      formData.append("text", payload.text);
    } else {
      let imageBlob;
      try {
        imageBlob = await fetchImageAsBlob(payload.srcUrl);
      } catch (err) {
        // Known limitation: some sites' CORS policy blocks fetching their
        // image bytes directly, even from an extension with host_permissions.
        // If this happens often in practice, the fallback is a content
        // script that draws the already-rendered <img> to a canvas instead.
        showStatus("Couldn't fetch that image (the site may block it) -- try saving it and using the web app's attach-image option instead.", true);
        return;
      }
      formData.append("text", "");
      formData.append("image", imageBlob, "image");
    }

    const response = await fetch(`${API_BASE_URL}/api/check/stream`, {
      method: "POST",
      credentials: "include",
      body: formData,
    });

    if (response.status === 429) {
      showStatus("You've used your free checks for today -- come back tomorrow.", true);
      return;
    }
    if (response.status === 503) {
      showStatus("This service hit today's usage limit -- please try again tomorrow.", true);
      return;
    }
    if (!response.ok) {
      const body = await safeJson(response);
      showStatus(body?.detail || "Something went wrong. Please try again.", true);
      return;
    }

    await readEventStream(response);
  } catch (err) {
    showStatus("Couldn't reach the checker. Check your connection and try again.", true);
  }
}

async function fetchImageAsBlob(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error("image fetch failed");
  return await response.blob();
}

// The backend streams progress as Server-Sent Events instead of one blocking
// JSON response -- mirrors frontend/app.js's readEventStream exactly.
async function readEventStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separatorIndex;
    while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      handleStreamEvent(rawEvent);
    }
  }
}

function handleStreamEvent(rawEvent) {
  const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data:"));
  if (!dataLine) return;

  let event;
  try {
    event = JSON.parse(dataLine.slice(5).trim());
  } catch {
    return;
  }

  if (event.event === "claims_found") {
    renderPlaceholderClaims(event.claims);
  } else if (event.event === "claim_verified") {
    updateClaimCard(event);
  } else if (event.event === "synthesizing") {
    showStatus("Writing summary...", false);
  } else if (event.event === "done") {
    renderDone(event);
  }
}

function showStatus(message, isError) {
  statusTextEl.textContent = message;
  statusEl.classList.toggle("error", isError);
  statusEl.hidden = false;
  // The "thinking" dots are for in-progress states only -- an error is a
  // final state, not something still happening.
  statusDotsEl.hidden = isError;
}

function hideStatus() {
  statusEl.hidden = true;
}

// CSS animations don't replay just because textContent/classList changed on
// an element that's already in the DOM -- forcing a reflow between removing
// and re-adding the class guarantees the reveal animation actually restarts
// on every check, not just the first one.
function playReveal(el) {
  el.classList.remove("reveal-in");
  void el.offsetWidth;
  el.classList.add("reveal-in");
}

// Transient: shows a "checking..." card per claim the moment extraction
// finishes, well before any verdict exists yet.
function renderPlaceholderClaims(claims) {
  resultCountsEl.innerHTML = "";
  resultSummaryEl.textContent = "";
  resultSummaryEl.classList.remove("no-claims");
  resultClaimsEl.innerHTML = "";
  claimCardsById.clear();

  for (const claim of claims) {
    const card = document.createElement("div");
    card.className = "claim-card PENDING";

    const badge = document.createElement("span");
    badge.className = "claim-badge PENDING";
    badge.textContent = "⏳ Checking...";

    const claimText = document.createElement("p");
    claimText.className = "claim-text";
    claimText.textContent = claim.text;

    const reasoning = document.createElement("p");
    reasoning.className = "claim-reasoning";

    card.appendChild(badge);
    card.appendChild(claimText);
    card.appendChild(reasoning);
    resultClaimsEl.appendChild(card);

    claimCardsById.set(claim.claim_id, { card, badge, reasoning });
  }

  showStatus(`Found ${claims.length} claim${claims.length === 1 ? "" : "s"} -- verifying...`, false);
  resultEl.hidden = false;
}

// Transient: fills in one placeholder card as its verdict resolves.
function updateClaimCard(event) {
  const entry = claimCardsById.get(event.claim_id);
  if (!entry) return;

  const { card, badge, reasoning } = entry;
  card.className = `claim-card ${event.verdict} reveal-in`;
  badge.className = `claim-badge ${event.verdict}`;
  badge.textContent = `${VERDICT_ICON[event.verdict] || "❓"} ${VERDICT_LABEL[event.verdict] || event.verdict}`;
  reasoning.textContent = event.reasoning;
}

// Authoritative final render, from the stream's last event -- rebuilds
// everything from scratch so a cache hit (which skips straight to this,
// with no preceding placeholder events at all) renders correctly too.
function renderDone(data) {
  hideStatus();
  resultCountsEl.innerHTML = "";
  resultClaimsEl.innerHTML = "";
  claimCardsById.clear();

  if (data.claims_checked === 0) {
    resultSummaryEl.textContent = data.summary || "No factual claims found in this text -- there's nothing to fact-check here.";
    resultSummaryEl.classList.add("no-claims");
    playReveal(resultSummaryEl);
    resultEl.hidden = false;
    return;
  }

  resultSummaryEl.classList.remove("no-claims");

  const claimWord = data.claims_checked === 1 ? "claim" : "claims";
  resultCountsEl.innerHTML = `
    <span class="count-chip total">${data.claims_checked} ${claimWord} checked</span>
    <span class="count-chip true">✅ ${data.supported_count} True</span>
    <span class="count-chip false">❌ ${data.refuted_count} False</span>
    <span class="count-chip unclear">❓ ${data.unverifiable_count} Unclear</span>
  `;

  resultSummaryEl.textContent = data.summary;
  playReveal(resultSummaryEl);

  data.claim_verdicts.forEach((cv, index) => {
    const verdict = cv.final_verdict;

    const card = document.createElement("div");
    card.className = `claim-card ${verdict} reveal-in`;
    card.style.animationDelay = `${index * 60}ms`;

    const badge = document.createElement("span");
    badge.className = `claim-badge ${verdict}`;
    badge.textContent = `${VERDICT_ICON[verdict] || "❓"} ${VERDICT_LABEL[verdict] || verdict}`;

    const claimText = document.createElement("p");
    claimText.className = "claim-text";
    claimText.textContent = cv.claim.text;

    const reasoning = document.createElement("p");
    reasoning.className = "claim-reasoning";
    reasoning.textContent = cv.reasoning;

    card.appendChild(badge);
    card.appendChild(claimText);
    card.appendChild(reasoning);
    resultClaimsEl.appendChild(card);
  });

  resultEl.hidden = false;
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
