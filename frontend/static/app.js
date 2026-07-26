// ---------------------------------------------------------------------------
// Auth / bootstrap
// ---------------------------------------------------------------------------
const loginScreen = document.getElementById("loginScreen");
const appShell = document.getElementById("appShell");
let currentUser = null;

window.addEventListener("ppe:unauthorized", showLoginScreen);

function showLoginScreen() {
  appShell.hidden = true;
  loginScreen.hidden = false;
  currentUser = null;
  stopAlertPolling();
}

function showApp(user) {
  currentUser = user;
  loginScreen.hidden = true;
  appShell.hidden = false;
  document.getElementById("userName").textContent = user.username;
  document.getElementById("userAvatar").textContent = user.username.slice(0, 1);
  loadDashboard();
  loadSettingsIntoForm();
  checkHealth();
  initAlertSystem();
}

async function bootstrap() {
  try {
    const user = await apiGetJSON("/api/auth/me");
    showApp(user);
  } catch (e) {
    showLoginScreen();
  }
}

document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  const errorEl = document.getElementById("loginError");
  errorEl.hidden = true;
  try {
    const user = await apiPostJSON("/api/auth/login", { username, password });
    showApp(user);
  } catch (err) {
    errorEl.textContent = err.message || "Sign-in failed.";
    errorEl.hidden = false;
  }
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } catch (e) {
    /* ignore */
  }
  stopLiveCamera();
  showLoginScreen();
});

bootstrap();

