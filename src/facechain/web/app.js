const selectOne = (selector) => document.querySelector(selector);
const imageInput = selectOne("#image-input");
const dropzone = selectOne("#dropzone");
const preview = selectOne("#preview");
const dropCopy = selectOne("#drop-copy");
const replaceButton = selectOne("#replace-button");
const consent = selectOne("#consent");
const runButton = selectOne("#run-button");
const formError = selectOne("#form-error");
const idleState = selectOne("#idle-state");
const progress = selectOne("#progress");
const steps = [...document.querySelectorAll("#progress li")];
const results = selectOne("#results");
const downloadButton = selectOne("#download-button");
const proofInput = selectOne("#proof-input");
const verifyProofButton = selectOne("#verify-proof-button");
const proofStatus = selectOne("#proof-status");

let imageFile = null;
let progressTimer = null;
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

function beginProgress() {
  idleState.hidden = true;
  progress.hidden = false;
  steps.forEach((step) => step.classList.remove("active", "done"));
  let active = 0;
  steps[active].classList.add("active");
  progressTimer = window.setInterval(() => {
    if (active >= steps.length - 1) return;
    steps[active].classList.replace("active", "done");
    active += 1;
    steps[active].classList.add("active");
  }, 1700);
}

function finishProgress(ok) {
  window.clearInterval(progressTimer);
  steps.forEach((step) => {
    step.classList.remove("active");
    if (ok) step.classList.add("done");
  });
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

runButton.addEventListener("click", async () => {
  if (!imageFile || !consent.checked) return;
  runButton.disabled = true;
  runButton.querySelector("span").textContent = "Verification running…";
  formError.textContent = "";
  results.hidden = true;
  beginProgress();

  const body = new FormData();
  body.append("image", imageFile);
  body.append("consent", "true");

  try {
    const response = await fetch("/api/verify", { method: "POST", body });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Verification failed.");
    finishProgress(true);
    showResult(data);
  } catch (error) {
    finishProgress(false);
    formError.textContent = error.message;
  } finally {
    runButton.querySelector("span").textContent = "Run verification";
    syncRunButton();
  }
});

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
