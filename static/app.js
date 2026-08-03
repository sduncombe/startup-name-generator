(() => {
  const state = {
    runId: null,
    candidates: [],
    run: null,
    sortKey: "total_score",
    sortDir: "desc",
  };

  const $ = (id) => document.getElementById(id);
  const tbody = document.querySelector("#results tbody");

  function setBusy(busy, label = "") {
    const progress = $("progress");
    progress.hidden = false;
    progress.dataset.busy = busy ? "true" : "false";
    $("status").textContent = label;
  }

  function setIdleMessage(msg) {
    const progress = $("progress");
    progress.hidden = !msg;
    progress.dataset.busy = "false";
    $("status").textContent = msg || "";
  }

  function domainStatus(c, ext) {
    return ((c.domains || {})[ext] || {}).status || "";
  }

  function bestDomainSummary(c) {
    const order = [".com", ".app", ".co"];
    const parts = [];
    for (const ext of order) {
      const st = domainStatus(c, ext);
      // Skip transient lookup errors (noise, not signal)
    if (st && st !== "error") parts.push({ ext, st });
    }
    if (!parts.length) return "-";
    return parts
      .map((p) => `<span class="status-pill ${p.st}">${p.ext} ${p.st}</span>`)
      .join("");
  }

  function riskRank(c) {
    const r = String(c.trademark_risk || "");
    if (r === "high") return 3;
    if (r === "medium") return 2;
    if (r === "low") return 1;
    return 0;
  }

  function scoreOf(c, key) {
    if (key === "total_score") return Number(c.total_score || 0);
    if (key === "name") return String(c.name || "").toLowerCase();
    if (key === "conflict_level") return String(c.conflict_level || "");
    if (key === "trademark_risk" || key === "risk") return riskRank(c);
    if (key === "radio_result") return String(c.radio_result || "");
    if (key === "favorite") return c.favorite ? 1 : 0;
    if (key === "com") return domainStatus(c, ".com");
    return 0;
  }

  function isUsable(c) {
    const comOk = domainStatus(c, ".com") === "available";
    const anyOk = Object.values(c.domains || {}).some((d) => d.status === "available");
    const conflictOk =
      !c.conflict_level ||
      c.conflict_level === "Not checked" ||
      String(c.conflict_level).startsWith("Low");
    const radioOk = !c.radio_result || c.radio_result === "pass";
    const tmOk = c.trademark_risk !== "high";
    return (comOk || anyOk) && conflictOk && radioOk && tmOk;
  }

  function filtered() {
    const q = $("search").value.trim().toLowerCase();
    const usableOnly = $("filterUsable").checked;
    let rows = state.candidates.slice();
    rows = rows.filter((c) => {
      if (usableOnly && !isUsable(c)) return false;
      if (
        q &&
        !String(c.name).toLowerCase().includes(q) &&
        !String(c.pronunciation).toLowerCase().includes(q)
      ) {
        return false;
      }
      return true;
    });
    rows.sort((a, b) => {
      const av = scoreOf(a, state.sortKey);
      const bv = scoreOf(b, state.sortKey);
      if (av < bv) return state.sortDir === "asc" ? -1 : 1;
      if (av > bv) return state.sortDir === "asc" ? 1 : -1;
      return String(a.name).localeCompare(String(b.name));
    });
    return rows;
  }

  function trademarkLabel(c) {
    if (!c.trademark_risk) return "Not checked";
    return c.trademark_summary || "None found";
  }

  function riskCell(c) {
    const r = String(c.trademark_risk || "");
    if (!r) return "<span class='risk-badge'>-</span>";
    const label = r.charAt(0).toUpperCase() + r.slice(1);
    return `<span class="risk-badge risk-${r}"><span class="risk-dot"></span>${label}</span>`;
  }

  function radioLabel(c) {
    if (!c.radio_result) return "-";
    const score = c.radio_score == null ? "" : ` ${Number(c.radio_score).toFixed(0)}`;
    return `${c.radio_result}${score}`;
  }

  function notesFor(c) {
    const bits = [];
    if (c.trademark_reason && c.trademark_risk !== "low") bits.push(c.trademark_reason);
    if (c.radio_explanation) bits.push(c.radio_explanation);
    if (c.conflict_notes) bits.push(c.conflict_notes);
    const alts = (c.radio_spellings || []).join(", ");
    if (alts) bits.push(`Also: ${alts}`);
    return bits.join(" · ") || "-";
  }

  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function escapeAttr(str) {
    return escapeHtml(str).replaceAll("'", "&#39;");
  }

  function renderDirections(run, candidates) {
    const box = $("directions");
    const dirs = (run && run.llm && run.llm.directions) || [];
    const rows = candidates || [];
    if (!rows.length) {
      box.innerHTML = "";
      return;
    }

    const byDir = new Map();
    for (const d of dirs) {
      const name = d.name || "Ideas";
      byDir.set(name, { name, description: d.description || "", names: [] });
    }
    for (const c of rows) {
      const label = c.direction || "Other ideas";
      if (!byDir.has(label)) {
        byDir.set(label, {
          name: label,
          description: c.direction_description || "",
          names: [],
        });
      }
      byDir.get(label).names.push(c);
    }

    const cards = [...byDir.values()]
      .sort((a, b) => (a.name === "Other ideas") - (b.name === "Other ideas"))
      .map((d) => {
        const top = d.names
          .slice()
          .sort((a, b) => Number(b.total_score || 0) - Number(a.total_score || 0))
          .slice(0, 5);
        if (!top.length) return "";
        const items = top
          .map((c) => {
            const com = domainStatus(c, ".com");
            const hint = com ? `.com ${com}` : `${Number(c.total_score || 0).toFixed(0)}`;
            return `<li><strong>${escapeHtml(c.name)}</strong><span class="mini">${escapeHtml(hint)}</span></li>`;
          })
          .join("");
        return `<article class="direction-card">
          <h3>${escapeHtml(d.name)}</h3>
          <p class="dir-desc">${escapeHtml(d.description || "")}</p>
          <ul class="direction-names">${items}</ul>
        </article>`;
      })
      .filter(Boolean);

    box.innerHTML = cards.join("");
  }

  function renderTable() {
    const rows = filtered();
    tbody.innerHTML = rows
      .map(
        (c) => `<tr>
        <td class="fav ${c.favorite ? "on" : ""}" data-name="${escapeAttr(c.name)}">${c.favorite ? "★" : "☆"}</td>
        <td class="name-cell"><strong>${escapeHtml(c.name)}</strong><div class="pron">${escapeHtml(c.pronunciation || "")}</div></td>
        <td>${Number(c.total_score || 0).toFixed(1)}</td>
        <td><div class="domain-stack">${bestDomainSummary(c)}</div></td>
        <td class="tm-cell" title="${escapeAttr(c.trademark_reason || "")}">${escapeHtml(trademarkLabel(c))}</td>
        <td title="${escapeAttr(c.trademark_reason || "")}">${riskCell(c)}</td>
        <td class="radio-${c.radio_result || ""}" title="${escapeAttr(c.radio_explanation || "")}">${escapeHtml(radioLabel(c))}</td>
        <td class="notes">${escapeHtml(notesFor(c))}</td>
      </tr>`,
      )
      .join("");
    $("count").textContent = `${rows.length} of ${state.candidates.length}`;
  }

  const BYOK = {
    provider: "sng_llm_provider",
    key: "sng_llm_key",
    model: "sng_llm_model",
  };

  function readByok() {
    return {
      provider: sessionStorage.getItem(BYOK.provider) || $("llmProvider").value || "anthropic",
      key: sessionStorage.getItem(BYOK.key) || "",
      model: sessionStorage.getItem(BYOK.model) || "",
    };
  }

  function persistByokFromFields() {
    const provider = $("llmProvider").value;
    const key = $("llmKey").value.trim();
    const model = $("llmModel").value.trim();
    sessionStorage.setItem(BYOK.provider, provider);
    if (key) sessionStorage.setItem(BYOK.key, key);
    if (model) sessionStorage.setItem(BYOK.model, model);
    else sessionStorage.removeItem(BYOK.model);
    refreshByokStatus();
  }

  function refreshByokStatus() {
    const { provider, key, model } = readByok();
    $("llmProvider").value = provider;
    if (!$("llmKey").value) $("llmModel").value = model;
    $("byokStatus").textContent = key ? `Key set · ${provider}` : "No key";
  }

  function llmHeaders() {
    const { provider, key, model } = readByok();
    const headers = {};
    if (key) {
      headers["X-LLM-Provider"] = provider;
      headers["X-LLM-API-Key"] = key;
      if (model) headers["X-LLM-Model"] = model;
    }
    return headers;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch (_) { /* ignore */ }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  }

  function showResults() {
    document.body.classList.add("has-results");
    $("resultsSection").hidden = false;
  }

  function setActiveRun(run, candidates) {
    state.runId = run.id;
    state.run = run;
    state.candidates = candidates || [];
    const exportBtn = $("btnExport");
    exportBtn.href = `/api/runs/${run.id}/export.csv`;
    exportBtn.hidden = false;
    showResults();
    renderDirections(run, state.candidates);
    renderTable();
  }

  async function loadRun(runId) {
    setBusy(true, "Loading session…");
    try {
      const data = await api(`/api/runs/${runId}`);
      setActiveRun(data.run, data.candidates || []);
      setIdleMessage(`${state.candidates.length} names`);
    } catch (err) {
      setIdleMessage(`Couldn’t load session: ${err.message}`);
    }
  }

  async function refreshRuns() {
    const data = await api("/api/runs");
    const list = $("runList");
    list.innerHTML =
      (data.runs || [])
        .map((r) => {
          const label = escapeHtml(r.problem || r.building || r.category || r.id);
          return `<li data-id="${r.id}">${label} <span class="hint">· ${escapeHtml(r.status)}</span></li>`;
        })
        .join("") || "<li class='hint'>No previous sessions</li>";
  }

  async function generate() {
    persistByokFromFields();
    const fd = new FormData($("runForm"));
    const domainTop = 40;
    const conflictTop = 40;
    const trademarkTop = 40;
    const payload = {
      problem: String(fd.get("problem") || ""),
      audience: String(fd.get("audience") || ""),
      liked_brands: String(fd.get("liked_brands") || ""),
      avoid: String(fd.get("avoid") || ""),
      primary_language: String(fd.get("primary_language") || "en-global"),
      primary_language_other: String(fd.get("primary_language_other") || ""),
      naming_style: String(fd.get("naming_style") || "brandable"),
      max_length: Number(fd.get("max_length")),
      generate_count: Number(fd.get("generate_count")),
      extensions: String(fd.get("extensions") || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      domain_check_top: domainTop,
      conflict_check_top: conflictTop,
      trademark_check_top: trademarkTop,
      run_pipeline: false,
    };

    try {
      $("btnCreate").disabled = true;
      setBusy(true, "Generating names…");

      const created = await api("/api/runs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const runId = created.run.id;

      setBusy(true, "Scoring and radio-testing…");
      const gen = await api(`/api/runs/${runId}/generate`, {
        method: "POST",
        body: "{}",
        headers: llmHeaders(),
      });

      setBusy(true, "Checking domains…");
      await api(`/api/runs/${runId}/check-domains`, {
        method: "POST",
        body: JSON.stringify({ top_n: domainTop, resume: true }),
      });

      setBusy(true, "Checking conflicts…");
      await api(`/api/runs/${runId}/check-conflicts`, {
        method: "POST",
        body: JSON.stringify({ top_n: conflictTop }),
      });

      setBusy(true, "Screening trademarks…");
      await api(`/api/runs/${runId}/check-trademarks`, {
        method: "POST",
        body: JSON.stringify({ top_n: trademarkTop }),
      });

      setBusy(true, "Preparing results…");
      const data = await api(`/api/runs/${runId}`);
      setActiveRun(data.run, data.candidates || []);
      await refreshRuns();

      const r = gen.result || {};
      const bits = [`${state.candidates.length} names`];
      if (r.llm) bits.push(`${r.llm} from AI`);
      setIdleMessage(bits.join(" · "));
      $("problem").blur();
    } catch (err) {
      setIdleMessage(`Something went wrong: ${err.message}`);
    } finally {
      $("btnCreate").disabled = false;
    }
  }

  $("runForm").addEventListener("submit", (e) => {
    e.preventDefault();
    generate();
  });

  // ⌘⏎ / Ctrl+Enter submits from anywhere in the form
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (!$("btnCreate").disabled && $("problem").value.trim()) generate();
    }
  });

  // Chips toggle the disclosure drawers
  document.querySelectorAll(".chip[data-toggle]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const drawer = $(chip.dataset.toggle);
      drawer.open = !drawer.open;
      chip.classList.toggle("active", drawer.open);
    });
  });

  tbody.addEventListener("click", async (e) => {
    const cell = e.target.closest(".fav");
    if (!cell || !state.runId) return;
    const name = cell.dataset.name;
    const currently = cell.classList.contains("on");
    try {
      await api(`/api/runs/${state.runId}/favorite`, {
        method: "POST",
        body: JSON.stringify({ name, favorite: !currently }),
      });
      const row = state.candidates.find((c) => c.name === name);
      if (row) row.favorite = !currently;
      renderDirections(state.run, state.candidates);
      renderTable();
    } catch (err) {
      setIdleMessage(`Couldn’t update favorite: ${err.message}`);
    }
  });

  document.querySelectorAll("#results thead th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = key === "name" ? "asc" : "desc";
      }
      renderTable();
    });
  });

  ["search", "filterUsable"].forEach((id) => {
    $(id).addEventListener("input", renderTable);
    $(id).addEventListener("change", renderTable);
  });

  $("runList").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-id]");
    if (!li) return;
    loadRun(li.dataset.id);
  });

  // Key autosaves on change/blur; no separate Save control
  ["llmKey", "llmProvider", "llmModel"].forEach((id) => {
    $(id).addEventListener("change", persistByokFromFields);
    $(id).addEventListener("blur", persistByokFromFields);
  });
  $("llmKey").addEventListener("input", () => {
    if ($("llmKey").value.trim().length > 8) persistByokFromFields();
  });

  $("btnClearKey").addEventListener("click", () => {
    sessionStorage.removeItem(BYOK.provider);
    sessionStorage.removeItem(BYOK.key);
    sessionStorage.removeItem(BYOK.model);
    $("llmKey").value = "";
    $("llmModel").value = "";
    refreshByokStatus();
    setIdleMessage("AI key cleared");
  });

  async function showTrademarkDatasetNote() {
    try {
      const health = await api("/api/health");
      const ds = health.trademark_dataset || {};
      const note = $("tmDataNote");
      if (ds.sample) {
        note.textContent =
          `Trademark screening currently uses a small built-in sample dataset (${ds.marks} well-known marks) for demonstration only. ` +
          "It does not search the USPTO register. To screen against real USPTO data, import the official bulk dataset (see README).";
        note.hidden = false;
      } else if (ds.name) {
        note.textContent = `Trademark screening dataset: ${ds.name} (${ds.marks} marks).`;
        note.hidden = false;
      }
    } catch (_) { /* non-critical */ }
  }

  // Heroicons v2 outline (MIT) — https://heroicons.com
  const LANG_ICONS = {
    "globe-alt":
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 4.582M12 3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0 1 12 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 0 1 3 12c0-1.605.42-3.113 1.157-4.418"/></svg>',
    language:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m10.5 21 5.25-11.25L21 21m-9-3h7.5M3 5.621a48.474 48.474 0 0 1 6-.371m0 0c1.12 0 2.233.038 3.334.114M9 5.25V3m3.334 2.364C11.176 10.658 7.69 15.08 3 17.502m9.334-12.138c.896.061 1.785.147 2.666.257m-4.589 8.495a18.023 18.023 0 0 1-3.827-5.802"/></svg>',
    ellipsis:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>',
  };

  function paintLangIcons() {
    document.querySelectorAll(".market-icon[data-icon]").forEach((el) => {
      const key = el.dataset.icon;
      el.innerHTML = LANG_ICONS[key] || LANG_ICONS.language;
    });
  }

  function setLanguageValue(value, label, icon) {
    $("primaryLanguage").value = value;
    $("languageTriggerLabel").textContent = label;
    $("languageTriggerIcon").innerHTML = LANG_ICONS[icon || "language"] || LANG_ICONS.language;
    $("languageMenu").querySelectorAll('[role="option"]').forEach((opt) => {
      opt.setAttribute("aria-selected", opt.dataset.value === value ? "true" : "false");
    });
    syncLanguageOther();
  }

  function syncLanguageOther() {
    const other = $("primaryLanguage").value === "other";
    $("primaryLanguageOtherField").hidden = !other;
    if (!other) $("primaryLanguageOther").value = "";
  }

  function closeLanguageMenu() {
    const picker = $("languagePicker");
    picker.classList.remove("open");
    $("languageTrigger").setAttribute("aria-expanded", "false");
    $("languageMenu").hidden = true;
  }

  function openLanguageMenu() {
    const picker = $("languagePicker");
    picker.classList.add("open");
    $("languageTrigger").setAttribute("aria-expanded", "true");
    $("languageMenu").hidden = false;
  }

  paintLangIcons();
  setLanguageValue("en-global", "English (Global)", "globe-alt");

  $("languageTrigger").addEventListener("click", () => {
    if ($("languageMenu").hidden) openLanguageMenu();
    else closeLanguageMenu();
  });

  $("languageMenu").addEventListener("click", (e) => {
    const opt = e.target.closest('[role="option"]');
    if (!opt) return;
    setLanguageValue(opt.dataset.value, opt.dataset.label, opt.dataset.icon);
    closeLanguageMenu();
  });

  document.addEventListener("click", (e) => {
    if (!$("languagePicker").contains(e.target)) closeLanguageMenu();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("languageMenu").hidden) {
      closeLanguageMenu();
      $("languageTrigger").focus();
    }
  });


  refreshByokStatus();
  $("progress").hidden = true;
  refreshRuns().catch(() => {});
  showTrademarkDatasetNote();
})();