// Chrome/Safari can restore a fully-rendered page from bfcache on Back/
// Forward without re-running any JS — re-check auth every time the page
// becomes visible again so a signed-out session can never show stale,
// already-authenticated UI.
window.addEventListener("pageshow", (event) => {
  if (event.persisted) bootstrap();
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
const pageTitles = {
  dashboard: "Dashboard",
  live: "Live Camera",
  cctv: "CCTV",
  analyze: "Analyze",
  events: "Events",
  settings: "Settings",
};

function goToView(view) {
  document.querySelectorAll(".nav__item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${view}`));
  document.getElementById("pageTitle").textContent = pageTitles[view] || view;
  closeMobileNav();
  if (view !== "live") stopLiveCamera();
  if (view !== "cctv") stopRtspGrid();
  if (view === "cctv") loadRtspCameraGrid();
  if (view === "events") loadEvents(true);
  if (view === "dashboard") { loadDashboard(); clearAlertBadge(); }
  if (view === "settings") loadCameraManageList();
}

document.querySelectorAll(".nav__item").forEach((btn) => {
  btn.addEventListener("click", () => goToView(btn.dataset.view));
});
document.querySelectorAll("[data-goto]").forEach((btn) => {
  btn.addEventListener("click", () => goToView(btn.dataset.goto));
});

// Mobile nav drawer
const sidebar = document.getElementById("sidebar");
const sidebarScrim = document.getElementById("sidebarScrim");
function openMobileNav() {
  sidebar.classList.add("is-open");
  sidebarScrim.hidden = false;
  sidebarScrim.classList.add("is-open");
}
function closeMobileNav() {
  sidebar.classList.remove("is-open");
  sidebarScrim.classList.remove("is-open");
  sidebarScrim.hidden = true;
}
document.getElementById("mobileNavToggle").addEventListener("click", openMobileNav);
sidebarScrim.addEventListener("click", closeMobileNav);

// ---------------------------------------------------------------------------
// Model health
// ---------------------------------------------------------------------------
async function checkHealth() {
  const dot = document.getElementById("modelDot");
  const text = document.getElementById("modelStatusText");
  dot.classList.remove("ok", "bad");
  try {
    const data = await apiGetJSON("/api/health");
    if (data.model_loaded) {
      dot.classList.add("ok");
      text.textContent = "model ready";
    } else {
      dot.classList.add("bad");
      text.textContent = "model not loaded";
    }
  } catch (e) {
    dot.classList.add("bad");
    text.textContent = "backend unreachable";
  }
}

// ---------------------------------------------------------------------------
// Shared render helpers
// ---------------------------------------------------------------------------
function renderPersonList(listEl, persons, unmatchedItems) {
  listEl.innerHTML = "";
  if (!persons || persons.length === 0) {
    if (unmatchedItems && unmatchedItems.length) {
      const names = unmatchedItems.map((i) => i.label).join(", ");
      listEl.innerHTML = `<li class="person-list__empty">No full person outline detected, but the model found: ${names}. Try a wider shot that includes the whole body.</li>`;
    } else {
      listEl.innerHTML = `<li class="person-list__empty">No persons detected.</li>`;
    }
    return;
  }
  persons.forEach((p, i) => {
    const li = document.createElement("li");
    li.className = `person-card ${p.status}`;
    const missing = p.missing && p.missing.length ? `missing: ${p.missing.join(", ")}` : "";
    li.innerHTML = `
      <div>
        <span class="person-card__id">#${i + 1}</span>
        <span class="person-card__status ${p.status === "secure" ? "secure-text" : "unsecure-text"}">${p.status.toUpperCase()}</span>
      </div>
      <span class="person-card__missing">${missing}</span>
    `;
    listEl.appendChild(li);
  });
}

function setStatRow(prefix, summary) {
  document.getElementById(`${prefix}StatTotal`).textContent = summary.total_persons ?? 0;
  document.getElementById(`${prefix}StatSecure`).textContent = summary.secure ?? 0;
  document.getElementById(`${prefix}StatUnsecure`).textContent = summary.unsecure ?? 0;
}

function timeAgo(isoString) {
  const then = new Date(isoString.replace(" ", "T") + "Z").getTime();
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function eventRowHTML(ev) {
  const thumb = ev.thumbnail_b64
    ? `<img class="event-row__thumb" src="data:image/jpeg;base64,${ev.thumbnail_b64}" alt="" />`
    : `<span class="event-row__thumb event-row__thumb--placeholder">—</span>`;
  const sourceLabel = ev.camera_name ? `${ev.source}: ${ev.camera_name}` : ev.source;
  return `
    <li class="event-row" data-event-id="${ev.id}">
      ${thumb}
      <div class="event-row__body">
        <span class="event-row__counts">
          ${ev.total_persons} person(s) —
          <span class="secure-text">${ev.secure_count} secure</span>,
          <span class="unsecure-text">${ev.unsecure_count} unsecure</span>
        </span>
        <span class="event-row__meta">${timeAgo(ev.created_at)}</span>
      </div>
      <span class="event-row__source">${sourceLabel}</span>
    </li>
  `;
}

// Clicking any event row (dashboard feed or the Events table) opens the
// detail modal — delegated so it keeps working after re-renders.
document.addEventListener("click", (e) => {
  const row = e.target.closest(".event-row[data-event-id]");
  if (row) openEventModal(row.dataset.eventId);
});

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function loadDashboard() {
  try {
    const stats = await apiGetJSON("/api/events/stats?days=7");
    document.getElementById("dashEvents7d").textContent = stats.events ?? 0;
    document.getElementById("dashSecure7d").textContent = stats.secure ?? 0;
    document.getElementById("dashUnsecure7d").textContent = stats.unsecure ?? 0;

    const { events: alerts } = await apiGetJSON("/api/events?unsecure_only=true&limit=5");
    const alertsList = document.getElementById("dashActiveAlerts");
    alertsList.innerHTML = alerts.length
      ? alerts.map(eventRowHTML).join("")
      : `<li class="event-list__empty">No unsecure detections right now.</li>`;

    const { events } = await apiGetJSON("/api/events?limit=5");
    const list = document.getElementById("dashRecentEvents");
    if (!events.length) {
      list.innerHTML = `<li class="event-list__empty">No events logged yet — run a detection to see it here.</li>`;
    } else {
      list.innerHTML = events.map(eventRowHTML).join("");
    }
  } catch (e) {
    /* dashboard is best-effort */
  }
}

// ---------------------------------------------------------------------------
// Events view (filtered report, paginated) — Phase 2
// ---------------------------------------------------------------------------
let eventsOffset = 0;
let eventsTotal = 0;
const EVENTS_PAGE_SIZE = 20;

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function currentFilterParams() {
  const range = document.getElementById("filterDateRange").value;
  const status = document.getElementById("filterStatus").value;
  const source = document.getElementById("filterSource").value;

  let start_date = null;
  let end_date = null;
  const now = new Date();

  if (range === "today") {
    start_date = todayISO();
    end_date = todayISO();
  } else if (range === "week") {
    const d = new Date(now);
    d.setDate(d.getDate() - 7);
    start_date = d.toISOString().slice(0, 10);
    end_date = todayISO();
  } else if (range === "month") {
    const d = new Date(now);
    d.setDate(d.getDate() - 30);
    start_date = d.toISOString().slice(0, 10);
    end_date = todayISO();
  } else if (range === "custom") {
    start_date = document.getElementById("filterStartDate").value || null;
    end_date = document.getElementById("filterEndDate").value || null;
  }

  return { status, source, start_date, end_date };
}

function filterQueryString(extra = {}) {
  const { status, source, start_date, end_date } = currentFilterParams();
  const params = new URLSearchParams({ status, source, ...extra });
  if (start_date) params.set("start_date", start_date);
  if (end_date) params.set("end_date", end_date);
  return params.toString();
}

document.getElementById("filterDateRange").addEventListener("change", (e) => {
  const isCustom = e.target.value === "custom";
  document.getElementById("filterStartWrap").hidden = !isCustom;
  document.getElementById("filterEndWrap").hidden = !isCustom;
});

document.getElementById("filterApply").addEventListener("click", () => loadEvents(true));
document.getElementById("eventsExport").addEventListener("click", () => {
  window.open(`${API_BASE}/api/events/export?${filterQueryString()}`, "_blank");
});

async function loadEvents(reset) {
  if (reset) eventsOffset = 0;
  const table = document.getElementById("eventsTable");
  const countEl = document.getElementById("eventsResultCount");
  const loadMoreBtn = document.getElementById("eventsLoadMore");
  try {
    const qs = filterQueryString({ limit: EVENTS_PAGE_SIZE, offset: eventsOffset });
    const { events, total } = await apiGetJSON(`/api/events/report?${qs}`);
    eventsTotal = total;
    if (reset) table.innerHTML = "";
    if (!events.length && reset) {
      table.innerHTML = `<li class="event-list__empty">No events match these filters.</li>`;
    } else {
      table.insertAdjacentHTML("beforeend", events.map(eventRowHTML).join(""));
    }
    eventsOffset += events.length;
    countEl.textContent = `${eventsOffset} of ${eventsTotal} shown`;
    loadMoreBtn.hidden = eventsOffset >= eventsTotal;
  } catch (e) {
    table.innerHTML = `<li class="event-list__empty">Could not load events.</li>`;
  }
}
document.getElementById("eventsRefresh").addEventListener("click", () => loadEvents(true));
document.getElementById("eventsLoadMore").addEventListener("click", () => loadEvents(false));

// ---------------------------------------------------------------------------
// Dropzone helper
// ---------------------------------------------------------------------------
function setupDropzone(dropzone, input, onFile) {
  dropzone.addEventListener("click", () => input.click());
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("is-dragover"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("is-dragover");
    if (e.dataTransfer.files.length) onFile(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => {
    if (input.files.length) onFile(input.files[0]);
  });
}

// ---------------------------------------------------------------------------
// ANALYZE mode toggle (Image / Video share one page)
// ---------------------------------------------------------------------------
document.querySelectorAll("#analyzeModeToggle [data-mode]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const mode = btn.dataset.mode;
    document.querySelectorAll("#analyzeModeToggle [data-mode]").forEach((b) => {
      const active = b.dataset.mode === mode;
      b.classList.toggle("btn--accent", active);
      b.classList.toggle("btn--ghost", !active);
      b.classList.toggle("is-active", active);
    });
    document.querySelectorAll(".analyze-mode").forEach((panel) => {
      panel.hidden = panel.dataset.modePanel !== mode;
    });
    // Don't let a video keep playing silently in the background once its panel is hidden.
    if (mode !== "video") {
      const vid = document.getElementById("vidResult");
      if (vid && !vid.paused) vid.pause();
    }
  });
});

// ---------------------------------------------------------------------------
// IMAGE view
// ---------------------------------------------------------------------------
const imgDropzone = document.getElementById("imgDropzone");
const imgInput = document.getElementById("imgInput");
const imgViewer = document.getElementById("imgViewer");
const imgResult = document.getElementById("imgResult");

setupDropzone(imgDropzone, imgInput, async (file) => {
  const hintEl = imgDropzone.querySelector(".dropzone__hint");
  const originalHint = hintEl.innerHTML;
  hintEl.innerHTML = "<strong>Analyzing…</strong>";
  const form = new FormData();
  form.append("file", file);
  try {
    const data = await apiFetch("/api/detect/image", { method: "POST", body: form });
    imgResult.src = `data:image/jpeg;base64,${data.annotated_b64}`;
    setStatRow("img", data.summary);
    renderPersonList(document.getElementById("imgPersonList"), data.persons, data.unmatched_items);
    imgDropzone.hidden = true;
    imgViewer.hidden = false;
    loadDashboard();
  } catch (err) {
    alert("Detection failed: " + err.message);
  } finally {
    hintEl.innerHTML = originalHint;
  }
});

document.getElementById("imgReset").addEventListener("click", () => {
  imgViewer.hidden = true;
  imgDropzone.hidden = false;
  imgInput.value = "";
});

// ---------------------------------------------------------------------------
// VIDEO view
// ---------------------------------------------------------------------------
const vidDropzone = document.getElementById("vidDropzone");
const vidInput = document.getElementById("vidInput");
const vidViewer = document.getElementById("vidViewer");
const vidResult = document.getElementById("vidResult");
const vidProgressFill = document.getElementById("vidProgressFill");
const vidProgressText = document.getElementById("vidProgressText");
const vidActions = document.getElementById("vidActions");
const vidDownload = document.getElementById("vidDownload");

setupDropzone(vidDropzone, vidInput, async (file) => {
  vidDropzone.hidden = true;
  vidViewer.hidden = false;
  vidResult.hidden = true;
  vidActions.hidden = true;
  vidProgressFill.style.width = "0%";
  vidProgressText.textContent = "Uploading…";

  const form = new FormData();
  form.append("file", file);
  try {
    const { job_id } = await apiFetch("/api/detect/video", { method: "POST", body: form });
    pollVideoJob(job_id);
  } catch (err) {
    vidProgressText.textContent = "Upload failed: " + err.message;
  }
});

function pollVideoJob(jobId) {
  const interval = setInterval(async () => {
    try {
      const job = await apiGetJSON(`/api/jobs/${jobId}`);
      const progress = job.progress ?? 0;
      vidProgressFill.style.width = `${progress}%`;

      if (job.status === "processing" || job.status === "queued") {
        vidProgressText.textContent = `Processing… ${progress}%`;
      } else if (job.status === "done") {
        clearInterval(interval);
        vidProgressFill.style.width = "100%";
        vidProgressText.textContent = "Done.";
        vidResult.src = `${API_BASE}/api/download/${jobId}`;
        vidResult.hidden = false;
        vidDownload.href = `${API_BASE}/api/download/${jobId}`;
        vidActions.hidden = false;
        if (job.summary) {
          setStatRow("vid", {
            total_persons: job.summary.peak_secure + job.summary.peak_unsecure,
            secure: job.summary.peak_secure,
            unsecure: job.summary.peak_unsecure,
          });
        }
        loadDashboard();
      } else if (job.status === "error") {
        clearInterval(interval);
        vidProgressText.textContent = "Error: " + job.error;
      }
    } catch (err) {
      clearInterval(interval);
      vidProgressText.textContent = "Lost connection to job.";
    }
  }, 1000);
}

document.getElementById("vidReset").addEventListener("click", () => {
  vidViewer.hidden = true;
  vidDropzone.hidden = false;
  vidInput.value = "";
});

// ---------------------------------------------------------------------------
// LIVE view
// ---------------------------------------------------------------------------
const liveVideo = document.getElementById("liveVideo");
const liveCanvas = document.getElementById("liveCanvas");
const liveIdle = document.getElementById("liveIdle");
const liveControls = document.getElementById("liveControls");
const liveFps = document.getElementById("liveFps");
const liveRecDot = document.getElementById("liveRecDot");
const liveCtx = liveCanvas.getContext("2d");

let liveStream = null;
let liveWs = null;
let liveLoopHandle = null;
let liveBusy = false;
const captureCanvas = document.createElement("canvas");
const captureCtx = captureCanvas.getContext("2d");

async function startLiveCamera() {
  try {
    liveStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
  } catch (err) {
    alert("Could not access webcam: " + err.message);
    return;
  }
  liveVideo.srcObject = liveStream;
  await liveVideo.play();

  liveCanvas.width = liveVideo.videoWidth || 640;
  liveCanvas.height = liveVideo.videoHeight || 480;
  captureCanvas.width = liveCanvas.width;
  captureCanvas.height = liveCanvas.height;

  liveIdle.hidden = true;
  liveControls.hidden = false;
  liveRecDot.classList.add("is-live");

  const wsProto = window.location.protocol === "https:" ? "wss" : "ws";
  liveWs = new WebSocket(`${wsProto}://${window.location.host}/ws/live`);
  liveWs.onopen = () => sendNextFrame();
  liveWs.onmessage = (event) => {
    const data = JSON.parse(event.data);
    const img = new Image();
    img.onload = () => liveCtx.drawImage(img, 0, 0, liveCanvas.width, liveCanvas.height);
    img.src = `data:image/jpeg;base64,${data.annotated_b64}`;
    setStatRow("live", data.summary);
    renderPersonList(document.getElementById("livePersonList"), data.persons, data.unmatched_items);
    liveFps.textContent = `${data.inference_ms} ms/frame`;
    liveBusy = false;
  };
  liveWs.onclose = () => { liveBusy = false; };
  liveWs.onerror = () => { liveBusy = false; };
}

function sendNextFrame() {
  liveLoopHandle = requestAnimationFrame(sendNextFrame);
  if (liveBusy || !liveWs || liveWs.readyState !== WebSocket.OPEN) return;
  if (!liveVideo.videoWidth) return;
  liveBusy = true;
  captureCtx.drawImage(liveVideo, 0, 0, captureCanvas.width, captureCanvas.height);
  const b64 = captureCanvas.toDataURL("image/jpeg", 0.7).split(",")[1];
  liveWs.send(b64);
}

function stopLiveCamera() {
  if (liveLoopHandle) cancelAnimationFrame(liveLoopHandle);
  if (liveWs) { liveWs.close(); liveWs = null; }
  if (liveStream) { liveStream.getTracks().forEach((t) => t.stop()); liveStream = null; }
  liveIdle.hidden = false;
  liveControls.hidden = true;
  liveRecDot.classList.remove("is-live");
  liveCtx.clearRect(0, 0, liveCanvas.width, liveCanvas.height);
  liveFps.textContent = "-- ms/frame";
}

document.getElementById("liveStart").addEventListener("click", startLiveCamera);
document.getElementById("liveStop").addEventListener("click", stopLiveCamera);

// ---------------------------------------------------------------------------
// SETTINGS view
// ---------------------------------------------------------------------------
async function loadSettingsIntoForm() {
  try {
    const settings = await apiGetJSON("/api/settings");
    document.getElementById("settingSiteName").value = settings.site_name || "";
    const conf = parseFloat(settings.confidence_threshold || "0.35");
    document.getElementById("settingConfThreshold").value = conf;
    document.getElementById("confThresholdVal").textContent = conf.toFixed(2);
    document.getElementById("settingFrameSkip").value = settings.video_frame_skip || "2";
    document.getElementById("settingRetention").value = settings.event_retention_days || "30";
    document.getElementById("settingAlertsEnabled").checked = settings.alerts_enabled !== "false";
    document.getElementById("settingAlertSound").checked = localStorage.getItem(ALERT_SOUND_KEY) === "true";

    if (!localStorage.getItem(THEME_STORAGE_KEY) && settings.theme_default) {
      setThemePref(settings.theme_default);
    } else {
      document.getElementById("settingTheme").value = getThemePref();
    }
  } catch (e) {
    /* best-effort */
  }
}

document.getElementById("settingConfThreshold").addEventListener("input", (e) => {
  document.getElementById("confThresholdVal").textContent = parseFloat(e.target.value).toFixed(2);
});

document.getElementById("settingTheme").addEventListener("change", (e) => {
  setThemePref(e.target.value);
});

document.getElementById("settingAlertSound").addEventListener("change", (e) => {
  localStorage.setItem(ALERT_SOUND_KEY, e.target.checked ? "true" : "false");
});

document.getElementById("settingsSave").addEventListener("click", async () => {
  const payload = {
    site_name: document.getElementById("settingSiteName").value,
    confidence_threshold: document.getElementById("settingConfThreshold").value,
    video_frame_skip: document.getElementById("settingFrameSkip").value,
    event_retention_days: document.getElementById("settingRetention").value,
    alerts_enabled: document.getElementById("settingAlertsEnabled").checked ? "true" : "false",
    theme_default: getThemePref(),
  };
  try {
    await apiPostJSON("/api/settings", payload);
    alertsEnabled = payload.alerts_enabled === "true";
    if (alertsEnabled && !alertPollHandle) {
      alertPollHandle = setInterval(pollForAlerts, ALERT_POLL_INTERVAL_MS);
      pollForAlerts();
    } else if (!alertsEnabled) {
      stopAlertPolling();
    }
    const confirmEl = document.getElementById("settingsSaveConfirm");
    confirmEl.hidden = false;
    setTimeout(() => { confirmEl.hidden = true; }, 2500);
  } catch (err) {
    alert("Could not save settings: " + err.message);
  }
});

document.getElementById("pwSave").addEventListener("click", async () => {
  const errorEl = document.getElementById("pwError");
  errorEl.hidden = true;
  const old_password = document.getElementById("pwOld").value;
  const new_password = document.getElementById("pwNew").value;
  try {
    await apiPostJSON("/api/auth/change-password", { old_password, new_password });
    document.getElementById("pwOld").value = "";
    document.getElementById("pwNew").value = "";
    errorEl.hidden = false;
    errorEl.style.color = "var(--secure)";
    errorEl.textContent = "Password changed.";
  } catch (err) {
    errorEl.hidden = false;
    errorEl.style.color = "var(--unsecure)";
    errorEl.textContent = err.message || "Could not change password.";
  }
});

// ---------------------------------------------------------------------------
// Event detail modal
// ---------------------------------------------------------------------------
const eventModal = document.getElementById("eventModal");
const eventModalImage = document.getElementById("eventModalImage");
const eventModalCaptures = document.getElementById("eventModalCaptures");
const eventModalTitle = document.getElementById("eventModalTitle");
const eventModalMeta = document.getElementById("eventModalMeta");

async function openEventModal(eventId) {
  eventModal.hidden = false;
  eventModalTitle.textContent = `Event #${eventId}`;
  eventModalMeta.textContent = "Loading…";
  eventModalImage.removeAttribute("src");
  eventModalCaptures.innerHTML = `<li class="person-list__empty">Loading…</li>`;

  try {
    const ev = await apiGetJSON(`/api/events/${eventId}`);
    eventModalMeta.textContent = `${ev.source} · ${timeAgo(ev.created_at)}`;
    document.getElementById("eventModalTotal").textContent = ev.total_persons;
    document.getElementById("eventModalSecure").textContent = ev.secure_count;
    document.getElementById("eventModalUnsecure").textContent = ev.unsecure_count;

    if (ev.full_image_b64) {
      eventModalImage.src = `data:image/jpeg;base64,${ev.full_image_b64}`;
    } else if (ev.thumbnail_b64) {
      eventModalImage.src = `data:image/jpeg;base64,${ev.thumbnail_b64}`;
    }

    const unsecureCaptures = (ev.persons || []).filter((p) => p.status === "unsecure");
    if (!unsecureCaptures.length) {
      eventModalCaptures.innerHTML = `<li class="person-list__empty">No unsecure persons in this event.</li>`;
    } else {
      eventModalCaptures.innerHTML = unsecureCaptures
        .map((p) => {
          const img = p.crop_b64
            ? `<img class="capture-card__img" src="data:image/jpeg;base64,${p.crop_b64}" alt="" />`
            : `<span class="capture-card__img"></span>`;
          const missing = p.missing && p.missing.length ? p.missing.join(", ") : "unknown";
          return `
            <li class="capture-card">
              ${img}
              <div class="capture-card__body">
                <span class="capture-card__missing">Missing: ${missing}</span>
                <span class="capture-card__conf">confidence ${p.confidence}</span>
              </div>
            </li>
          `;
        })
        .join("");
    }
  } catch (err) {
    eventModalMeta.textContent = "Could not load this event.";
    eventModalCaptures.innerHTML = `<li class="person-list__empty">${err.message}</li>`;
  }
}

function closeEventModal() {
  eventModal.hidden = true;
}

document.getElementById("eventModalClose").addEventListener("click", closeEventModal);
eventModal.addEventListener("click", (e) => {
  if (e.target === eventModal) closeEventModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !eventModal.hidden) closeEventModal();
});

// ---------------------------------------------------------------------------
// Alerts: polling, toasts, badge, sound
// ---------------------------------------------------------------------------
const ALERT_SOUND_KEY = "ppe_alert_sound";
const LAST_SEEN_EVENT_KEY = "ppe_last_seen_event_id";
const ALERT_POLL_INTERVAL_MS = 10000;

let alertsEnabled = true;
let lastSeenEventId = 0;
let unreadAlertCount = 0;
let alertPollHandle = null;

function getLastSeenEventId() {
  return parseInt(localStorage.getItem(LAST_SEEN_EVENT_KEY) || "0", 10);
}
function setLastSeenEventId(id) {
  lastSeenEventId = id;
  localStorage.setItem(LAST_SEEN_EVENT_KEY, String(id));
}

async function initAlertSystem() {
  try {
    const settings = await apiGetJSON("/api/settings");
    alertsEnabled = settings.alerts_enabled !== "false";
  } catch (e) {
    alertsEnabled = true;
  }

  lastSeenEventId = getLastSeenEventId();
  if (!lastSeenEventId) {
    // First time in this browser — don't flood alerts for old history,
    // just start watching from whatever the latest event is right now.
    try {
      const { events } = await apiGetJSON("/api/events?limit=1");
      setLastSeenEventId(events.length ? events[0].id : 0);
    } catch (e) {
      /* ignore */
    }
  }

  stopAlertPolling();
  if (alertsEnabled) {
    alertPollHandle = setInterval(pollForAlerts, ALERT_POLL_INTERVAL_MS);
    pollForAlerts();
  }
}

function stopAlertPolling() {
  if (alertPollHandle) {
    clearInterval(alertPollHandle);
    alertPollHandle = null;
  }
}

async function pollForAlerts() {
  if (!alertsEnabled || !currentUser) return;
  try {
    const { events } = await apiGetJSON(`/api/alerts/poll?since_id=${lastSeenEventId}`);
    if (!events.length) return;

    events.forEach((ev) => showAlertToast(ev));
    setLastSeenEventId(events[events.length - 1].id);

    const dashboardActive = document.getElementById("view-dashboard").classList.contains("is-active");
    if (dashboardActive) {
      loadDashboard();
    } else {
      unreadAlertCount += events.length;
      updateAlertBadge();
    }
    if (document.getElementById("settingAlertSound").checked || localStorage.getItem(ALERT_SOUND_KEY) === "true") {
      playAlertBeep();
    }
  } catch (e) {
    /* polling is best-effort — a failed check just tries again next cycle */
  }
}

function updateAlertBadge() {
  const badge = document.getElementById("dashboardBadge");
  if (unreadAlertCount > 0) {
    badge.textContent = unreadAlertCount > 99 ? "99+" : String(unreadAlertCount);
    badge.hidden = false;
  } else {
    badge.hidden = true;
  }
}

function clearAlertBadge() {
  unreadAlertCount = 0;
  updateAlertBadge();
}

function getToastStack() {
  let stack = document.querySelector(".toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.className = "toast-stack";
    document.body.appendChild(stack);
  }
  return stack;
}

function showAlertToast(ev) {
  const stack = getToastStack();
  const toast = document.createElement("div");
  toast.className = "toast";
  const thumb = ev.thumbnail_b64
    ? `<img class="toast__thumb" src="data:image/jpeg;base64,${ev.thumbnail_b64}" alt="" />`
    : "";
  toast.innerHTML = `
    ${thumb}
    <div class="toast__body">
      <span class="toast__title">${ev.unsecure_count} unsecure person(s) detected</span>
      <span class="toast__meta">${ev.source} · just now</span>
    </div>
  `;
  toast.addEventListener("click", () => {
    openEventModal(ev.id);
    toast.remove();
  });
  stack.appendChild(toast);
  setTimeout(() => toast.remove(), 6000);
}

function playAlertBeep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.4);
  } catch (e) {
    /* audio not available — ignore */
  }
}

