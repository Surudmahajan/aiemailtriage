"use strict";

// ─── Sample emails for quick demo ────────────────────────────────────────────
const SAMPLES = {
    tech: `Hi Support Team,

I've been getting a "500 Internal Server Error" every time I try to log into my account for the past 3 hours. I've cleared my cache and tried different browsers but nothing works. This is completely blocking my work and I have a deadline in 4 hours.

Please help ASAP.
— David Chen`,

    billing: `Hello,

I was charged $49.99 on June 30th but I cancelled my subscription on June 28th, two days before the billing cycle. I have the cancellation confirmation email. I'd like a full refund for this incorrect charge.

Thank you,
Sarah Williams`,

    refund: `I ordered a pair of wireless headphones (Order #HX-98231) and they arrived yesterday completely broken — the right ear cup is cracked and there's no audio output. The packaging was also damaged, so it looks like it was shipped this way. I want a full refund or a replacement unit shipped immediately.

Very disappointed,
Raj Patel`
};

// ─── DOM References ───────────────────────────────────────────────────────────
const backendStatus  = document.getElementById("backendStatus");
const statusText     = document.getElementById("statusText");

const emailInput     = document.getElementById("emailInput");
const analyzeBtn     = document.getElementById("analyzeBtn");
const analyzeBtnText = document.getElementById("analyzeBtnText");
const analyzeSpinner = document.getElementById("analyzeSpinner");

const senderBanner   = document.getElementById("senderBanner");
const senderAddress  = document.getElementById("senderAddress");
const emailSubject   = document.getElementById("emailSubject");

const resultsSection = document.getElementById("resultsSection");
const resTicketId    = document.getElementById("resTicketId");
const resCategory    = document.getElementById("resCategory");
const resPriority    = document.getElementById("resPriority");
const resSentiment   = document.getElementById("resSentiment");
const resTeam        = document.getElementById("resTeam");
const resEta         = document.getElementById("resEta");
const resConfText    = document.getElementById("resConfText");
const resConfBar     = document.getElementById("resConfBar");
const resIntent      = document.getElementById("resIntent");
const resSummary     = document.getElementById("resSummary");
const replyInput     = document.getElementById("replyInput");
const recipientInput = document.getElementById("recipientInput");

const approveBtn     = document.getElementById("approveBtn");
const approveBtnText = document.getElementById("approveBtnText");
const approveSpinner = document.getElementById("approveSpinner");

const rejectBtn      = document.getElementById("rejectBtn");
const rejectBtnText  = document.getElementById("rejectBtnText");
const rejectSpinner  = document.getElementById("rejectSpinner");

const toast          = document.getElementById("toast");
const toastMsg       = document.getElementById("toastMsg");
const toastIcon      = document.getElementById("toastIcon");
const toastClose     = document.getElementById("toastClose");

// ─── App State ────────────────────────────────────────────────────────────────
let currentAnalysis  = null;   // Holds the last AI result
let currentSender    = "";     // Email address of the original sender
let toastTimer       = null;
let backendOnline    = false;

// ─── Initialise ───────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    bindEvents();
});

function bindEvents() {
    document.getElementById("btnFetch").addEventListener("click", fetchFromInbox);
    document.getElementById("btnTech").addEventListener("click", () => fillSample("tech"));
    document.getElementById("btnBilling").addEventListener("click", () => fillSample("billing"));
    document.getElementById("btnRefund").addEventListener("click", () => fillSample("refund"));

    emailInput.addEventListener("input", updateAnalyzeBtn);
    analyzeBtn.addEventListener("click", analyzeEmail);
    approveBtn.addEventListener("click", () => submitDecision("approve"));
    rejectBtn.addEventListener("click", () => submitDecision("reject"));
    toastClose.addEventListener("click", hideToast);
}

// ─── Health Check ─────────────────────────────────────────────────────────────
async function checkHealth() {
    try {
        const res = await fetch(`${CONFIG.BACKEND_URL}/api/health`);
        if (!res.ok) throw new Error("Bad status");
        backendOnline = true;
        backendStatus.className = "status-pill healthy";
        statusText.textContent  = "Backend Online";
        updateAnalyzeBtn();
    } catch {
        backendOnline = false;
        backendStatus.className = "status-pill offline";
        statusText.textContent  = "Backend Offline — check your server";
        analyzeBtn.disabled     = true;
        showToast("Cannot reach the backend. Make sure the server is running.", "error");
    }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function updateAnalyzeBtn() {
    analyzeBtn.disabled = !backendOnline || emailInput.value.trim().length === 0;
}

function fillSample(type) {
    emailInput.value = SAMPLES[type];
    currentSender = "";
    senderBanner.classList.add("hidden");
    updateAnalyzeBtn();
}

function setLoading(btn, spinner, textEl, isOn, label) {
    btn.disabled = isOn;
    spinner.classList.toggle("hidden", !isOn);
    textEl.textContent = label;
}

// ─── Fetch Email from Inbox ───────────────────────────────────────────────────
async function fetchFromInbox() {
    const fetchBtn = document.getElementById("btnFetch");
    fetchBtn.disabled   = true;
    fetchBtn.textContent = "⬇ Fetching…";

    try {
        const res  = await fetch(`${CONFIG.BACKEND_URL}/api/fetch-email`);
        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || "Failed to fetch email from inbox.");
        }

        if (!data.found) {
            showToast("No unread emails found in inbox.", "info");
            return;
        }

        // Populate UI with fetched email
        currentSender        = data.sender_email || "";
        senderAddress.textContent = data.sender_email || "Unknown";
        emailSubject.textContent  = data.subject || "(No Subject)";
        senderBanner.classList.remove("hidden");
        emailInput.value     = data.body || "";
        recipientInput.value = data.sender_email || ""; // auto-fill recipient
        updateAnalyzeBtn();
        showToast(`Email fetched from ${data.sender_email}. Marked as read.`, "success");

    } catch (err) {
        showToast(`Fetch failed: ${err.message}`, "error");
    } finally {
        fetchBtn.disabled    = false;
        fetchBtn.textContent = "⬇ Fetch from Inbox";
    }
}

