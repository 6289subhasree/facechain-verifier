const selectOne = (selector) => document.querySelector(selector);
const imageInput = selectOne("#image-input");
const dropzone = selectOne("#dropzone");
const preview = selectOne("#preview");
const dropCopy = selectOne("#drop-copy");
const replaceButton = selectOne("#replace-button");
const consent = selectOne("#consent");
const runButton = selectOne("#run-button");
const retryButton = selectOne("#retry-button");
const formError = selectOne("#form-error");
const idleState = selectOne("#idle-state");
const processPanel = selectOne("#process-panel");
const pipelineBadge = selectOne("#pipeline-badge");
const runMeta = selectOne("#run-meta");
const runStatus = selectOne("#run-status");
const elapsedTime = selectOne("#elapsed-time");
const progressTrack = selectOne("#progress-track");
const progressFill = selectOne("#progress-fill");
const progressNote = selectOne("#progress-note");
const progress = selectOne("#progress");
const steps = [...document.querySelectorAll("#progress li")];
const results = selectOne("#results");
const downloadButton = selectOne("#download-button");
const proofInput = selectOne("#proof-input");
const verifyProofButton = selectOne("#verify-proof-button");
const proofStatus = selectOne("#proof-status");

let imageFile = null;
let progressTimers = [];
let elapsedTimer = null;
let runStartedAt = 0;
let lastProofBundle = null;

function syncRunButton() {
  runButton.disabled = !(imageFile && consent.checked);
}

function selectImage(nextFile) {
  if (!nextFile) return;
  if (!["image/jpeg", "image/png", "image/webp"].includes(nextFile.type)) {
    formError.textContent = "Choose a JPG, PNG, or WebP image.";
    return;
  }
  if (nextFile.size > 12 * 1024 * 1024) {
    formError.textContent = "Image must be 12 MB or smaller.";
    return;
  }

  imageFile = nextFile;
  formError.textContent = "";
  preview.src = URL.createObjectURL(nextFile);
  preview.hidden = false;
  dropCopy.hidden = true;
  replaceButton.hidden = false;
  syncRunButton();
}

imageInput.addEventListener("change", () => selectImage(imageInput.files[0]));
consent.addEventListener("change", syncRunButton);
replaceButton.addEventListener("click", (event) => {
  event.preventDefault();
  imageInput.click();
});

["dragenter", "dragover"].forEach((name) => {
  dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  });
});
["dragleave", "drop"].forEach((name) => {
  dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
  });
});
dropzone.addEventListener("drop", (event) => selectImage(event.dataTransfer.files[0]));

const progressStages = [
  { delay: 0, fill: 12, message: "Encoding the submitted face…" },
  { delay: 3500, fill: 38, message: "Searching public sources for candidates…" },
  { delay: 9000, fill: 66, message: "Comparing candidate face embeddings…" },
  { delay: 16000, fill: 88, message: "Preparing and anchoring the evidence fingerprint…" },
];