// ---------------------------------------------------------------------------
// Cameras (RTSP) — Phase 3
// ---------------------------------------------------------------------------
function cameraStatusLabel(cam) {
  if (!cam.enabled) return "disabled";
  if (cam.status === "running") return "live";
  if (cam.status === "starting") return "connecting…";
  if (cam.status === "error") return cam.last_error || "error";
  return cam.status || "stopped";
}

// --- Settings → Cameras management list ---
async function loadCameraManageList() {
  const list = document.getElementById("cameraManageList");
  try {
    const { cameras } = await apiGetJSON("/api/cameras");
    if (!cameras.length) {
      list.innerHTML = `<li class="side-panel__note">No cameras added yet.</li>`;
      return;
    }
    list.innerHTML = cameras.map((cam) => {
      const statusClass = !cam.enabled ? "" : cam.status === "running" ? "running" : cam.status === "error" ? "error" : "";
      return `
        <li class="camera-manage-row" data-camera-id="${cam.id}">
          <span class="camera-manage-row__status ${statusClass}"></span>
          <div class="camera-manage-row__body">
            <span class="camera-manage-row__name">${cam.name}</span>
            <span class="camera-manage-row__url">${cam.rtsp_url} · ${cameraStatusLabel(cam)}</span>
          </div>
          <div class="camera-manage-row__actions">
            <button data-action="toggle" data-enabled="${cam.enabled ? 1 : 0}">${cam.enabled ? "Disable" : "Enable"}</button>
            <button data-action="edit">Edit</button>
            <button data-action="delete" class="danger">Delete</button>
          </div>
        </li>
      `;
    }).join("");
  } catch (e) {
    list.innerHTML = `<li class="side-panel__note">Could not load cameras.</li>`;
  }
}

