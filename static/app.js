(() => {
  const state = {
    runId: null,
    candidates: [],
    run: null,
    sortKey: "total_score",
    sortDir: "desc",
  };

  const $ = (id) => document.getElementById(id);
  const statusEl = $("status");
  const tbody = document.querySelector("#results tbody");

  function setStatus(msg) {
    statusEl.textContent = msg;
  }

  function slugLen(name) {
    return String(name || "").replace(/[^a-zA-Z0-9]/g, "").length;
  }

  function domainStatus(c, ext) {
    return ((c.domains || {})[ext] || {}).status || "";
  }

  function scoreOf(c, key) {
    if (key === "total_score") return Number(c.total_score || 0);
    if (key === "radio_score") return Number(c.radio_score ?? -1);
    if (key === "name") return String(c.name || "").toLowerCase();
    if (key === "pronunciation") return String(c.pronunciation || "").toLowerCase();
    if (key === "conflict_level") return String(c.conflict_level || "");
    if (key === "method") return String(c.method || "");
    if (key === "radio_result") return String(c.radio_result || "");
    if (key === "radio_spellings") return (c.radio_spellings || []).join(",");
    if (key === "favorite") return c.favorite ? 1 : 0;
    if (key === "com") return domainStatus(c, ".com");
    if (key === "app") return domainStatus(c, ".app");
    if (key === "co") return domainStatus(c, ".co");
    return Number((c.scores || {})[key] || 0);
  }

  function filtered() {
    const q = $("search").value.trim().toLowerCase();
    const minScore = Number($("minScore").value || 0);
    const maxChars = Number($("maxChars").value || 20);
    const needCom = $("filterCom").checked;
    const needAny = $("filterAny").checked;
    const lowOnly = $("filterLow").checked;
    const llmOnly = $("filterLlm").checked;
    const radioPass = $("filterRadioPass").checked;
    const favOnly = $("filterFav").checked;

    let rows = state.candidates.slice();
    rows = rows.filter((c) => {
      if (favOnly && !c.favorite) return false;
      if (llmOnly && c.method !== "llm") return false;
      if (radioPass && c.radio_result !== "pass") return false;
      if (Number(c.total_score || 0) < minScore) return false;
      if (slugLen(c.name) > maxChars) return false;
      if (q && !String(c.name).toLowerCase().includes(q) && !String(c.pronunciation).toLowerCase().includes(q)) {
        return false;
      }
      if (needCom && domainStatus(c, ".com") !== "available") return false;
      if (needAny) {
        const statuses = Object.values(c.domains || {}).map((d) => d.status);
        if (!statuses.includes("available")) return false;
      }
      if (lowOnly && !String(c.conflict_level || "").startsWith("Low")) return false;
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

  function pill(status) {
    const s = status || "—";
    return `<span class="status-pill ${status || "unknown"}">${s}</span>`;
  }

  function conflictClass(level) {
    if (String(level).startsWith("High")) return "conflict-high";
    if (String(level).startsWith("Possible")) return "conflict-possible";
    if (String(level).startsWith("Low")) return "conflict-low";
    return "";
  }

  function renderDirections(run) {
    const box = $("llmBox");
    const list = $("llmDirections");
    const dirs = (run && run.llm && run.llm.directions) || [];
    if (!dirs.length) {
      box.hidden = true;
      list.innerHTML = "";
      return;
    }
    box.hidden = false;
    list.innerHTML = dirs.map((d) => {
      return `<li><strong>${escapeHtml(d.name || "")}</strong> — ${escapeHtml(d.description || "")}</li>`;
    }).join("");
  }

  function renderTable() {
    const rows = filtered();
    tbody.innerHTML = rows.map((c) => {
      const spellings = (c.radio_spellings || []).join(", ") || "—";
      const radioScore = c.radio_score == null ? "—" : Number(c.radio_score).toFixed(0);
      const radioResult = c.radio_result || "—";
      const sourceClass = c.method === "llm" ? "src-llm" : "src-local";
      return `<tr>
        <td class="fav ${c.favorite ? "on" : ""}" data-name="${escapeAttr(c.name)}">${c.favorite ? "★" : "☆"}</td>
        <td><strong>${escapeHtml(c.name)}</strong></td>
        <td>${escapeHtml(c.pronunciation || "")}</td>
        <td>${Number(c.total_score || 0).toFixed(1)}</td>
        <td><span class="src ${sourceClass}">${escapeHtml(c.method || "")}</span></td>
        <td>${radioScore}</td>
        <td class="radio-${radioResult}">${escapeHtml(radioResult)}</td>
        <td class="spellings" title="${escapeAttr(c.radio_explanation || "")}">${escapeHtml(spellings)}</td>
        <td>${pill(domainStatus(c, ".com"))}</td>
        <td>${pill(domainStatus(c, ".app"))}</td>
        <td>${pill(domainStatus(c, ".co"))}</td>
        <td class="${conflictClass(c.conflict_level)}">${escapeHtml(c.conflict_level || "")}</td>
        <td>${escapeHtml(c.conflict_notes || c.radio_explanation || "")}</td>
      </tr>`;
    }).join("");
    const llmCount = state.candidates.filter((c) => c.method === "llm").length;
    $("count").textContent = `${rows.length} shown / ${state.candidates.length} total (${llmCount} llm)`;
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

  function refreshByokStatus() {
    const { provider, key, model } = readByok();
    $("llmProvider").value = provider;
    $("llmModel").value = model;
    // Never re-populate the password field from storage into a copyable visible value
    // beyond the masked input the user just typed; show status only.
    $("byokStatus").textContent = key
      ? `AI key: set for this session (${provider}${model ? ", " + model : ""})`
      : "AI key: not set — AI naming disabled until you paste a key";
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
      throw new Error(detail);
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  }

  function setActiveRun(run) {
    state.runId = run.id;
    state.run = run;
    const llmBit = run.llm && run.llm.count != null ? ` · llm ${run.llm.count}` : "";
    $("runMeta").textContent = `Run ${run.id} · ${run.status}${llmBit} · ${run.category}`;
    $("btnDomains").disabled = false;
    $("btnConflicts").disabled = false;
    const exportBtn = $("btnExport");
    exportBtn.href = `/api/runs/${run.id}/export.csv`;
    exportBtn.classList.remove("disabled");
    renderDirections(run);
  }

  async function loadRun(runId) {
    setStatus(`Loading run ${runId}…`);
    const data = await api(`/api/runs/${runId}`);
    setActiveRun(data.run);
    state.candidates = data.candidates || [];
    renderTable();
    const llm = data.run.llm || {};
    const err = llm.error ? ` LLM note: ${llm.error}` : "";
    setStatus(`Loaded ${state.candidates.length} candidates (${state.candidates.filter((c) => c.method === "llm").length} llm). Status: ${data.run.status}.${err}`);
  }

  async function refreshRuns() {
    const data = await api("/api/runs");
    const list = $("runList");
    list.innerHTML = (data.runs || []).map((r) => {
      const brief = r.brand_brief ? " · brief" : "";
      return `<li data-id="${r.id}"><strong>${escapeHtml(r.id)}</strong> — ${escapeHtml(r.category)} <span class="hint">(${escapeHtml(r.status)}${brief})</span></li>`;
    }).join("") || "<li class='hint'>No saved runs yet</li>";
  }

  $("runForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = {
      category: fd.get("category"),
      keywords: String(fd.get("keywords") || ""),
      tone: fd.get("tone"),
      brand_brief: String(fd.get("brand_brief") || ""),
      max_length: Number(fd.get("max_length")),
      generate_count: Number(fd.get("generate_count")),
      extensions: String(fd.get("extensions") || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      domain_check_top: Number(fd.get("domain_check_top")),
      conflict_check_top: Number(fd.get("conflict_check_top")),
    };

    try {
      $("btnCreate").disabled = true;
      setStatus("Creating run…");
      const created = await api("/api/runs", { method: "POST", body: JSON.stringify(payload) });
      setActiveRun(created.run);
      const byok = readByok();
      if (payload.brand_brief && !byok.key) {
        setStatus("Generating locally (AI skipped — no session key). Add a BYOK key to include LLM names.");
      } else if (payload.brand_brief && byok.key) {
        setStatus(`Generating local names + AI names via ${byok.provider} (BYOK)…`);
      } else {
        setStatus(`Generating ${payload.generate_count} names (local only)…`);
      }
      const gen = await api(`/api/runs/${created.run.id}/generate`, {
        method: "POST",
        body: "{}",
        headers: llmHeaders(),
      });
      await loadRun(created.run.id);
      await refreshRuns();
      const r = gen.result || {};
      setStatus(
        `Done. Total ${r.generated || 0} (local ${r.local || 0}, llm ${r.llm || 0}), radio-tested ${r.radio_tested || 0}.` +
          (r.llm_error ? ` LLM: ${r.llm_error}` : ""),
      );
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    } finally {
      $("btnCreate").disabled = false;
    }
  });

  $("btnDomains").addEventListener("click", async () => {
    if (!state.runId) return;
    const top = Number(document.querySelector('[name="domain_check_top"]').value || 50);
    try {
      $("btnDomains").disabled = true;
      setStatus(`Checking domains for top ${top}…`);
      const result = await api(`/api/runs/${state.runId}/check-domains`, {
        method: "POST",
        body: JSON.stringify({ top_n: top, resume: true }),
      });
      await loadRun(state.runId);
      setStatus(`Domain check done. Checked ${result.result.checked}, skipped ${result.result.skipped}.`);
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    } finally {
      $("btnDomains").disabled = false;
    }
  });

  $("btnConflicts").addEventListener("click", async () => {
    if (!state.runId) return;
    const top = Number(document.querySelector('[name="conflict_check_top"]').value || 50);
    try {
      $("btnConflicts").disabled = true;
      setStatus(`Conflict-scanning top ${top}…`);
      await api(`/api/runs/${state.runId}/check-conflicts`, {
        method: "POST",
        body: JSON.stringify({ top_n: top }),
      });
      await loadRun(state.runId);
      setStatus("Conflict scan complete (local brand list — not a legal opinion).");
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    } finally {
      $("btnConflicts").disabled = false;
    }
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
      renderTable();
    } catch (err) {
      setStatus(`Error: ${err.message}`);
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

  ["search", "filterCom", "filterAny", "filterLow", "filterLlm", "filterRadioPass", "filterFav", "minScore", "maxChars"].forEach((id) => {
    $(id).addEventListener("input", renderTable);
    $(id).addEventListener("change", renderTable);
  });

  $("runList").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-id]");
    if (!li) return;
    loadRun(li.dataset.id).catch((err) => setStatus(`Error: ${err.message}`));
  });

  $("btnSaveKey").addEventListener("click", () => {
    const provider = $("llmProvider").value;
    const key = $("llmKey").value.trim();
    const model = $("llmModel").value.trim();
    if (!key) {
      setStatus("Paste an API key before saving.");
      return;
    }
    sessionStorage.setItem(BYOK.provider, provider);
    sessionStorage.setItem(BYOK.key, key);
    if (model) sessionStorage.setItem(BYOK.model, model);
    else sessionStorage.removeItem(BYOK.model);
    $("llmKey").value = "";
    refreshByokStatus();
    setStatus(`Saved ${provider} key in sessionStorage for this browser tab. Clear key removes it.`);
  });

  $("btnClearKey").addEventListener("click", () => {
    sessionStorage.removeItem(BYOK.provider);
    sessionStorage.removeItem(BYOK.key);
    sessionStorage.removeItem(BYOK.model);
    $("llmKey").value = "";
    $("llmModel").value = "";
    refreshByokStatus();
    setStatus("Cleared AI key from this browser session.");
  });

  $("llmProvider").addEventListener("change", () => {
    const existing = sessionStorage.getItem(BYOK.key);
    if (existing) sessionStorage.setItem(BYOK.provider, $("llmProvider").value);
    refreshByokStatus();
  });

  refreshByokStatus();

  api("/api/health")
    .then((h) => {
      const mode = h.byok_required === false ? "private (server keys allowed)" : "public BYOK";
      setStatus(`Ready. Mode: ${mode}. Providers: ${(h.providers || []).join(", ")}.`);
    })
    .catch(() => setStatus("Ready."));

  refreshRuns().catch((err) => setStatus(`Error loading runs: ${err.message}`));
})();