function formatElapsed(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function showProgressStage(index) {
  steps.forEach((step, stepIndex) => {
    step.classList.toggle("done", stepIndex < index);
    step.classList.toggle("active", stepIndex === index);
    step.toggleAttribute("aria-current", stepIndex === index);
  });
  runStatus.textContent = progressStages[index].message;
  progressFill.style.width = `${progressStages[index].fill}%`;
}

function clearProgressTimers() {
  progressTimers.forEach((timer) => window.clearTimeout(timer));
  progressTimers = [];
  window.clearInterval(elapsedTimer);
  elapsedTimer = null;
}

function beginProgress() {
  clearProgressTimers();
  idleState.hidden = true;
  runMeta.hidden = false;
  progressTrack.hidden = false;
  progress.hidden = false;
  progressNote.hidden = false;
  pipelineBadge.textContent = "RUNNING";
  pipelineBadge.className = "pipeline-badge running";
  processPanel.setAttribute("aria-busy", "true");
  progressFill.style.width = "0%";
  elapsedTime.textContent = "00:00";
  runStartedAt = Date.now();
  elapsedTimer = window.setInterval(() => {
    elapsedTime.textContent = formatElapsed(Date.now() - runStartedAt);
  }, 1000);

  progressStages.forEach((stage, index) => {
    progressTimers.push(window.setTimeout(() => showProgressStage(index), stage.delay));
  });
}

function finishProgress(ok) {
  clearProgressTimers();
  processPanel.setAttribute("aria-busy", "false");
  steps.forEach((step) => {
    step.classList.remove("active");
    step.removeAttribute("aria-current");
    if (ok) step.classList.add("done");
  });
  if (ok) {
    progressFill.style.width = "100%";
    runStatus.textContent = "Verification completed and proof confirmed.";
    pipelineBadge.textContent = "VERIFIED";
    pipelineBadge.className = "pipeline-badge verified";
  } else {
    progressFill.classList.add("failed");
    runStatus.textContent = "Verification stopped before completion.";
    pipelineBadge.textContent = "STOPPED";
    pipelineBadge.className = "pipeline-badge stopped";
  }
}

function put(selector, value) {
  selectOne(selector).textContent = value;
}

function showResult(data) {
  lastProofBundle = data.proof_bundle;
  put("#score", `${Math.max(0, data.evidence.similarity_score * 100).toFixed(1)}%`);
  put("#match-title", data.evidence.title);
  put("#search-rank", `#${data.evidence.search_rank}`);
  put("#candidate-count", data.evaluations.length);
  put("#chain-name", `${data.receipt.chain_name} · ID ${data.receipt.chain_id}`);
  put("#block-number", Number(data.receipt.block_number).toLocaleString());
  put("#transaction-hash", data.receipt.transaction_hash);
  put("#evidence-hash", data.receipt.evidence_hash);
  selectOne("#source-link").href = data.evidence.source_url;

  const explorerLink = selectOne("#explorer-link");
  if (data.receipt.explorer_url) {
    explorerLink.href = data.receipt.explorer_url;
    explorerLink.hidden = false;
  } else {
    explorerLink.hidden = true;
  }

  results.hidden = false;
  results.scrollIntoView({ behavior: "smooth" });
}

function setFormRunning(running) {
  imageInput.disabled = running;
  consent.disabled = running;
  replaceButton.disabled = running;
  runButton.disabled = running;
  if (running) retryButton.hidden = true;
  runButton.querySelector("span").textContent = running
    ? "Verification running…"
    : "Run verification";
}

function friendlyError(error) {
  if (error instanceof SyntaxError) return "The verifier returned an unreadable response. Please try again.";
  if (error.message === "Failed to fetch") return "Could not reach the verifier. Check that the server is still running.";
  return error.message || "Verification failed. Please try again.";
}

async function runVerification() {
  if (!imageFile || !consent.checked) return;
  setFormRunning(true);
  formError.textContent = "";
  results.hidden = true;
  progressFill.classList.remove("failed");
  beginProgress();

  const body = new FormData();
  body.append("image", imageFile);
  body.append("consent", "true");

  try {
    const response = await fetch("/api/verify", {
      method: "POST",
      body,
    });
    const responseText = await response.text();
    const data = JSON.parse(responseText);
    if (!response.ok) throw new Error(data.detail || "Verification failed.");
    finishProgress(true);
    showResult(data);
  } catch (error) {
    finishProgress(false);
    formError.textContent = friendlyError(error);
    retryButton.hidden = false;
    formError.focus();
  } finally {
    setFormRunning(false);
    syncRunButton();
  }
}

runButton.addEventListener("click", runVerification);
retryButton.addEventListener("click", runVerification);

downloadButton.addEventListener("click", () => {
  if (!lastProofBundle) return;
  const blob = new Blob([JSON.stringify(lastProofBundle, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const digest = lastProofBundle.receipt.evidence_hash.slice(2, 14);
  anchor.href = url;
  anchor.download = `facechain-proof-${digest}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
});

selectOne("#reset-button").addEventListener("click", () => {
  results.hidden = true;
  imageFile = null;
  lastProofBundle = null;
  imageInput.value = "";
  consent.checked = false;
  preview.hidden = true;
  preview.removeAttribute("src");
  dropCopy.hidden = false;
  replaceButton.hidden = true;
  progress.hidden = true;
  runMeta.hidden = true;
  progressTrack.hidden = true;
  progressNote.hidden = true;
  progressFill.classList.remove("failed");
  progressFill.style.width = "0%";
  pipelineBadge.textContent = "READY";
  pipelineBadge.className = "pipeline-badge";
  retryButton.hidden = true;
  formError.textContent = "";
  idleState.hidden = false;
  syncRunButton();
  dropzone.scrollIntoView({ behavior: "smooth", block: "center" });
});

proofInput.addEventListener("change", () => {
  verifyProofButton.disabled = !proofInput.files[0];
  proofStatus.textContent = "";
  proofStatus.className = "proof-status";
});

verifyProofButton.addEventListener("click", async () => {
  const proofFile = proofInput.files[0];
  if (!proofFile) return;

  verifyProofButton.disabled = true;
  proofStatus.className = "proof-status";
  proofStatus.textContent = "Checking blockchain transaction…";

  try {
    const bundle = JSON.parse(await proofFile.text());
    const response = await fetch("/api/proofs/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bundle),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Proof verification failed.");

    proofStatus.classList.add(data.verified ? "verified" : "invalid");
    proofStatus.textContent = data.verified
      ? `✓ VERIFIED — ${data.reason}`
      : `✕ TAMPER DETECTED — ${data.reason}`;
  } catch (error) {
    proofStatus.classList.add("invalid");
    proofStatus.textContent = `✕ ${error.message}`;
  } finally {
    verifyProofButton.disabled = false;
  }
});