document.getElementById("cameraManageList").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const row = btn.closest(".camera-manage-row");
  const id = row.dataset.cameraId;
  const errorEl = document.getElementById("cameraError");
  errorEl.hidden = true;

  try {
    if (btn.dataset.action === "toggle") {
      const currentlyEnabled = btn.dataset.enabled === "1";
      await apiFetch(`/api/cameras/${id}`, { method: "PUT", body: JSON.stringify({ enabled: !currentlyEnabled }) });
    } else if (btn.dataset.action === "delete") {
      if (!confirm("Remove this camera? This stops its stream and detection immediately.")) return;
      await apiFetch(`/api/cameras/${id}`, { method: "DELETE" });
    } else if (btn.dataset.action === "edit") {
      const nameEl = row.querySelector(".camera-manage-row__name");
      const currentName = nameEl.textContent;
      const currentUrl = row.querySelector(".camera-manage-row__url").textContent.split(" · ")[0];
      const newName = prompt("Camera name:", currentName);
      if (newName === null) return;
      const newUrl = prompt("RTSP URL:", currentUrl);
      if (newUrl === null) return;
      await apiFetch(`/api/cameras/${id}`, { method: "PUT", body: JSON.stringify({ name: newName, rtsp_url: newUrl }) });
    }
    await loadCameraManageList();
    await loadRtspCameraGrid();
  } catch (err) {
    errorEl.textContent = err.message || "Camera action failed.";
    errorEl.hidden = false;
  }
});

