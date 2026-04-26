// affectra frontend — splash checks, scan form, results pagination, dev menu

(function () {
  "use strict";

  // dom refs
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const splash = $("#splash");
  const splashChecks = $("#splash-checks");
  const splashBar = $("#splash-progress-bar");
  const splashFootnote = $("#splash-footnote");
  const splashContinue = $("#splash-continue");

  const form = $("#scan-form");
  const submitBtn = $("#submit-btn");
  const formError = $("#form-error");
  const resultsCard = $("#results");
  const resultsMeta = $("#results-meta");
  const summaryPills = $("#summary-pills");
  const exposureList = $("#exposure-list");
  const emptyState = $("#empty-state");
  const comparisonBlock = $("#comparison-block");
  const exposureToolbar = $("#exposure-toolbar");
  const exposureCount = $("#exposure-count");
  const pageSizeSelect = $("#page-size");
  const expandAllBtn = $("#expand-all");
  const collapseAllBtn = $("#collapse-all");
  const pagination = $("#pagination");

  const aiSummary = $("#ai-summary");

  const systemGrid = $("#system-grid");

  // Settings (was: floating Dev Menu)
  const devDrawer    = $("#devmenu");
  const devStatus    = $("#devmenu-status");
  const themePicker  = $("#theme-picker");
  const serviceToggles = $("#service-toggles");
  const keyEditors   = $("#key-editors");
  const flagStrictStack    = $("#flag-strict-stack");
  const flagStrictGithub   = $("#flag-strict-github");
  const flagPerServiceCap  = $("#flag-per-service-cap");

  // state
  let currentExposures = [];
  let currentPage = 1;
  let pageSize = 10;
  let expandedByDefault = false;
  let devConfig = null;        // cached /api/config snapshot
  let currentAiAnalysis = null; // {per_finding:{id:str}, overall_summary:str} | null
  let aiAnalysisLoading = false;
  let currentScanData = null;  // last full scan response — used by evaluation page

  // ── Mitigation Tracker ────────────────────────────────────────────────────
  // Persists per-finding action status in localStorage across page reloads.
  // States cycle: todo → in_progress → done → todo
  const MitigationTracker = (() => {
    const STATES  = ["todo", "in_progress", "done"];
    const LABELS  = { todo: "To-Do", in_progress: "In Progress", done: "Done" };
    const ICONS   = { todo: "○", in_progress: "◑", done: "●" };
    const _key    = (id) => `affectra_mt_${id}`;

    return {
      get(id)  { return localStorage.getItem(_key(id)) || "todo"; },
      next(id) {
        const curr = this.get(id);
        const nxt  = STATES[(STATES.indexOf(curr) + 1) % STATES.length];
        localStorage.setItem(_key(id), nxt);
        return nxt;
      },
      label(id) { return LABELS[this.get(id)]; },
      icon(id)  { return ICONS[this.get(id)];  },
      state(id) { return this.get(id); },
      LABELS,
      ICONS,
    };
  })();

  // ── Scan History — API-backed, stored in backend/data/History.json ────────
  const ScanHistory = (() => {
    let _cache = [];   // in-memory mirror of server data

    const _api = async (path, opts = {}) => {
      const r = await fetch(`/api/history${path}`, {
        headers: { "Content-Type": "application/json" },
        ...opts,
      });
      if (!r.ok) throw new Error(`History API ${r.status}`);
      return r.json();
    };

    return {
      // Load all scans from the server into the local cache
      async load() {
        try {
          const data = await _api("");
          _cache = data.scans || [];
        } catch { _cache = []; }
        return _cache;
      },

      // Synchronous cache read — always call load() first
      all() { return _cache; },

      // Save a new scan entry to the server
      async add(scanData, query) {
        const entry = {
          id:        String(Date.now()),
          timestamp: new Date().toISOString(),
          query: {
            email:     query.email     || "",
            full_name: query.full_name || "",
            phone:     query.phone     || "",
            usernames: Array.isArray(query.usernames)
              ? query.usernames.join(", ")
              : (query.usernames || ""),
            mode:      query.mode      || "HYBRID",
          },
          summary:  scanData.summary       || {},
          metadata: scanData.scan_metadata || {},
          results:  (scanData.results || []).slice(0, 60),
        };
        try {
          await _api("", { method: "POST", body: JSON.stringify(entry) });
          _cache.unshift(entry);
        } catch {}
      },

      async remove(id) {
        try {
          await _api(`/${id}`, { method: "DELETE" });
          _cache = _cache.filter((s) => s.id !== id);
        } catch {}
      },

      async clear() {
        try {
          await _api("", { method: "DELETE" });
          _cache = [];
        } catch {}
      },
    };
  })();

  // helpers

  function setCheckState(key, state, status) {
    const li = splashChecks.querySelector(`[data-check="${key}"]`);
    if (!li) return;
    li.classList.remove("pending", "running", "ok", "fail", "warn");
    li.classList.add(state);
    if (status !== undefined) {
      const s = li.querySelector(".sc-status");
      if (s) s.textContent = status;
    }
  }

  function setProgress(pct) {
    splashBar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function escHtml(s) {
    return String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[c])
    );
  }

  function fmtMs(ms) {
    if (ms === undefined || ms === null) return "—";
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(2)} s`;
  }

  function titleCase(s) {
    return String(s || "")
      .replace(/_/g, " ")
      .replace(/\b([a-z])/g, (_, c) => c.toUpperCase());
  }

  // splash boot

  async function runSplashBoot() {
    splashFootnote.textContent = "Verifying core assets…";
    setCheckState("core", "running");
    setProgress(5);

    const coreOk = await verifyCoreFiles();
    setCheckState(
      "core",
      coreOk ? "ok" : "fail",
      coreOk ? "ready" : "missing"
    );
    setProgress(18);
    await sleep(120);

    setCheckState("backend", "running");
    splashFootnote.textContent = "Contacting Affectra backend…";
    let sys = null;
    let backendOk = false;
    try {
      const r = await fetch("/api/status/system");
      backendOk = r.ok;
      if (r.ok) sys = await r.json();
    } catch (err) {
      backendOk = false;
    }
    setCheckState(
      "backend",
      backendOk ? "ok" : "fail",
      backendOk ? "online" : "unreachable"
    );
    setProgress(36);
    await sleep(120);

    if (!backendOk || !sys) {
      ["keys", "external", "internal", "scanner"].forEach((k) =>
        setCheckState(k, "fail", "unreachable")
      );
      setProgress(100);
      splashFootnote.textContent =
        "Backend unreachable. Start the server and reload.";
      startContinueCountdown(5, "Continue anyway");
      return;
    }

    setCheckState("keys", "running");
    splashFootnote.textContent = "Loading API keys…";
    const keys = sys.checks.keys || {};
    const keyState =
      keys.configured === keys.total
        ? "ok"
        : keys.configured > 0
        ? "warn"
        : "warn";
    setCheckState(
      "keys",
      keyState,
      `${keys.configured || 0} / ${keys.total || 0}`
    );
    setProgress(54);
    await sleep(120);

    setCheckState("external", "running");
    splashFootnote.textContent = "Reaching external APIs…";
    const ext = sys.checks.external || {};
    const extState =
      ext.ready === ext.total ? "ok" : ext.ready > 0 ? "warn" : "fail";
    setCheckState(
      "external",
      extState,
      `${ext.ready || 0} / ${ext.total || 0}`
    );
    setProgress(72);
    await sleep(120);

    setCheckState("internal", "running");
    splashFootnote.textContent = "Booting internal API modules…";
    const internal = sys.checks.internal || {};
    const intState = internal.ok ? "ok" : "fail";
    setCheckState(
      "internal",
      intState,
      `${internal.ready || 0} / ${internal.total || 0}`
    );
    setProgress(88);
    await sleep(120);

    setCheckState("scanner", "running");
    splashFootnote.textContent = "Initializing scanner engine…";
    const scanner = sys.checks.scanner || {};
    setCheckState(
      "scanner",
      scanner.ok ? "ok" : "fail",
      scanner.ok ? "ready" : "error"
    );
    setProgress(100);
    await sleep(200);

    const allOk =
      coreOk &&
      backendOk &&
      internal.ok &&
      scanner.ok &&
      (ext.ready || 0) >= 1;
    splashFootnote.textContent = allOk
      ? "All systems ready."
      : "Some services unavailable — you can still run scans with reduced coverage.";
    startContinueCountdown(5);

    renderSystemStatus(sys);
  }

  async function verifyCoreFiles() {
    try {
      const r = await fetch("/static/styles.css", { method: "HEAD" });
      return r.ok;
    } catch (err) {
      return false;
    }
  }

  let _splashCountdown = null;

  // Show the continue button and count down from `secs`.
  // Auto-dismisses when it reaches 0; clicking the button also dismisses.
  function startContinueCountdown(secs, label) {
    label = label || "Continue";
    let remaining = secs;
    splashContinue.classList.remove("hidden");
    splashContinue.textContent = label + " (" + remaining + ")";
    _splashCountdown = setInterval(function () {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(_splashCountdown);
        _splashCountdown = null;
        dismissSplash();
      } else {
        splashContinue.textContent = label + " (" + remaining + ")";
      }
    }, 1000);
  }

  function dismissSplash() {
    if (_splashCountdown) {
      clearInterval(_splashCountdown);
      _splashCountdown = null;
    }
    splash.classList.add("dismissing");
    setTimeout(() => {
      splash.style.display = "none";
    }, 300);
  }

  splashContinue.addEventListener("click", dismissSplash);

  // system status card

  function renderSystemStatus(sys) {
    if (!sys || !sys.checks) {
      systemGrid.innerHTML =
        '<p class="muted small">System status unavailable.</p>';
      return;
    }
    const c = sys.checks;
    const tiles = [
      tile(
        "Backend",
        c.backend.ok ? "online" : "offline",
        c.backend.detail || "",
        c.backend.ok ? "ok" : "fail"
      ),
      tile(
        "API keys",
        `${c.keys.configured} / ${c.keys.total}`,
        c.keys.detail || "",
        c.keys.configured === c.keys.total
          ? "ok"
          : c.keys.configured > 0
          ? "warn"
          : "warn"
      ),
      tile(
        "External APIs",
        `${c.external.ready} / ${c.external.total}`,
        c.external.detail || "",
        c.external.ok ? "ok" : c.external.ready > 0 ? "warn" : "fail"
      ),
      tile(
        "Internal modules",
        `${c.internal.ready} / ${c.internal.total}`,
        c.internal.detail || "",
        c.internal.ok ? "ok" : "fail"
      ),
      tile(
        "Scanner engine",
        c.scanner.ok ? "ready" : "error",
        c.scanner.detail || "",
        c.scanner.ok ? "ok" : "fail"
      ),
    ];
    systemGrid.innerHTML = tiles.join("");
  }

  function tile(label, value, detail, state) {
    return `
      <div class="sys-tile ${escHtml(state)}">
        <p class="st-title">${escHtml(label)}</p>
        <p class="st-value">${escHtml(value)}</p>
        <p class="st-detail">${escHtml(detail)}</p>
      </div>`;
  }

  // scan form

  function readForm() {
    const fd = new FormData(form);
    const email = (fd.get("email") || "").toString().trim();
    const full_name = (fd.get("full_name") || "").toString().trim();
    const phone = (fd.get("phone") || "").toString().trim();
    const rawUsers = (fd.get("usernames") || "").toString().trim();
    const usernames = rawUsers
      ? rawUsers
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : [];
    const mode = (fd.get("scan_mode") || "HYBRID").toString();
    return { email, full_name, phone, usernames, mode };
  }

  function buildPayload(v) {
    const p = { scan_mode: v.mode === "COMPARE" ? "HYBRID" : v.mode };
    if (v.email) p.email = v.email;
    if (v.full_name) p.full_name = v.full_name;
    if (v.phone) p.phone = v.phone;
    if (v.usernames.length) p.usernames = v.usernames;
    return p;
  }

  // ── consent popup ──────────────────────────────────────────────────────────
  // Returns a Promise<boolean> — true if the user confirmed, false if cancelled.
  function askConsent() {
    return new Promise((resolve) => {
      const overlay    = document.getElementById("consent-overlay");
      const confirmBtn = document.getElementById("consent-confirm");
      const cancelBtn  = document.getElementById("consent-cancel");

      function done(result) {
        overlay.classList.add("hidden");
        confirmBtn.removeEventListener("click", onConfirm);
        cancelBtn.removeEventListener("click", onCancel);
        overlay.removeEventListener("click", onBackdrop);
        resolve(result);
      }

      function onConfirm()       { done(true);  }
      function onCancel()        { done(false); }
      function onBackdrop(e)     { if (e.target === overlay) done(false); }

      overlay.classList.remove("hidden");
      confirmBtn.addEventListener("click", onConfirm);
      cancelBtn.addEventListener("click",  onCancel);
      overlay.addEventListener("click",    onBackdrop);
      // move focus into the modal for keyboard / accessibility
      confirmBtn.focus();
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    formError.textContent = "";
    const v = readForm();

    if (!v.email && !v.full_name && !v.phone && !v.usernames.length) {
      formError.textContent = "Provide at least one identifier.";
      return;
    }

    // gate 1: CAPTCHA must be solved
    const hcaptchaToken = (typeof hcaptcha !== "undefined")
      ? hcaptcha.getResponse()
      : "";
    if (!hcaptchaToken) {
      formError.textContent = "Please complete the CAPTCHA before running a scan.";
      return;
    }

    // gate 2: user must confirm the data is their own before we scan
    const confirmed = await askConsent();
    if (!confirmed) return;

    submitBtn.disabled = true;
    submitBtn.classList.add("loading");
    submitBtn.textContent = "Scanning…";
    form.closest(".scan-card").classList.add("busy");

    try {
      if (v.mode === "COMPARE") {
        const body = { ...buildPayload(v), hcaptcha_token: hcaptchaToken };
        const r = await fetch("/api/scan/compare", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw await errorFrom(r);
        const data = await r.json();
        renderCompare(data);
      } else {
        const body = { ...buildPayload(v), hcaptcha_token: hcaptchaToken };
        const r = await fetch("/api/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw await errorFrom(r);
        const data = await r.json();
        renderScan(data);
        ScanHistory.add(data, v).catch(() => {});  // persist to backend history
      }
    } catch (err) {
      formError.textContent = err && err.message ? err.message : String(err);
    } finally {
      // always reset the CAPTCHA so the user must solve it again for the next scan
      if (typeof hcaptcha !== "undefined") hcaptcha.reset();
      submitBtn.disabled = false;
      submitBtn.classList.remove("loading");
      submitBtn.textContent = "Run scan";
      form.closest(".scan-card").classList.remove("busy");
    }
  });

  async function errorFrom(resp) {
    try {
      const j = await resp.json();
      return new Error(j.detail || `Request failed (${resp.status})`);
    } catch {
      return new Error(`Request failed (${resp.status})`);
    }
  }

  // results + pagination

  function renderScan(data) {
    currentScanData = data;

    resultsCard.classList.remove("hidden");
    comparisonBlock.classList.add("hidden");
    comparisonBlock.innerHTML = "";

    // reset AI state for fresh scan
    currentAiAnalysis = null;
    aiAnalysisLoading = false;
    aiSummary.classList.add("hidden");
    aiSummary.innerHTML = "";

    const md = data.scan_metadata || {};
    const sm = data.summary || {};
    resultsMeta.textContent =
      `${md.scan_mode || ""} · ` +
      `${sm.total_exposures || 0} exposure(s) · ` +
      `${md.apis_succeeded || 0}/${
        (md.apis_attempted || 0) + (md.apis_skipped || 0)
      } services responded · ` +
      `runtime ${fmtMs(md.runtime_delta_ms)}`;

    summaryPills.innerHTML = buildSummaryPills(sm, md);
    renderHygieneGauge(sm.hygiene_score);
    renderExposureGraph(data);

    currentExposures = data.results || [];
    currentPage = 1;
    renderCurrentPage();
    resultsCard.scrollIntoView({ behavior: "smooth", block: "start" });
    document.dispatchEvent(new CustomEvent("affectra:scanComplete"));

    // kick off AI analysis in the background — doesn't block scan render
    if ((data.results || []).length) {
      runAiAnalysis(data).catch(() => {});
    }
  }

  function renderCurrentPage() {
    exposureList.innerHTML = "";
    if (!currentExposures.length) {
      emptyState.classList.remove("hidden");
      exposureToolbar.classList.add("hidden");
      pagination.classList.add("hidden");
      return;
    }
    emptyState.classList.add("hidden");
    exposureToolbar.classList.remove("hidden");

    const total = currentExposures.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (currentPage > totalPages) currentPage = totalPages;

    const start = (currentPage - 1) * pageSize;
    const end = Math.min(start + pageSize, total);
    const slice = currentExposures.slice(start, end);

    exposureCount.textContent = `Showing ${start + 1}–${end} of ${total}`;

    for (const e of slice) {
      exposureList.insertAdjacentHTML("beforeend", renderExposure(e));
    }
    // Reflect any persisted "done" state visually after render
    $$("#exposure-list .exposure[data-id]").forEach((card) => {
      if (MitigationTracker.state(card.dataset.id) === "done") {
        card.classList.add("mt-done");
      }
    });
    bindExposureActions();

    renderPagination(totalPages);
  }

  function renderPagination(totalPages) {
    if (totalPages <= 1) {
      pagination.classList.add("hidden");
      pagination.innerHTML = "";
      return;
    }
    pagination.classList.remove("hidden");

    const btns = [];
    const mkBtn = (label, page, opts = {}) => {
      const cls = ["page-btn"];
      if (opts.active) cls.push("active");
      const disabled = opts.disabled ? "disabled" : "";
      const dataPage = page !== null ? `data-page="${page}"` : "";
      if (opts.ellipsis) {
        return `<span class="page-ellipsis">…</span>`;
      }
      return `<button type="button" class="${cls.join(" ")}" ${dataPage} ${disabled}>${escHtml(
        String(label)
      )}</button>`;
    };

    btns.push(mkBtn("‹ Prev", currentPage - 1, { disabled: currentPage === 1 }));

    // Windowed page list: 1 … (current-1, current, current+1) … last
    const windowPages = new Set([1, totalPages, currentPage]);
    for (let i = -1; i <= 1; i++) {
      const p = currentPage + i;
      if (p >= 1 && p <= totalPages) windowPages.add(p);
    }
    const sorted = [...windowPages].sort((a, b) => a - b);
    let last = 0;
    for (const p of sorted) {
      if (p - last > 1) btns.push(mkBtn("", null, { ellipsis: true }));
      btns.push(mkBtn(p, p, { active: p === currentPage }));
      last = p;
    }

    btns.push(
      mkBtn("Next ›", currentPage + 1, {
        disabled: currentPage === totalPages,
      })
    );

    pagination.innerHTML = btns.join("");
    pagination.querySelectorAll("[data-page]").forEach((b) => {
      b.addEventListener("click", () => {
        currentPage = parseInt(b.getAttribute("data-page"), 10) || 1;
        renderCurrentPage();
        resultsCard.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  pageSizeSelect.addEventListener("change", () => {
    pageSize = parseInt(pageSizeSelect.value, 10) || 10;
    currentPage = 1;
    renderCurrentPage();
  });
  expandAllBtn.addEventListener("click", () => {
    expandedByDefault = true;
    $$("#exposure-list .exposure").forEach((el) =>
      el.classList.remove("collapsed")
    );
  });
  collapseAllBtn.addEventListener("click", () => {
    expandedByDefault = false;
    $$("#exposure-list .exposure").forEach((el) =>
      el.classList.add("collapsed")
    );
  });

  function buildSummaryPills(sm, md) {
    const out = [];
    out.push(
      `<span class="pill risk-${escHtml(
        sm.overall_risk_level || "low"
      )}">Overall risk: ${titleCase(sm.overall_risk_level || "low")} · ${
        sm.overall_risk_score || 0
      }</span>`
    );
    for (const [cat, n] of Object.entries(sm.by_category || {})) {
      out.push(
        `<span class="pill pill-navy">${titleCase(cat)}: ${n}</span>`
      );
    }
    if ((md.errors || []).length) {
      out.push(
        `<span class="pill pill-gold">${md.errors.length} warning(s)</span>`
      );
    }
    return out.join("");
  }

  // ── Hygiene Gauge ────────────────────────────────────────────────────────────

  function renderHygieneGauge(score) {
    const gauge   = $("#hygiene-gauge");
    const arc     = $("#hygiene-arc");
    const numEl   = $("#hygiene-num");
    if (!gauge || !arc || !numEl) return;

    const s = (typeof score === "number" && !isNaN(score)) ? score : 100;
    const circumference = 201.06;  // 2π × 32
    const offset = circumference * (1 - s / 100);

    arc.style.strokeDashoffset = offset;
    numEl.textContent = Math.round(s);

    gauge.classList.remove("hidden", "hg-good", "hg-ok", "hg-poor", "hg-critical", "hg-excellent");
    if      (s >= 80) gauge.classList.add("hg-excellent");
    else if (s >= 65) gauge.classList.add("hg-good");
    else if (s >= 35) gauge.classList.add("hg-ok");
    else if (s >= 15) gauge.classList.add("hg-poor");
    else              gauge.classList.add("hg-critical");
  }

  // ── Hygiene Info Modal ───────────────────────────────────────────────────────

  (function initHygieneModal() {
    const infoBtn    = $("#hygiene-info-btn");
    const modal      = $("#hygiene-modal");
    const closeBtn   = $("#hygiene-modal-close");
    if (!infoBtn || !modal || !closeBtn) return;

    const openModal  = () => { modal.classList.remove("hidden"); infoBtn.setAttribute("aria-expanded", "true"); };
    const closeModal = () => { modal.classList.add("hidden");    infoBtn.setAttribute("aria-expanded", "false"); };

    infoBtn.addEventListener("click", openModal);
    closeBtn.addEventListener("click", closeModal);

    // close on backdrop click
    modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

    // close on Escape
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.classList.contains("hidden")) closeModal();
    });
  })();

  // ── Exposure Graph (D3 force-directed) ──────────────────────────────────────

  function renderExposureGraph(data) {
    const graphSection = $("#graph-section");
    const graphEl      = $("#exposure-graph");
    if (!graphSection || !graphEl) return;

    const results = data.results || [];
    const query   = data.query   || {};

    if (!results.length) {
      graphSection.classList.add("hidden");
      return;
    }
    graphSection.classList.remove("hidden");

    // collapse graph by default; user expands it
    const wrap   = $("#graph-canvas-wrap");
    const toggle = $("#graph-toggle");
    if (wrap && wrap.hidden) return; // not open yet — build on first open

    _buildGraph(graphEl, results, query);
  }

  function _buildGraph(container, results, query) {
    if (typeof d3 === "undefined") {
      container.innerHTML = '<p class="muted small" style="padding:1rem">D3 library not loaded.</p>';
      return;
    }

    container.innerHTML = "";
    const width  = container.clientWidth  || 700;
    const height = container.clientHeight || 420;

    const nodeMap  = new Map();
    const linkSet  = new Set();
    const links    = [];

    const addNode = (id, type, label, extra = {}) => {
      if (!nodeMap.has(id)) nodeMap.set(id, { id, type, label, ...extra });
    };

    // identifier nodes
    const identIds = [];
    if (query.email)     { const k = `id:${query.email}`;                         addNode(k, "identifier", query.email);      identIds.push(k); }
    if (query.full_name) { const k = `id:${query.full_name}`;                     addNode(k, "identifier", query.full_name);  identIds.push(k); }
    (query.usernames || []).forEach(u => { const k = `id:${u}`; addNode(k, "identifier", u); identIds.push(k); });
    const primaryId = identIds[0] || "id:unknown";

    // source + category nodes & edges
    const catLabels = {
      potential_breach: "Breach", paste_exposure: "Paste", data_broker: "Data Broker",
      code_repository: "Code Repo", document: "Document", public_directory: "Directory",
      historical_cache: "Archive", forum_mention: "Forum", social_trace: "Social", unknown: "Unknown",
    };

    for (const r of results) {
      const srcId = `src:${r.source_name}`;
      const catId = `cat:${r.classification}`;

      addNode(srcId, "source", r.source_name, { riskLevel: r.risk_level });
      addNode(catId, "category", catLabels[r.classification] || r.classification);

      // pick closest identifier for this finding's fields
      let bestId = primaryId;
      if (query.email && (r.matched_fields || []).includes("email"))     bestId = `id:${query.email}`;
      else if (query.full_name && (r.matched_fields || []).includes("full_name")) bestId = `id:${query.full_name}`;

      const l1 = `${bestId}→${srcId}`;
      const l2 = `${srcId}→${catId}`;
      if (!linkSet.has(l1)) { linkSet.add(l1); links.push({ source: bestId, target: srcId }); }
      if (!linkSet.has(l2)) { linkSet.add(l2); links.push({ source: srcId,  target: catId }); }
    }

    const nodes = [...nodeMap.values()];

    const svg = d3.select(container).append("svg")
      .attr("width", width).attr("height", height)
      .attr("viewBox", [0, 0, width, height]);

    // arrow marker
    svg.append("defs").append("marker")
      .attr("id", "arr").attr("viewBox", "0 -5 10 10")
      .attr("refX", 22).attr("refY", 0)
      .attr("markerWidth", 6).attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path").attr("d", "M0,-5L10,0L0,5").attr("fill", "#94a3b8");

    const simulation = d3.forceSimulation(nodes)
      .force("link",      d3.forceLink(links).id(d => d.id).distance(110))
      .force("charge",    d3.forceManyBody().strength(-320))
      .force("center",    d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(36));

    const link = svg.append("g").selectAll("line").data(links).join("line")
      .attr("stroke", "#94a3b8").attr("stroke-opacity", 0.55)
      .attr("stroke-width", 1.5).attr("marker-end", "url(#arr)");

    const nodeColor = d => {
      if (d.type === "identifier") return "#001d51";
      if (d.type === "category")   return "#b45309";
      const m = { critical: "#dc2626", high: "#ea580c", medium: "#ca8a04", low: "#16a34a" };
      return m[d.riskLevel] || "#64748b";
    };

    const nodeR = d => d.type === "identifier" ? 20 : d.type === "category" ? 13 : 11;

    const nodeG = svg.append("g").selectAll("g").data(nodes).join("g")
      .call(d3.drag()
        .on("start", (ev, d) => { if (!ev.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag",  (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
        .on("end",   (ev, d) => { if (!ev.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }));

    nodeG.append("circle")
      .attr("r", nodeR).attr("fill", nodeColor)
      .attr("stroke", "#fff").attr("stroke-width", 2);

    nodeG.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", d => nodeR(d) + 13)
      .attr("font-size", "10px").attr("fill", "#334155")
      .text(d => d.label.length > 20 ? d.label.slice(0, 18) + "…" : d.label);

    nodeG.append("title").text(d => d.label);

    simulation.on("tick", () => {
      link
        .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
      nodeG.attr("transform", d => `translate(${d.x},${d.y})`);
    });
  }

  // graph expand / collapse toggle
  const graphToggle = $("#graph-toggle");
  const graphWrap   = $("#graph-canvas-wrap");
  if (graphToggle && graphWrap) {
    graphToggle.addEventListener("click", () => {
      const open = graphWrap.hidden;
      graphWrap.hidden = !open;
      graphToggle.setAttribute("aria-expanded", String(open));
      if (open && currentScanData) {
        // build graph on first open so it has correct dimensions
        const el = $("#exposure-graph");
        if (el && !el.querySelector("svg")) {
          _buildGraph(el, currentScanData.results || [], currentScanData.query || {});
        }
      }
    });
    graphToggle.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); graphToggle.click(); }
    });
  }

  // ── Evaluation page ──────────────────────────────────────────────────────────

  // --- Coverage comparison ---
  const evalCompareForm = $("#eval-compare-form");
  const evalCompareBtn  = $("#eval-compare-btn");
  const evalCompareErr  = $("#eval-compare-error");
  const evalCompareRes  = $("#eval-compare-result");

  if (evalCompareForm) {
    evalCompareForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      evalCompareErr.textContent = "";
      const fd    = new FormData(evalCompareForm);
      const email = fd.get("eval_email")?.trim();
      const name  = fd.get("eval_name")?.trim();
      if (!email && !name) { evalCompareErr.textContent = "Enter at least one identifier."; return; }

      evalCompareBtn.disabled = true;
      evalCompareBtn.textContent = "Running…";
      evalCompareRes.classList.add("hidden");
      evalCompareRes.innerHTML = "";

      try {
        const body = {};
        if (email) body.email = email;
        if (name)  body.full_name = name;

        const r = await fetch("/api/evaluate/compare", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw await errorFrom(r);
        const d = await r.json();
        evalCompareRes.innerHTML = buildCompareTable(d);
        evalCompareRes.classList.remove("hidden");
      } catch (err) {
        evalCompareErr.textContent = err?.message || String(err);
      } finally {
        evalCompareBtn.disabled = false;
        evalCompareBtn.textContent = "Run comparison";
      }
    });
  }

  function buildCompareTable(d) {
    const modeOrder = ["API_ONLY", "HYBRID", "DEEP_SCAN", "EXTENDED_EXPLORATION"];
    const rows = (d.runs || [])
      .sort((a, b) => modeOrder.indexOf(a.mode) - modeOrder.indexOf(b.mode))
      .map(run => `
        <tr>
          <td>${escHtml(run.mode)}</td>
          <td class="num">${run.total_exposures}</td>
          <td class="num">${run.apis_attempted}</td>
          <td class="num">${run.sources_checked}</td>
          <td class="num">${run.pages_scanned}</td>
          <td class="num">${fmtMs(run.runtime_delta_ms)}</td>
          <td><span class="pill risk-${escHtml(run.overall_risk_level)}">${titleCase(run.overall_risk_level)}</span></td>
        </tr>`).join("");

    return `
      <div class="eval-metrics">
        <div class="eval-metric">
          <span class="eval-metric-val">${d.coverage_uplift_pct}%</span>
          <span class="eval-metric-label">Coverage uplift</span>
        </div>
        <div class="eval-metric">
          <span class="eval-metric-val">${fmtMs(d.runtime_overhead_ms)}</span>
          <span class="eval-metric-label">Runtime overhead</span>
        </div>
      </div>
      <div class="eval-table-wrap">
        <table class="eval-table">
          <thead><tr>
            <th>Mode</th><th>Exposures</th><th>APIs</th>
            <th>Sources</th><th>Pages</th><th>Runtime</th><th>Risk</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  // --- False Positive Rate ---
  const evalFprBtn = $("#eval-fpr-btn");
  const evalFprRes = $("#eval-fpr-result");

  if (evalFprBtn) {
    evalFprBtn.addEventListener("click", async () => {
      evalFprBtn.disabled = true;
      evalFprBtn.textContent = "Running (~30s)…";
      evalFprRes.classList.add("hidden");
      evalFprRes.innerHTML = "";

      try {
        const r = await fetch("/api/evaluate/fpr", { method: "POST" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        evalFprRes.innerHTML = buildFprResult(d);
        evalFprRes.classList.remove("hidden");
      } catch (err) {
        evalFprRes.innerHTML = `<p class="form-error">${escHtml(err?.message || String(err))}</p>`;
        evalFprRes.classList.remove("hidden");
      } finally {
        evalFprBtn.disabled = false;
        evalFprBtn.textContent = "Run FPR test";
      }
    });
  }

  function buildFprResult(d) {
    const rows = (d.per_query || []).map(q => `
      <tr>
        <td>${escHtml(q.label)}</td>
        <td class="num">${q.false_positives}</td>
        <td class="num">${q.apis_attempted}</td>
        <td class="num">${q.apis_succeeded}</td>
        <td class="num">${fmtMs(q.runtime_ms)}</td>
      </tr>`).join("");

    const rateColor = d.false_positive_rate_pct === 0 ? "hg-good" : d.false_positive_rate_pct < 10 ? "hg-ok" : "hg-poor";
    return `
      <div class="eval-metrics">
        <div class="eval-metric">
          <span class="eval-metric-val hygiene-gauge ${rateColor}" style="font-size:1.8rem">${d.false_positive_rate_pct}%</span>
          <span class="eval-metric-label">False positive rate</span>
        </div>
        <div class="eval-metric">
          <span class="eval-metric-val">${d.total_false_positives}</span>
          <span class="eval-metric-label">Total FPs found</span>
        </div>
        <div class="eval-metric">
          <span class="eval-metric-val">${d.total_queries}</span>
          <span class="eval-metric-label">Queries tested</span>
        </div>
      </div>
      <div class="eval-table-wrap">
        <table class="eval-table">
          <thead><tr>
            <th>Test identifier</th><th>FP findings</th>
            <th>APIs tried</th><th>APIs OK</th><th>Runtime</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p class="eval-methodology-note">${escHtml(d.methodology || "")}</p>`;
  }

  // --- Sensitivity analysis ---
  const evalSensBtn  = $("#eval-sensitivity-btn");
  const evalSensHint = $("#eval-sensitivity-hint");
  const evalSensRes  = $("#eval-sensitivity-result");

  if (evalSensBtn) {
    // enable/disable based on whether a scan has been run
    const updateSensBtn = () => {
      const hasScan = !!(currentScanData && (currentScanData.results || []).length);
      evalSensBtn.disabled = !hasScan;
      if (evalSensHint) evalSensHint.textContent = hasScan
        ? `${currentScanData.results.length} finding(s) ready to analyse.`
        : "Run a scan first to enable this.";
    };
    updateSensBtn();

    // re-check whenever evaluation page is opened
    const origSwitch = window.switchToSettings;
    document.addEventListener("affectra:scanComplete", updateSensBtn);

    evalSensBtn.addEventListener("click", async () => {
      if (!currentScanData || !(currentScanData.results || []).length) return;

      evalSensBtn.disabled = true;
      evalSensBtn.textContent = "Analysing…";
      evalSensRes.classList.add("hidden");

      const findings = (currentScanData.results || []).map(r => ({
        source_name:        r.source_name,
        classification:     r.classification,
        matched_fields:     r.matched_fields || [],
        confidence_score:   r.confidence_score || 0,
        current_risk_score: r.risk_score || 0,
      }));

      try {
        const r = await fetch("/api/evaluate/sensitivity", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ findings }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        evalSensRes.innerHTML = buildSensResult(d);
        evalSensRes.classList.remove("hidden");
      } catch (err) {
        evalSensRes.innerHTML = `<p class="form-error">${escHtml(err?.message || String(err))}</p>`;
        evalSensRes.classList.remove("hidden");
      } finally {
        evalSensBtn.disabled = false;
        evalSensBtn.textContent = "Analyse last scan";
        updateSensBtn();
      }
    });

    // refresh hint whenever evaluation page becomes visible
    const evalNavBtn = document.querySelector('.main-nav-btn[data-page="evaluation"]');
    if (evalNavBtn) evalNavBtn.addEventListener("click", updateSensBtn);
  }

  function buildSensResult(d) {
    const ov = d.overall || {};
    const overallRow = (label, cls) => {
      const o = ov[label] || {};
      return `<td class="num ${cls}">${o.risk_score ?? "—"}</td><td class="num ${cls}">${o.hygiene_score ?? "—"}</td>`;
    };

    const rows = (d.per_finding || []).map(f => `
      <tr>
        <td>${escHtml(f.source_name)}</td>
        <td>${escHtml(f.classification)}</td>
        <td class="num sens-conservative">${f.conservative}</td>
        <td class="num sens-balanced">${f.balanced}</td>
        <td class="num sens-aggressive">${f.aggressive}</td>
        <td class="num">${f.baseline}</td>
      </tr>`).join("");

    return `
      <div class="eval-metrics">
        <div class="eval-metric">
          <span class="eval-metric-val sens-conservative">${ov.conservative?.risk_score ?? "—"}</span>
          <span class="eval-metric-label">Conservative risk</span>
        </div>
        <div class="eval-metric">
          <span class="eval-metric-val sens-balanced">${ov.balanced?.risk_score ?? "—"}</span>
          <span class="eval-metric-label">Balanced (default)</span>
        </div>
        <div class="eval-metric">
          <span class="eval-metric-val sens-aggressive">${ov.aggressive?.risk_score ?? "—"}</span>
          <span class="eval-metric-label">Aggressive risk</span>
        </div>
        <div class="eval-metric">
          <span class="eval-metric-val">${ov.balanced?.hygiene_score ?? "—"}</span>
          <span class="eval-metric-label">Hygiene (balanced)</span>
        </div>
      </div>
      <div class="eval-table-wrap">
        <table class="eval-table">
          <thead><tr>
            <th>Source</th><th>Category</th>
            <th>Conservative (−20%)</th><th>Balanced</th><th>Aggressive (+20%)</th><th>Current</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p class="eval-methodology-note">${escHtml(d.methodology || "")}</p>`;
  }

  function renderExposure(e) {
    const confirmed =
      (e.source_count && e.source_count > 1) ||
      (e.confirmed_by && e.confirmed_by.length > 1);
    const confirmedBadge = confirmed
      ? `<span class="tag tag-confirmed">Confirmed by ${
          e.source_count || e.confirmed_by.length
        } sources</span>`
      : "";

    const sources = (e.confirmed_by || [])
      .map((s) => escHtml(s))
      .join(", ");

    const matchedFields = (e.matched_fields || [])
      .map((f) => `<span class="tag">${escHtml(f)}</span>`)
      .join("");

    // Mitigation steps — three possible states:
    //  1. AI loading  → shimmer placeholder (smarter steps incoming)
    //  2. AI loaded with steps for this finding → AI-written steps (labelled)
    //  3. No AI / AI skipped this finding → static fallback from backend
    let mitigationHtml = "";
    if (aiAnalysisLoading) {
      mitigationHtml = `
        <div class="mitigation-loading" aria-label="Loading AI mitigation steps…">
          <div class="mitigation-shimmer"></div>
          <div class="mitigation-shimmer mitigation-shimmer-mid"></div>
          <div class="mitigation-shimmer mitigation-shimmer-short"></div>
        </div>`;
    } else {
      const aiSteps =
        currentAiAnalysis &&
        currentAiAnalysis.per_finding_mitigations &&
        currentAiAnalysis.per_finding_mitigations[e.id];

      if (aiSteps && aiSteps.length) {
        const items = aiSteps
          .map((s) => `<li>${escHtml(s)}</li>`)
          .join("");
        mitigationHtml = `
          <div>
            <strong>Mitigation steps <span class="ai-label ai-label-inline">✦ AI</span></strong>
            <ul class="exposure-mitigation">${items}</ul>
          </div>`;
      } else {
        const staticItems = (e.mitigation || [])
          .map((s) => `<li>${escHtml(s)}</li>`)
          .join("");
        if (staticItems) {
          mitigationHtml = `
            <div>
              <strong>Mitigation steps</strong>
              <ul class="exposure-mitigation">${staticItems}</ul>
            </div>`;
        }
      }
    }

    const snippet = e.snippet
      ? `<div class="exposure-snippet">${escHtml(e.snippet)}</div>`
      : "";

    const urlLink = e.source_url
      ? `<a href="${escHtml(
          e.source_url
        )}" target="_blank" rel="noopener noreferrer">${escHtml(
          e.source_url
        )}</a>`
      : "";

    // matched data grid — everything the adapter captured, rendered as a
    // definition list so long rows wrap cleanly
    const fieldRows = Object.entries(e.matched_data || {})
      .map(
        ([k, v]) =>
          `<dt>${escHtml(k)}</dt><dd>${escHtml(String(v))}</dd>`
      )
      .join("");
    const fieldsGrid = fieldRows
      ? `<dl class="exposure-fields-grid">${fieldRows}</dl>`
      : "";

    const collapsedCls = expandedByDefault ? "" : "collapsed";
    const riskCls = e.risk_level ? `risk-${escHtml(e.risk_level)}` : "";

    // ── Mitigation tracker status button (always visible, even when collapsed)
    const mtState = MitigationTracker.state(e.id);
    const mtStatusBtn = `<button
        class="mitigation-status-btn mt-${escHtml(mtState)}"
        data-action="mt-cycle"
        title="Cycle action status"
        aria-label="Mitigation status: ${MitigationTracker.LABELS[mtState]}"
      >${MitigationTracker.ICONS[mtState]} ${MitigationTracker.LABELS[mtState]}</button>`;

    // ── Copy deletion email button (only when backend generated a template)
    const emailBtn = e.deletion_email_template
      ? `<div class="copy-email-wrap">
          <button class="copy-email-btn" data-action="copy-email"
            data-template="${escHtml(e.deletion_email_template)}"
            title="Copy a GDPR / CCPA deletion request email to clipboard">
            📋 Copy deletion email
          </button>
          <span class="copy-email-confirm hidden" aria-live="polite">Copied!</span>
         </div>`
      : "";

    // Hook line — always visible in both collapsed and expanded state.
    // Tells the user WHAT was actually found before they decide to expand.
    // Priority: matched_data key:value → matched_fields list → snippet preview.
    const hookHtml = (() => {
      const dataEntries = Object.entries(e.matched_data || {}).slice(0, 3);
      if (dataEntries.length) {
        const parts = dataEntries.map(([k, v]) => {
          const raw = String(v || "").trim();
          const display = raw.length > 44 ? raw.slice(0, 44) + "…" : raw;
          return `<span class="hook-kv"><span class="hook-key">${escHtml(k)}</span>: <span class="hook-val">${escHtml(display)}</span></span>`;
        });
        return `<p class="exposure-hook">${parts.join('<span class="hook-dot">&middot;</span>')}</p>`;
      }
      const fields = e.matched_fields || [];
      if (fields.length) {
        const list = fields.map(f => `<span class="hook-key">${escHtml(f)}</span>`).join(", ");
        return `<p class="exposure-hook"><span class="hook-label">Fields found:</span> ${list}</p>`;
      }
      if (e.snippet) {
        const preview = e.snippet.trim();
        const short = preview.length > 90 ? preview.slice(0, 90) + "…" : preview;
        return `<p class="exposure-hook hook-muted">${escHtml(short)}</p>`;
      }
      return "";
    })();

    // AI commentary — loading shimmer, actual text, or nothing
    let aiSection = "";
    if (aiAnalysisLoading) {
      aiSection = `<div class="ai-commentary ai-loading">
        <span class="ai-label">✦ AI Analysis</span>
        <span>Analysing…</span>
      </div>`;
    } else if (
      currentAiAnalysis &&
      currentAiAnalysis.per_finding &&
      currentAiAnalysis.per_finding[e.id]
    ) {
      aiSection = `<div class="ai-commentary">
        <span class="ai-label">✦ AI Analysis</span>
        <p class="ai-commentary-text">${escHtml(
          currentAiAnalysis.per_finding[e.id]
        )}</p>
      </div>`;
    }

    return `
      <article class="exposure ${collapsedCls} ${riskCls}" data-id="${escHtml(e.id)}">
        <div class="exposure-summary">
          <div class="exposure-summary-main">
            <div class="exposure-source">
              ${escHtml(e.source_name || "Unknown source")}
              <div class="exposure-url">${urlLink}</div>
            </div>
            ${hookHtml}
            <div class="exposure-meta">
              <span class="tag">${titleCase(e.classification || "unknown")}</span>
              <span class="tag">${titleCase(e.source_type || "")}</span>
              <span class="tag">${titleCase(e.match_type || "")}</span>
              ${matchedFields}
              ${confirmedBadge}
            </div>
          </div>
          <div class="summary-pills">
            <span class="pill risk-${escHtml(e.risk_level)}">Risk: ${titleCase(e.risk_level)} &middot; ${e.risk_score || 0}</span>
            <span class="pill pill-navy">Confidence: ${titleCase(e.confidence_level)} &middot; ${e.confidence_score || 0}</span>
            ${mtStatusBtn}
            <span class="exposure-chev">
              <span class="chev-arrow">▾</span>
              <span class="chev-label">${collapsedCls ? "Details" : "Hide"}</span>
            </span>
          </div>
        </div>
        <div class="exposure-details">
          ${aiSection}
          ${snippet}
          ${fieldsGrid}
          ${sources ? `<p class="muted small">Surfaced by: ${sources}</p>` : ""}
          ${mitigationHtml}
          ${emailBtn}
        </div>
      </article>`;
  }

  // ── History page ──────────────────────────────────────────────────────────

  // ── History tab switching (wired once on first open) ──────────────────────
  let _historyTabsWired = false;
  function _wireHistoryTabs() {
    if (_historyTabsWired) return;
    _historyTabsWired = true;
    const panel = $("#history-panel");
    if (!panel) return;
    panel.querySelectorAll(".devmenu-tab[data-htab]").forEach((tab) => {
      tab.addEventListener("click", () => {
        panel.querySelectorAll(".devmenu-tab[data-htab]").forEach((t) => {
          t.classList.remove("active");
          t.setAttribute("aria-selected", "false");
        });
        tab.classList.add("active");
        tab.setAttribute("aria-selected", "true");
        panel.querySelectorAll(".devmenu-tabpanel[data-hpanel]").forEach((p) => p.classList.remove("active"));
        const target = panel.querySelector(`.devmenu-tabpanel[data-hpanel="${tab.dataset.htab}"]`);
        if (target) target.classList.add("active");
      });
    });
  }

  // Returns the primary label for grouping scans into a profile
  function _profileKey(scan) {
    const q = scan.query || {};
    if (q.email)     return q.email.toLowerCase().trim();
    if (q.usernames) return q.usernames.split(",")[0].trim().toLowerCase();
    if (q.full_name) return q.full_name.toLowerCase().trim();
    return "unknown";
  }

  async function renderHistoryPage() {
    const listEl   = $("#history-list");
    const profEl   = $("#history-profiles");
    const clearBtn = $("#history-clear-all");

    _wireHistoryTabs();

    // Show loading state
    if (listEl) listEl.innerHTML = `<div class="history-empty"><p class="muted">Loading…</p></div>`;
    if (profEl) profEl.innerHTML = "";

    await ScanHistory.load();
    const scans = ScanHistory.all();

    if (clearBtn) {
      clearBtn.onclick = async () => {
        if (!scans.length) return;
        if (!window.confirm("Remove all saved scans?")) return;
        await ScanHistory.clear();
        renderHistoryPage();
      };
    }

    // ── All Scans tab ──────────────────────────────────────────────────────
    if (listEl) {
      if (!scans.length) {
        listEl.innerHTML = `<div class="history-empty"><p class="muted">No scans saved yet. Run a scan and it will appear here.</p></div>`;
      } else {
        listEl.innerHTML = scans.map(renderHistoryScanCard).join("");
        bindHistoryListActions(listEl);
      }
    }

    // ── Profiles tab ───────────────────────────────────────────────────────
    if (profEl) {
      if (!scans.length) {
        profEl.innerHTML = `<div class="history-empty"><p class="muted">No scans saved yet. Run a scan to build a profile.</p></div>`;
      } else {
        const groups = {};
        scans.forEach((s) => {
          const key = _profileKey(s);
          if (!groups[key]) groups[key] = [];
          groups[key].push(s);
        });
        profEl.innerHTML = Object.entries(groups)
          .map(([key, group]) => renderProfileCard(key, group))
          .join("");
        bindHistoryListActions(profEl);
      }
    }
  }

  // ── Shared finding-rows builder ────────────────────────────────────────────
  function buildFindingRows(results) {
    if (!results.length) return '<p class="muted small hf-none">No findings recorded.</p>';
    return results.map((e) => {
      const mtState   = MitigationTracker.state(e.id);
      const findRisk  = `risk-${e.risk_level || "unknown"}`;
      const emailBtn  = e.deletion_email_template
        ? `<button class="copy-email-btn copy-email-sm" data-action="copy-email"
               data-template="${escHtml(e.deletion_email_template)}"
               title="Copy GDPR deletion email">📋</button>
             <span class="copy-email-confirm hidden" aria-live="polite">Copied!</span>`
        : "";
      return `
        <div class="hf-row ${mtState === "done" ? "hf-done" : ""}" data-id="${escHtml(e.id)}">
          <div class="hf-left">
            <span class="hf-source">${escHtml(e.source_name || "Unknown")}</span>
            <span class="tag">${escHtml(titleCase(e.classification || "unknown"))}</span>
            <span class="pill ${findRisk} pill-xs">${titleCase(e.risk_level || "")}</span>
          </div>
          <div class="hf-right">
            <button class="mitigation-status-btn mt-${escHtml(mtState)}"
              data-action="mt-cycle" title="Cycle status"
              aria-label="Mitigation status: ${MitigationTracker.LABELS[mtState]}">
              ${MitigationTracker.ICONS[mtState]} ${MitigationTracker.LABELS[mtState]}
            </button>
            ${emailBtn}
          </div>
        </div>`;
    }).join("");
  }

  function buildProgressBar(results) {
    const total     = results.length;
    const doneCount = results.filter((e) => MitigationTracker.state(e.id) === "done").length;
    const pct       = total ? Math.round((doneCount / total) * 100) : 0;
    return { total, doneCount, pct };
  }

  // ── All-scans card ─────────────────────────────────────────────────────────
  function renderHistoryScanCard(scan) {
    const q   = scan.query    || {};
    const sm  = scan.summary  || {};
    const md  = scan.metadata || {};
    const results = scan.results || [];

    const label   = [q.email, q.full_name, q.phone, q.usernames].filter(Boolean).join(" · ") || "Unknown query";
    const date    = new Date(scan.timestamp).toLocaleString("en-GB", { day:"numeric", month:"short", year:"numeric", hour:"2-digit", minute:"2-digit" });
    const riskCls = `risk-${sm.overall_risk_level || "unknown"}`;
    const { total, doneCount, pct } = buildProgressBar(results);

    return `
      <div class="history-scan-card" data-scan-id="${escHtml(scan.id)}">
        <div class="history-scan-header">
          <div class="history-scan-info">
            <span class="history-label">${escHtml(label)}</span>
            <span class="history-meta muted small">
              ${escHtml(md.scan_mode || q.mode || "")} &middot;
              ${total} finding(s) &middot;
              Risk: <span class="${riskCls} fw-600">${titleCase(sm.overall_risk_level || "—")}</span>
              &middot; Hygiene: ${sm.hygiene_score ?? "—"}
            </span>
            <span class="history-date muted small">${escHtml(date)}</span>
          </div>
          <div class="history-scan-actions">
            <button class="btn btn-sm btn-primary" data-action="rerun-scan" title="Pre-fill form and re-run">↺ Re-run</button>
            <button class="btn btn-sm btn-ghost"   data-action="delete-scan" title="Remove this scan">✕</button>
            <span class="history-chev" aria-hidden="true">▾</span>
          </div>
        </div>
        <div class="history-progress-wrap">
          <div class="history-progress-track">
            <div class="history-progress-fill" style="width:${pct}%"></div>
          </div>
          <span class="history-progress-label">${doneCount}/${total} actioned</span>
        </div>
        <div class="history-findings hidden">
          ${buildFindingRows(results)}
        </div>
      </div>`;
  }

  // ── Profile card (groups multiple scans by same identifier) ───────────────
  function renderProfileCard(key, scans) {
    // scans are newest-first; for trend show oldest→newest
    const chronological = [...scans].reverse();
    const latest  = scans[0];
    const sm      = latest.summary  || {};
    const q       = latest.query    || {};
    const riskCls = `risk-${sm.overall_risk_level || "unknown"}`;

    // Trend: finding counts oldest → newest
    const counts  = chronological.map((s) => (s.summary || {}).total_exposures ?? (s.results || []).length);
    const trend   = counts.join(" → ");
    // Hygiene sparkline: text representation
    const hygiene = chronological.map((s) => (s.summary || {}).hygiene_score ?? "?");
    const hygieneStr = hygiene.join(" → ");

    // Direction arrow
    const first = counts[0] ?? 0;
    const last  = counts[counts.length - 1] ?? 0;
    const arrow = counts.length < 2 ? "" : last < first ? '<span class="trend-good">↓ Improving</span>' : last > first ? '<span class="trend-bad">↑ Worsening</span>' : '<span class="trend-neutral">→ Stable</span>';

    // All findings across all scans (latest scan's findings for tracker)
    const latestResults = latest.results || [];
    const { total, doneCount, pct } = buildProgressBar(latestResults);

    // Mini scan list
    const scanList = scans.map((s) => {
      const sDate   = new Date(s.timestamp).toLocaleString("en-GB", { day:"numeric", month:"short", year:"numeric", hour:"2-digit", minute:"2-digit" });
      const sMd     = s.metadata || {};
      const sSm     = s.summary  || {};
      const sRisk   = `risk-${sSm.overall_risk_level || "unknown"}`;
      const sTotal  = sSm.total_exposures ?? (s.results || []).length;
      return `
        <div class="profile-scan-row" data-scan-id="${escHtml(s.id)}">
          <span class="profile-scan-date muted small">${escHtml(sDate)}</span>
          <span class="muted small">${escHtml(sMd.scan_mode || s.query?.mode || "")}</span>
          <span class="${sRisk} fw-600 small">${titleCase(sSm.overall_risk_level || "—")}</span>
          <span class="muted small">${sTotal} finding(s)</span>
          <button class="btn btn-xs btn-primary" data-action="rerun-scan" data-scan-id="${escHtml(s.id)}" title="Re-run this scan">↺</button>
        </div>`;
    }).join("");

    return `
      <div class="history-scan-card profile-card" data-profile-key="${escHtml(key)}">
        <div class="history-scan-header">
          <div class="history-scan-info">
            <span class="history-label">${escHtml(key)}</span>
            <span class="history-meta muted small">
              ${scans.length} scan(s) &middot;
              Risk now: <span class="${riskCls} fw-600">${titleCase(sm.overall_risk_level || "—")}</span>
              &middot; Hygiene: ${sm.hygiene_score ?? "—"}
            </span>
            <span class="history-meta muted small">
              Findings: ${trend} ${arrow}
              &nbsp;&middot;&nbsp; Hygiene: ${hygieneStr}
            </span>
          </div>
          <div class="history-scan-actions">
            <button class="btn btn-sm btn-primary" data-action="rerun-scan" data-scan-id="${escHtml(latest.id)}" title="Re-run latest scan for this profile">↺ Re-run</button>
            <span class="history-chev" aria-hidden="true">▾</span>
          </div>
        </div>

        <div class="history-progress-wrap">
          <div class="history-progress-track">
            <div class="history-progress-fill" style="width:${pct}%"></div>
          </div>
          <span class="history-progress-label">${doneCount}/${total} actioned (latest scan)</span>
        </div>

        <div class="history-findings hidden">
          <div class="profile-scan-list">${scanList}</div>
          <div class="profile-findings-header muted small">Latest scan findings</div>
          ${buildFindingRows(latestResults)}
        </div>
      </div>`;
  }

  // ── Shared action binding — works on any container ────────────────────────
  function bindHistoryListActions(container) {

    // Expand / collapse findings on header click
    container.querySelectorAll(".history-scan-header").forEach((hdr) => {
      hdr.addEventListener("click", (ev) => {
        if (ev.target.closest("[data-action]")) return;
        const card     = hdr.closest(".history-scan-card");
        const findings = card.querySelector(".history-findings");
        const chev     = card.querySelector(".history-chev");
        findings.classList.toggle("hidden");
        if (chev) chev.textContent = findings.classList.contains("hidden") ? "▾" : "▴";
      });
    });

    // Re-run: pre-fill form + switch page
    container.querySelectorAll("[data-action='rerun-scan']").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const scanId = btn.dataset.scanId || btn.closest(".history-scan-card")?.dataset.scanId;
        const scan   = ScanHistory.all().find((s) => s.id === scanId);
        if (!scan) return;
        const q  = scan.query || {};
        const fq = (sel) => form.querySelector(sel);
        if (fq('[name="email"]'))     fq('[name="email"]').value     = q.email     || "";
        if (fq('[name="full_name"]')) fq('[name="full_name"]').value = q.full_name || "";
        if (fq('[name="phone"]'))     fq('[name="phone"]').value     = q.phone     || "";
        if (fq('[name="usernames"]')) fq('[name="usernames"]').value = q.usernames || "";
        const modeIn = fq(`[name="scan_mode"][value="${q.mode || "HYBRID"}"]`);
        if (modeIn) modeIn.checked = true;
        switchPage("scan");
        setTimeout(() => form.scrollIntoView({ behavior:"smooth", block:"start" }), 80);
      });
    });

    // Delete a single scan card
    container.querySelectorAll("[data-action='delete-scan']").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const card = btn.closest(".history-scan-card");
        await ScanHistory.remove(card.dataset.scanId);
        card.remove();
        if (!container.querySelectorAll(".history-scan-card").length) {
          container.innerHTML = `<div class="history-empty"><p class="muted">No scans saved yet.</p></div>`;
        }
      });
    });

    // Tracker cycle — works in both tabs
    container.querySelectorAll("[data-action='mt-cycle']").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const row = btn.closest(".hf-row");
        const id  = row.dataset.id;
        const nxt = MitigationTracker.next(id);
        btn.className   = `mitigation-status-btn mt-${nxt}`;
        btn.setAttribute("aria-label", `Mitigation status: ${MitigationTracker.LABELS[nxt]}`);
        btn.textContent = `${MitigationTracker.ICONS[nxt]} ${MitigationTracker.LABELS[nxt]}`;
        row.classList.toggle("hf-done", nxt === "done");
        // Refresh progress bar in the parent card
        const card = row.closest(".history-scan-card");
        if (!card) return;
        const scanId = card.dataset.scanId || card.dataset.profileKey;
        const allScans = ScanHistory.all();
        const scan = allScans.find((s) => s.id === scanId) || allScans.find((s) => _profileKey(s) === scanId);
        if (!scan) return;
        const res = scan.results || [];
        const done = res.filter((e) => MitigationTracker.state(e.id) === "done").length;
        const pct  = res.length ? Math.round((done / res.length) * 100) : 0;
        const fill  = card.querySelector(".history-progress-fill");
        const lbl   = card.querySelector(".history-progress-label");
        if (fill) fill.style.width   = `${pct}%`;
        if (lbl)  lbl.textContent    = `${done}/${res.length} actioned`;
      });
    });

    // Copy deletion email — renamed to avoid shadowing window.confirm
    container.querySelectorAll("[data-action='copy-email']").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const tmpl       = btn.dataset.template || "";
        const confirmEl  = btn.parentElement.querySelector(".copy-email-confirm");
        const showCopied = () => {
          if (!confirmEl) return;
          confirmEl.classList.remove("hidden");
          setTimeout(() => confirmEl.classList.add("hidden"), 2200);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(tmpl).then(showCopied).catch(() => {
            _clipboardFallback(tmpl); showCopied();
          });
        } else {
          _clipboardFallback(tmpl); showCopied();
        }
      });
    });
  }

  function _clipboardFallback(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
    document.body.appendChild(ta);
    ta.focus(); ta.select();
    try { document.execCommand("copy"); } catch {}
    document.body.removeChild(ta);
  }

  function bindExposureActions() {
    // ── Collapse / expand on summary click ───────────────────────────────────
    $$("#exposure-list .exposure-summary").forEach((summary) => {
      summary.addEventListener("click", (ev) => {
        // Don't collapse when clicking the tracker button (it bubbles up here)
        if (ev.target.closest("[data-action]")) return;
        const card = summary.closest(".exposure");
        card.classList.toggle("collapsed");
        const label = summary.querySelector(".chev-label");
        if (label) label.textContent = card.classList.contains("collapsed") ? "Details" : "Hide";
      });
    });

    // ── Mitigation status cycle ───────────────────────────────────────────────
    $$("#exposure-list [data-action='mt-cycle']").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();          // never trigger card collapse
        const card = btn.closest(".exposure");
        const id   = card.dataset.id;
        const nxt  = MitigationTracker.next(id);
        // Update button appearance in-place (no re-render needed)
        btn.className = `mitigation-status-btn mt-${nxt}`;
        btn.setAttribute("aria-label", `Mitigation status: ${MitigationTracker.LABELS[nxt]}`);
        btn.textContent = `${MitigationTracker.ICONS[nxt]} ${MitigationTracker.LABELS[nxt]}`;
        // Strike-through the whole card header when done
        card.classList.toggle("mt-done", nxt === "done");
      });
    });

    // ── Copy deletion email ───────────────────────────────────────────────────
    $$("#exposure-list [data-action='copy-email']").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const tmpl      = btn.dataset.template || "";
        const confirmEl = btn.parentElement.querySelector(".copy-email-confirm");
        const showCopied = () => {
          if (!confirmEl) return;
          confirmEl.classList.remove("hidden");
          setTimeout(() => confirmEl.classList.add("hidden"), 2200);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(tmpl).then(showCopied).catch(() => {
            _clipboardFallback(tmpl); showCopied();
          });
        } else {
          _clipboardFallback(tmpl); showCopied();
        }
      });
    });
  }

  // ai analysis

  // Parses a prefixed error string from the backend and renders the right banner.
  // Prefixes: KEY_ISSUE | QUOTA | TIMEOUT | UNAVAILABLE | ai_unavailable
  function renderAiError(raw) {
    const sep   = raw.indexOf(":");
    const code  = sep > 0 ? raw.slice(0, sep) : "UNAVAILABLE";
    const human = sep > 0 ? raw.slice(sep + 1).trim() : raw.trim();

    if (code === "KEY_ISSUE") {
      // Key missing or expired — show an actionable banner with a Dev Menu shortcut
      const label = human.toLowerCase().includes("expired")
        ? "Update key"
        : "Add key";
      return `
        <div class="ai-key-error">
          <span class="ai-key-error-icon" aria-hidden="true">🔑</span>
          <span class="ai-key-error-msg">${escHtml(human)}</span>
          <button type="button" class="btn btn-ghost btn-small ai-key-error-btn"
                  onclick="window.switchToSettings('keys')"
            ${escHtml(label)}
          </button>
        </div>`;
    }

    if (code === "QUOTA") {
      return `<p class="ai-soft-error">⏳ ${escHtml(human)}</p>`;
    }

    if (code === "TIMEOUT") {
      return `<p class="ai-soft-error">⌛ ${escHtml(human)}</p>`;
    }

    // UNAVAILABLE / unknown — quiet single line
    return `<p class="ai-soft-error">${escHtml(human)}</p>`;
  }

  async function runAiAnalysis(data) {
    if (!data || !(data.results || []).length) return;

    aiAnalysisLoading = true;
    aiSummary.innerHTML =
      '<div class="ai-loading"><span>✦</span> Analysing threats with AI…</div>';
    aiSummary.classList.remove("hidden");
    renderCurrentPage(); // renders cards with loading shimmer

    try {
      const q = data.query || {};
      const querySummary = {};
      if (q.email) querySummary.email = q.email;
      if (q.full_name) querySummary.full_name = q.full_name;

      const r = await fetch("/api/analyse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          findings: data.results,
          query_summary: querySummary,
        }),
      });
      if (!r.ok) throw new Error(`AI analysis request failed (${r.status})`);
      const analysis = await r.json();

      aiAnalysisLoading = false;
      currentAiAnalysis = analysis;

      if (analysis.error) {
        aiSummary.innerHTML = renderAiError(analysis.error);
      } else if (analysis.overall_summary) {
        aiSummary.innerHTML = `
          <div class="ai-summary-header">
            <span class="ai-label">✦ AI Summary</span>
          </div>
          <div class="ai-summary-body">
            <p>${escHtml(analysis.overall_summary)}</p>
          </div>`;
      } else {
        aiSummary.classList.add("hidden");
      }

      renderCurrentPage(); // re-render cards with actual commentary
    } catch (err) {
      aiAnalysisLoading = false;
      aiSummary.innerHTML = renderAiError("UNAVAILABLE:AI analysis unavailable.");
      renderCurrentPage();
    }
  }

  // compare view

  function renderCompare(data) {
    resultsCard.classList.remove("hidden");
    emptyState.classList.add("hidden");
    comparisonBlock.classList.remove("hidden");

    const rows = (data.runs || [])
      .map(
        (r) => `
        <tr>
          <td><strong>${titleCase(r.mode)}</strong></td>
          <td>${r.total_exposures}</td>
          <td>${r.api_calls_made}</td>
          <td>${r.sources_checked}</td>
          <td>${r.pages_scanned}</td>
          <td>${r.apis_succeeded}/${r.apis_attempted + r.apis_skipped}</td>
          <td>${fmtMs(r.runtime_delta_ms)}</td>
          <td><span class="pill risk-${escHtml(
            r.overall_risk_level
          )}">${titleCase(r.overall_risk_level)} · ${
          r.overall_risk_score
        }</span></td>
        </tr>`
      )
      .join("");

    comparisonBlock.innerHTML = `
      <h3>Mode comparison</h3>
      <table>
        <thead>
          <tr>
            <th>Mode</th><th>Exposures</th><th>API calls</th>
            <th>Sources</th><th>Pages</th><th>Services</th>
            <th>Runtime</th><th>Overall risk</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="deltas">
        <span class="pill pill-gold">Coverage uplift: ${
          data.coverage_uplift_pct
        }%</span>
        <span class="pill pill-navy">Runtime overhead: ${fmtMs(
          data.runtime_overhead_ms
        )}</span>
      </div>`;

    const extended = (data.full_results || {})["EXTENDED_EXPLORATION"];
    if (extended) {
      currentExposures = extended.results || [];
      currentPage = 1;
      renderCurrentPage();
    } else {
      currentExposures = [];
      renderCurrentPage();
    }

    const md =
      (data.full_results &&
        data.full_results.EXTENDED_EXPLORATION &&
        data.full_results.EXTENDED_EXPLORATION.scan_metadata) ||
      {};
    resultsMeta.textContent = `All four modes executed · showing EXTENDED_EXPLORATION results below · total runtime ${fmtMs(
      md.runtime_delta_ms
    )}`;
    summaryPills.innerHTML = "";
    resultsCard.scrollIntoView({ behavior: "smooth", block: "start" });

    // run AI analysis on the extended results
    currentAiAnalysis = null;
    aiAnalysisLoading = false;
    aiSummary.classList.add("hidden");
    aiSummary.innerHTML = "";
    if (extended && (extended.results || []).length) {
      runAiAnalysis(extended).catch(() => {});
    }
  }

  // ── page switching ──────────────────────────────────────────────────────────

  let _settingsLoaded = false;

  function switchPage(name) {
    $$(".page-view").forEach((v) => v.classList.remove("active"));
    $$(".main-nav-btn").forEach((b) => b.classList.remove("active"));

    const view = $(`#page-${name}`);
    if (view) view.classList.add("active");

    const btn = $(`.main-nav-btn[data-page="${name}"]`);
    if (btn) btn.classList.add("active");

    // re-render history every time the tab is opened (fetches fresh data from server)
    if (name === "history") renderHistoryPage().catch(() => {});

    // lazy-load settings content first time settings page is shown
    if (name === "settings" && !_settingsLoaded) {
      _settingsLoaded = true;
      loadDevConfig().catch((err) => {
        if (devStatus) devStatus.textContent = `Load failed: ${err.message || err}`;
      });
    }
  }

  // expose globally so inline onclick handlers (e.g. AI error banner) can call it
  window.switchToSettings = function (tab) {
    switchPage("settings");
    if (tab) {
      setTimeout(() => {
        const tabBtn = $(`.devmenu-tab[data-tab="${tab}"]`);
        if (tabBtn) tabBtn.click();
      }, 60);
    }
  };

  $$(".main-nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchPage(btn.getAttribute("data-page")));
  });

  // ── status page refresh button ──────────────────────────────────────────────

  async function refreshSystemStatus() {
    const btn = $("#refresh-status-btn");
    if (btn) { btn.disabled = true; btn.textContent = "↻ Refreshing…"; }
    systemGrid.innerHTML = '<p class="muted small">Refreshing…</p>';
    try {
      const r = await fetch("/api/status/system");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const sys = await r.json();
      renderSystemStatus(sys);
    } catch (err) {
      systemGrid.innerHTML = `<p class="muted small">Refresh failed: ${escHtml(err.message || err)}</p>`;
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "↻ Refresh"; }
    }
  }

  const refreshStatusBtn = $("#refresh-status-btn");
  if (refreshStatusBtn) {
    refreshStatusBtn.addEventListener("click", refreshSystemStatus);
  }

  // ── about modal ─────────────────────────────────────────────────────────────

  function openAbout() {
    const overlay = $("#about-overlay");
    if (overlay) {
      overlay.classList.remove("hidden");
      overlay.scrollTop = 0;
    }
  }

  function closeAbout() {
    const overlay = $("#about-overlay");
    if (overlay) overlay.classList.add("hidden");
  }

  const aboutLink = $("#about-link");
  if (aboutLink) aboutLink.addEventListener("click", (e) => { e.preventDefault(); openAbout(); });

  const aboutClose = $("#about-close");
  if (aboutClose) aboutClose.addEventListener("click", closeAbout);

  const aboutOverlay = $("#about-overlay");
  if (aboutOverlay) {
    aboutOverlay.addEventListener("click", (e) => {
      if (e.target === aboutOverlay) closeAbout();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeAbout();
    }
  });

  // tab switching
  $$(".devmenu-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-tab");
      $$(".devmenu-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      $$(".devmenu-tabpanel").forEach((p) => p.classList.remove("active"));
      const panel = document.querySelector(`[data-tabpanel="${id}"]`);
      if (panel) panel.classList.add("active");
    });
  });

  async function loadDevConfig() {
    const r = await fetch("/api/config");
    if (!r.ok) throw new Error(`GET /api/config → ${r.status}`);
    devConfig = await r.json();
    applyTheme(devConfig.theme || "navy-gold");
    renderThemePicker();
    renderServiceToggles();
    renderPrecisionFlags();
    renderKeyEditors();
    devStatus.textContent = "";
  }

  function renderThemePicker() {
    const themes = devConfig.available_themes || ["navy-gold"];
    const active = devConfig.theme || "navy-gold";
    themePicker.innerHTML = themes
      .map((name) => {
        const meta = THEME_META[name] || {
          bar: "linear-gradient(90deg,#001d51,#ffe3a5)",
          label: name,
          hint: "",
        };
        return `
          <button type="button" class="theme-swatch ${
            name === active ? "active" : ""
          }" data-theme="${escHtml(name)}">
            <div class="theme-swatch-bar" style="background:${meta.bar}"></div>
            <div class="theme-swatch-label">${escHtml(meta.label)}</div>
            <div class="theme-swatch-meta">${escHtml(meta.hint)}</div>
          </button>`;
      })
      .join("");

    themePicker.querySelectorAll(".theme-swatch").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const name = btn.getAttribute("data-theme");
        applyTheme(name);
        themePicker
          .querySelectorAll(".theme-swatch")
          .forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        await patchConfig({ theme: name });
      });
    });
  }

  const THEME_META = {
    "navy-gold": {
      bar: "linear-gradient(90deg,#001d51 0%,#001d51 60%,#ffe3a5 60%)",
      label: "Navy + Gold",
      hint: "Default",
    },
    midnight: {
      bar: "linear-gradient(90deg,#05060f 0%,#05060f 55%,#ffd464 55%)",
      label: "Midnight",
      hint: "High contrast",
    },
    graphite: {
      bar: "linear-gradient(90deg,#2a313c 0%,#2a313c 55%,#d4b784 55%)",
      label: "Graphite",
      hint: "Neutral steel",
    },
    ivory: {
      bar: "linear-gradient(90deg,#8a5a2f 0%,#8a5a2f 40%,#f3e5c8 40%)",
      label: "Ivory",
      hint: "Warm / light",
    },
  };

  function applyTheme(name) {
    if (name === "navy-gold") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", name);
    }
  }

  function renderServiceToggles() {
    const all = devConfig.all_services || [];
    const enabled = devConfig.enabled_services; // null = all on
    serviceToggles.innerHTML = all
      .map((name) => {
        const on = enabled === null || enabled.includes(name);
        return `
          <label class="switch-row">
            <input type="checkbox" data-service="${escHtml(name)}" ${
          on ? "checked" : ""
        } />
            <span>
              <strong>${escHtml(name)}</strong>
            </span>
          </label>`;
      })
      .join("");

    serviceToggles
      .querySelectorAll('input[type="checkbox"]')
      .forEach((cb) => {
        cb.addEventListener("change", async () => {
          const list = Array.from(
            serviceToggles.querySelectorAll('input[type="checkbox"]')
          )
            .filter((x) => x.checked)
            .map((x) => x.getAttribute("data-service"));
          // if every service is checked, send null to collapse to "all"
          const value = list.length === all.length ? null : list;
          await patchConfig({ enabled_services: value });
        });
      });
  }

  function renderPrecisionFlags() {
    // just sync values — listeners are wired once in initPrecisionListeners()
    flagStrictStack.checked = !!devConfig.strict_stack_exchange;
    flagStrictGithub.checked = !!devConfig.strict_github;
    flagPerServiceCap.value = String(devConfig.max_findings_per_service || 0);
    renderModeLimits();
  }

  // ── Mode limits (Scan Limits tab) ────────────────────────────────────────────

  const _MODE_LABELS = {
    API_ONLY:             "API Only",
    HYBRID:               "Hybrid",
    DEEP_SCAN:            "Deep Scan",
    EXTENDED_EXPLORATION: "Extended Exploration",
  };

  const _LIMIT_META = [
    { key: "timeout_seconds",    label: "Timeout",        unit: "s",   min: 1,   max: 3600 },
    { key: "max_search_results", label: "Search results", unit: "max", min: 0,   max: 500  },
    { key: "max_sources",        label: "Pages scraped",  unit: "max", min: 0,   max: 200  },
  ];

  function renderModeLimits() {
    const container = $("#mode-limits");
    if (!container || !devConfig) return;

    const limits    = devConfig.mode_limits        || {};
    const defaults  = devConfig.mode_limit_defaults || {};

    const rows = Object.entries(_MODE_LABELS).map(([modeKey, modeLabel]) => {
      const cur = limits[modeKey]    || {};
      const def = defaults[modeKey]  || {};

      // API_ONLY has no search/scrape budgets — skip those columns
      const isApiOnly = modeKey === "API_ONLY";

      const inputs = _LIMIT_META.map(({ key, label, unit, min, max }) => {
        const val = cur[key] ?? def[key] ?? 0;
        if (isApiOnly && key !== "timeout_seconds") {
          return `<td class="ml-cell ml-na"><span class="muted small">—</span></td>`;
        }
        return `
          <td class="ml-cell">
            <input
              type="number"
              class="ml-input"
              data-mode="${escHtml(modeKey)}"
              data-limit="${escHtml(key)}"
              value="${val}"
              min="${min}"
              max="${max}"
              step="1"
              aria-label="${escHtml(modeLabel)} ${escHtml(label)}"
            />
            <span class="ml-unit muted small">${escHtml(unit)}</span>
          </td>`;
      }).join("");

      const resetBtn = `<td class="ml-cell">
        <button type="button" class="btn btn-ghost btn-small ml-reset"
                data-mode="${escHtml(modeKey)}">Reset</button>
      </td>`;

      return `<tr>
        <td class="ml-mode-label"><strong>${escHtml(modeLabel)}</strong></td>
        ${inputs}
        ${resetBtn}
      </tr>`;
    }).join("");

    const headers = _LIMIT_META.map(m =>
      `<th>${escHtml(m.label)}<span class="muted small"> (${escHtml(m.unit)})</span></th>`
    ).join("");

    container.innerHTML = `
      <div class="ml-table-wrap">
        <table class="ml-table">
          <thead>
            <tr>
              <th>Mode</th>
              ${headers}
              <th></th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;

    // wire input listeners — debounced save on change
    container.querySelectorAll(".ml-input").forEach(input => {
      input.addEventListener("change", () => saveLimitInput(input));
    });

    // reset-to-default buttons
    container.querySelectorAll(".ml-reset").forEach(btn => {
      btn.addEventListener("click", async () => {
        const modeKey = btn.getAttribute("data-mode");
        const def = (devConfig.mode_limit_defaults || {})[modeKey] || {};
        // build a patch that restores all limits for this mode to defaults
        const patch = { mode_limits: { [modeKey]: { ...def } } };
        await patchConfig(patch);
        renderModeLimits();
      });
    });
  }

  async function saveLimitInput(input) {
    const modeKey  = input.getAttribute("data-mode");
    const limitKey = input.getAttribute("data-limit");
    const val      = parseInt(input.value, 10);
    if (!modeKey || !limitKey || !Number.isFinite(val)) return;
    await patchConfig({ mode_limits: { [modeKey]: { [limitKey]: Math.max(0, val) } } });
    renderModeLimits();
  }

  function initPrecisionListeners() {
    flagStrictStack.addEventListener("change", async () => {
      await patchConfig({ strict_stack_exchange: flagStrictStack.checked });
    });
    flagStrictGithub.addEventListener("change", async () => {
      await patchConfig({ strict_github: flagStrictGithub.checked });
    });
    flagPerServiceCap.addEventListener("change", async () => {
      const n = parseInt(flagPerServiceCap.value, 10);
      await patchConfig({
        max_findings_per_service: Number.isFinite(n) ? Math.max(0, n) : 0,
      });
    });
  }

  function renderKeyEditors() {
    const names = devConfig.overridable_keys || [];
    const fromEnv = devConfig.api_keys_from_env || {};
    const masked = devConfig.api_keys_masked || {};

    keyEditors.innerHTML = names
      .map((name) => {
        const hasOverride = !!masked[name];
        const hasEnv = !!fromEnv[name];
        let sourceLabel = "unset";
        let sourceClass = "";
        if (hasOverride) {
          sourceLabel = "runtime override";
          sourceClass = "override";
        } else if (hasEnv) {
          sourceLabel = "from env";
          sourceClass = "env";
        }
        return `
          <div class="key-editor" data-key="${escHtml(name)}">
            <div class="key-editor-row">
              <span class="key-editor-name">${escHtml(name)}</span>
              <span class="key-editor-source ${sourceClass}">${escHtml(
          sourceLabel
        )}</span>
            </div>
            <div class="key-editor-input-row">
              <input
                class="key-editor-input"
                type="password"
                placeholder="${hasOverride ? "overridden — enter new value to replace" : "Paste key to override env"}"
                autocomplete="off"
              />
              <button type="button" class="btn btn-primary btn-small key-editor-btn js-save">Save</button>
              <button type="button" class="btn btn-ghost btn-small key-editor-btn js-clear">Clear</button>
            </div>
          </div>`;
      })
      .join("");

    keyEditors.querySelectorAll(".key-editor").forEach((row) => {
      const name = row.getAttribute("data-key");
      const input = row.querySelector(".key-editor-input");
      row.querySelector(".js-save").addEventListener("click", async () => {
        const val = input.value || "";
        if (!val) {
          devStatus.textContent = "Enter a key value to save.";
          return;
        }
        try {
          const r = await fetch(
            `/api/config/keys/${encodeURIComponent(name)}`,
            {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ value: val }),
            }
          );
          if (!r.ok) throw await errorFrom(r);
          devConfig = await r.json();
          renderKeyEditors();
          devStatus.textContent = `Saved ${name}.`;
        } catch (err) {
          devStatus.textContent = `Save failed: ${err.message || err}`;
        }
      });
      row.querySelector(".js-clear").addEventListener("click", async () => {
        try {
          const r = await fetch(
            `/api/config/keys/${encodeURIComponent(name)}`,
            { method: "DELETE" }
          );
          if (!r.ok) throw await errorFrom(r);
          devConfig = await r.json();
          renderKeyEditors();
          devStatus.textContent = `Cleared ${name}.`;
        } catch (err) {
          devStatus.textContent = `Clear failed: ${err.message || err}`;
        }
      });
    });
  }

  async function patchConfig(patch) {
    try {
      const r = await fetch("/api/config", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!r.ok) throw await errorFrom(r);
      devConfig = await r.json();
      devStatus.textContent = "Saved.";
      // sync precision flag display values after any patch
      renderPrecisionFlags();
    } catch (err) {
      devStatus.textContent = `Save failed: ${err.message || err}`;
    }
  }

  // apply the persisted theme as early as possible so there's no flash of the
  // default on reload before the splash finishes
  (async function applyPersistedThemeEarly() {
    try {
      const r = await fetch("/api/config");
      if (r.ok) {
        const cfg = await r.json();
        applyTheme(cfg.theme || "navy-gold");
      }
    } catch {
      /* ignore — splash will retry */
    }
  })();

  // boot

  document.addEventListener("DOMContentLoaded", () => {
    initPrecisionListeners(); // wire precision flag handlers once
    runSplashBoot().catch((err) => {
      splashFootnote.textContent = `Boot error: ${err.message || err}`;
      startContinueCountdown(5, "Continue");
    });
  });
})();
