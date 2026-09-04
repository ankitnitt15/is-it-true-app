const API_BASE_URL = "https://is-it-true-1jug.onrender.com";

const textInput = document.getElementById("text-input");
const charCount = document.getElementById("char-count");
const checkBtn = document.getElementById("check-btn");
const clearBtn = document.getElementById("clear-btn");
const attachBtn = document.getElementById("attach-btn");
const imageInput = document.getElementById("image-input");
const imagePreview = document.getElementById("image-preview");
const imagePreviewImg = document.getElementById("image-preview-img");
const imageRemoveBtn = document.getElementById("image-remove-btn");
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("status-text");
const statusDotsEl = document.getElementById("status-dots");
const resultEl = document.getElementById("result");
const resultCountsEl = document.getElementById("result-counts");
const resultSummaryEl = document.getElementById("result-summary");
const resultClaimsEl = document.getElementById("result-claims");

const MAX_CHARS = 3000;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

const VERDICT_ICON = { SUPPORTED: "✅", REFUTED: "❌", UNVERIFIABLE: "❓" };
const VERDICT_LABEL = { SUPPORTED: "True", REFUTED: "False", UNVERIFIABLE: "Unclear" };

let selectedImage = null; // File or Blob, or null
let claimCardsById = new Map(); // claim_id -> {card, badge, reasoning} while a check is in flight

textInput.addEventListener("input", () => {
  charCount.textContent = `${textInput.value.length} / ${MAX_CHARS}`;
  // A previously shown result described the *old* text -- once the user
  // starts editing, it no longer applies and would otherwise linger looking
  // like it still describes what's currently in the box.
  hideResult();
});

attachBtn.addEventListener("click", () => imageInput.click());

imageInput.addEventListener("change", () => {
  const file = imageInput.files[0];
  if (file) setSelectedImage(file);
  imageInput.value = "";
});

imageRemoveBtn.addEventListener("click", () => setSelectedImage(null));

clearBtn.addEventListener("click", () => {
  textInput.value = "";
  charCount.textContent = `0 / ${MAX_CHARS}`;
  setSelectedImage(null);
  hideStatus();
  hideResult();
});

// Paste a screenshot directly (Ctrl+V) instead of having to save it as a file first.
textInput.addEventListener("paste", (event) => {
  const items = event.clipboardData?.items || [];
  for (const item of items) {
    if (item.type.startsWith("image/")) {
      const file = item.getAsFile();
      if (file) setSelectedImage(file);
      event.preventDefault();
      return;
    }
  }
});

function setSelectedImage(file) {
  if (file && !ALLOWED_IMAGE_TYPES.includes(file.type)) {
    showStatus("Please attach a JPEG, PNG, or WEBP image.", true);
    return;
  }
  if (file && file.size > MAX_IMAGE_BYTES) {
    showStatus("That image is too large -- please attach one under 5MB.", true);
    return;
  }

  selectedImage = file;
  if (file) {
    imagePreviewImg.src = URL.createObjectURL(file);
    imagePreview.hidden = false;
  } else {
    imagePreviewImg.src = "";
    imagePreview.hidden = true;
  }

  // Attaching or removing an image changes what would be checked next --
  // any result on screen described the old input and no longer applies.
  hideResult();
}

checkBtn.addEventListener("click", async () => {
  const text = textInput.value.trim();
  if (!text && !selectedImage) {
    showStatus("Please paste some text or attach an image to check.", true);
    return;
  }

  setLoading(true);
  hideResult();

  try {
    const formData = new FormData();
    formData.append("text", text);
    if (selectedImage) formData.append("image", selectedImage);

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
  } finally {
    setLoading(false);
  }
});

// The backend streams progress as Server-Sent Events instead of one blocking
// JSON response, so claim cards can fill in one at a time instead of the
// whole result appearing at once after a long silent wait.
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

function setLoading(isLoading) {
  checkBtn.disabled = isLoading;
  checkBtn.textContent = isLoading ? "Checking..." : "Check this";
  if (isLoading) {
    showStatus("Checking claims -- this can take a few seconds...", false);
  }
}

function showStatus(message, isError) {
  statusTextEl.textContent = message;
  statusEl.hidden = false;
  statusEl.classList.toggle("error", isError);
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

function hideResult() {
  resultEl.hidden = true;
  resultCountsEl.innerHTML = "";
  resultClaimsEl.innerHTML = "";
  claimCardsById.clear();
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