document.getElementById("cameraAddBtn").addEventListener("click", async () => {
  const nameInput = document.getElementById("newCameraName");
  const urlInput = document.getElementById("newCameraUrl");
  const errorEl = document.getElementById("cameraError");
  errorEl.hidden = true;

  const name = nameInput.value.trim();
  const rtsp_url = urlInput.value.trim();
  if (!name || !rtsp_url) {
    errorEl.textContent = "Enter both a name and an RTSP URL.";
    errorEl.hidden = false;
    return;
  }

  try {
    await apiPostJSON("/api/cameras", { name, rtsp_url, enabled: true });
    nameInput.value = "";
    urlInput.value = "";
    await loadCameraManageList();
    await loadRtspCameraGrid();
  } catch (err) {
    errorEl.textContent = err.message || "Could not add camera.";
    errorEl.hidden = false;
  }
});

// --- Live Camera page → RTSP tile grid ---
function cameraTileHTML(cam) {
  const isLive = cam.enabled && (cam.status === "running" || cam.status === "starting");
  const statusText = cameraStatusLabel(cam);
  const body = isLive
    ? `<img class="mjpeg-frame" src="/api/cameras/${cam.id}/stream?_=${Date.now()}" alt="${cam.name}" />`
    : `<div class="camera-placeholder"><span>${statusText}</span></div>`;
  return `
    <div class="camera-tile" data-camera-id="${cam.id}">
      <div class="camera-tile__header">
        <span class="camera-tile__name">
          <span class="rec-dot ${cam.status === 'running' ? 'is-live' : ''}"></span>
          ${cam.name}
        </span>
        <span class="fps-readout">${statusText}</span>
      </div>
      <div class="camera-tile__body">${body}</div>
    </div>
  `;
}