// ─── Analyze Email ────────────────────────────────────────────────────────────
async function analyzeEmail() {
    const body = emailInput.value.trim();
    if (!body) return;

    setLoading(analyzeBtn, analyzeSpinner, analyzeBtnText, true, "Analyzing…");
    resultsSection.classList.add("hidden");
    currentAnalysis = null;

    try {
        const res  = await fetch(`${CONFIG.BACKEND_URL}/api/analyze`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ email: body }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Server error ${res.status}`);

        currentAnalysis = data;
        currentAnalysis.sender_email = currentSender; // attach sender for later
        renderResults(data);
        resultsSection.classList.remove("hidden");

    } catch (err) {
        showToast(`Analysis failed: ${err.message}`, "error");
    } finally {
        setLoading(analyzeBtn, analyzeSpinner, analyzeBtnText, false, "Analyze Email");
    }
}

// ─── Render AI Results ────────────────────────────────────────────────────────
function renderResults(d) {
    resTicketId.textContent = d.ticket_id || "—";

    setText(resCategory, d.category);
    setTag(resPriority, d.priority, "priority-tag");
    setTag(resSentiment, d.sentiment, "sentiment-tag");

    resTeam.textContent    = d.assigned_team || "—";
    resEta.textContent     = d.estimated_response_time || "—";
    resIntent.textContent  = d.customer_intent || "—";
    resSummary.textContent = d.summary || "—";
    replyInput.value       = d.suggested_reply || "";

    const conf = Math.min(100, Math.max(0, Number(d.confidence) || 0));
    resConfText.textContent = `${conf}%`;
    // Small delay lets the CSS transition animate from 0
    requestAnimationFrame(() => requestAnimationFrame(() => {
        resConfBar.style.width = `${conf}%`;
    }));
}

function setText(el, value) {
    el.textContent = value || "—";
}

function setTag(el, value, extraClass) {
    el.textContent = value || "—";
    el.setAttribute("data-val", value || "");
}

// ─── Approve / Reject ─────────────────────────────────────────────────────────
async function submitDecision(action) {
    if (!currentAnalysis) return;

    const isApprove = action === "approve";
    const btn       = isApprove ? approveBtn : rejectBtn;
    const spinner   = isApprove ? approveSpinner : rejectSpinner;
    const textEl    = isApprove ? approveBtnText : rejectBtnText;
    const origLabel = isApprove ? "✓ Approve & Send" : "✕ Reject";

    // Use whatever is in the recipient input field (auto-filled or manually entered)
    currentAnalysis.sender_email   = recipientInput.value.trim();
    currentAnalysis.suggested_reply = replyInput.value;

    setLoading(btn, spinner, textEl, true, "Processing…");
    approveBtn.disabled = true;
    rejectBtn.disabled  = true;

    try {
        const res  = await fetch(`${CONFIG.BACKEND_URL}/api/${action}`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(currentAnalysis),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Server error ${res.status}`);

        showToast(data.message, "success");

        // Reset the UI after a short pause
        setTimeout(resetUI, 1800);

    } catch (err) {
        showToast(`Failed: ${err.message}`, "error");
        setLoading(btn, spinner, textEl, false, origLabel);
        approveBtn.disabled = false;
        rejectBtn.disabled  = false;
    }
}

// ─── Reset UI ─────────────────────────────────────────────────────────────────
function resetUI() {
    emailInput.value     = "";
    recipientInput.value = "";
    currentAnalysis      = null;
    currentSender    = "";
    senderBanner.classList.add("hidden");
    resultsSection.classList.add("hidden");
    resConfBar.style.width = "0%";
    updateAnalyzeBtn();

    // Re-enable action buttons
    setLoading(approveBtn, approveSpinner, approveBtnText, false, "✓ Approve & Send");
    setLoading(rejectBtn, rejectSpinner, rejectBtnText, false, "✕ Reject");
}

// ─── Toast Notification ───────────────────────────────────────────────────────
function showToast(message, type = "info") {
    const icons = { success: "✅", error: "❌", info: "ℹ️" };
    toastIcon.textContent = icons[type] || "ℹ️";
    toastMsg.textContent  = message;
    toast.className       = `toast ${type}`;
    toast.classList.remove("hidden");

    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, 5500);
}

function hideToast() {
    toast.classList.add("hidden");
}