async function loadRtspCameraGrid() {
  const grid = document.getElementById("rtspCameraGrid");
  try {
    const { cameras } = await apiGetJSON("/api/cameras");
    if (!cameras.length) {
      grid.classList.remove("has-focus");
      grid.innerHTML = `<p class="side-panel__note">No RTSP cameras configured yet — add one from Settings → Cameras.</p>`;
      return;
    }
    grid.innerHTML = cameras.map(cameraTileHTML).join("");
    applyFocusState(grid);
  } catch (e) {
    grid.innerHTML = `<p class="side-panel__note">Could not load cameras.</p>`;
  }
}

// Click a CCTV tile to zoom it in (full-width) with the rest shrunk to a
// thumbnail strip, like a monitor wall — click it again to go back to the
// even grid. focusedCameraId persists across grid reloads (e.g. after
// adding/editing a camera in Settings) so the zoomed tile doesn't reset.
let focusedCameraId = null;

document.getElementById("rtspCameraGrid").addEventListener("click", (e) => {
  const tile = e.target.closest(".camera-tile[data-camera-id]");
  if (!tile) return;
  const grid = document.getElementById("rtspCameraGrid");
  const clickedId = tile.dataset.cameraId;

  focusedCameraId = focusedCameraId === clickedId ? null : clickedId;
  applyFocusState(grid);
});

function applyFocusState(grid) {
  // If the previously-focused camera no longer exists (e.g. deleted from
  // Settings), fall back to the plain grid instead of leaving it in
  // thumbnail-strip layout with nothing zoomed in.
  if (focusedCameraId && !grid.querySelector(`.camera-tile[data-camera-id="${focusedCameraId}"]`)) {
    focusedCameraId = null;
  }
  const hasFocus = focusedCameraId !== null;
  grid.classList.toggle("has-focus", hasFocus);
  grid.querySelectorAll(".camera-tile[data-camera-id]").forEach((tile) => {
    tile.classList.toggle("is-focused", tile.dataset.cameraId === focusedCameraId);
  });
}

function stopRtspGrid() {
  // Clearing the tiles drops the <img> elements, which aborts the
  // in-flight MJPEG connections — otherwise they'd keep streaming in the
  // background (using bandwidth/CPU) even after leaving this tab, since
  // switching views only hides the section rather than removing it.
  const grid = document.getElementById("rtspCameraGrid");
  if (grid) grid.innerHTML = "";
}
