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

  function bestDomainSummary(c) {
    const order = [".com", ".app", ".co"];
    const parts = [];
    for (const ext of order) {
      const st = domainStatus(c, ext);
      if (st) parts.push({ ext, st });
    }
    if (!parts.length) return "—";
    return parts
      .map((p) => `<span class="status-pill ${p.st}">${p.ext} ${p.st}</span>`)
      .join(" ");
  }

  function scoreOf(c, key) {
    if (key === "total_score") return Number(c.total_score || 0);
    if (key === "radio_score") return Number(c.radio_score ?? -1);
    if (key === "name") return String(c.name || "").toLowerCase();
    if (key === "conflict_level") return String(c.conflict_level || "");
    if (key === "method") return String(c.method || "");
    if (key === "radio_result") return String(c.radio_result || "");
    if (key === "favorite") return c.favorite ? 1 : 0;
    if (key === "com") return domainStatus(c, ".com");
    return Number((c.scores || {})[key] || 0);
  }

  function filtered() {
    const q = $("search").value.trim().toLowerCase();
    const minScore = Number($("minScore").value || 0);
    const needCom = $("filterCom").checked;
    const needAny = $("filterAny").checked;
    const lowOnly = $("filterLow").checked;
    const radioPass = $("filterRadioPass").checked;
    const favOnly = $("filterFav").checked;

    let rows = state.candidates.slice();
    rows = rows.filter((c) => {
      if (favOnly && !c.favorite) return false;
      if (radioPass && c.radio_result !== "pass") return false;
      if (Number(c.total_score || 0) < minScore) return false;
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

  function conflictClass(level) {
    if (String(level).startsWith("High")) return "conflict-high";
    if (String(level).startsWith("Possible")) return "conflict-possible";
    if (String(level).startsWith("Low")) return "conflict-low";
    return "";
  }

  function radioLabel(c) {
    if (!c.radio_result) return "—";
    const score = c.radio_score == null ? "" : ` ${Number(c.radio_score).toFixed(0)}`;
    return `${c.radio_result}${score}`;
  }

  function notesFor(c) {
    const bits = [];
    if (c.radio_explanation) bits.push(c.radio_explanation);
    if (c.conflict_notes) bits.push(c.conflict_notes);
    const alts = (c.radio_spellings || []).join(", ");
    if (alts) bits.push(`Also sounds like: ${alts}`);
    return bits.join(" · ") || "—";
  }

  function renderDirections(run, candidates) {
    const box = $("directions");
    const dirs = (run && run.llm && run.llm.directions) || [];
    const rows = candidates || [];
    if (!dirs.length && !rows.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }

    const byDir = new Map();
    for (const d of dirs) {
      const name = d.name || "Ideas";
      byDir.set(name, {
        name,
        description: d.description || "",
        names: [],
      });
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
      .map((d) => {
        const top = d.names
          .slice()
          .sort((a, b) => Number(b.total_score || 0) - Number(a.total_score || 0))
          .slice(0, 5);
        if (!top.length) return "";
        const items = top
          .map((c) => {
            const com = domainStatus(c, ".com");
            const hint = com ? `.com ${com}` : `score ${Number(c.total_score || 0).toFixed(0)}`;
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

    box.hidden = !cards.length;
    box.innerHTML = cards.length
      ? `<div class="results-head"><h2>Naming directions</h2><p class="hint">Creative paths first — details below.</p></div>${cards.join("")}`
      : "";
  }

  function renderTable() {
    const rows = filtered();
    tbody.innerHTML = rows
      .map((c) => {
        const sourceClass = c.method === "llm" ? "src-llm" : "src-local";
        return `<tr>
        <td class="fav ${c.favorite ? "on" : ""}" data-name="${escapeAttr(c.name)}">${c.favorite ? "★" : "☆"}</td>
        <td><strong>${escapeHtml(c.name)}</strong><div class="mini hint">${escapeHtml(c.pronunciation || "")}</div></td>
        <td>${Number(c.total_score || 0).toFixed(1)}</td>
        <td><div class="domain-stack">${bestDomainSummary(c)}</div></td>
        <td class="${conflictClass(c.conflict_level)}">${escapeHtml(c.conflict_level || "—")}</td>
        <td class="radio-${c.radio_result || ""}" title="${escapeAttr(c.radio_explanation || "")}">${escapeHtml(radioLabel(c))}</td>
        <td><span class="src ${sourceClass}">${escapeHtml(c.method || "")}</span></td>
        <td class="notes">${escapeHtml(notesFor(c))}</td>
      </tr>`;
      })
      .join("");
    $("count").textContent = `${rows.length} shown / ${state.candidates.length} total`;
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
    $("byokStatus").textContent = key
      ? `AI key: set for this session (${provider}${model ? ", " + model : ""})`
      : "AI key: not set — local generation still works";
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

  function setActiveRun(run, candidates) {
    state.runId = run.id;
    state.run = run;
    state.candidates = candidates || state.candidates || [];
    const building = run.building || run.category || "";
    $("runMeta").textContent = `Session ${run.id} · ${run.status}`;
    const exportBtn = $("btnExport");
    exportBtn.href = `/api/runs/${run.id}/export.csv`;
    exportBtn.classList.remove("disabled");
    renderDirections(run, state.candidates);
    renderTable();
    if (building) {
      // keep form as the user left it
    }
  }

  async function loadRun(runId) {
    setStatus(`Loading session ${runId}…`);
    const data = await api(`/api/runs/${runId}`);
    setActiveRun(data.run, data.candidates || []);
    const note = (data.run.llm && data.run.llm.note) || "";
    setStatus(`Loaded ${state.candidates.length} names.${note ? " " + note : ""}`);
  }

  async function refreshRuns() {
    const data = await api("/api/runs");
    const list = $("runList");
    list.innerHTML =
      (data.runs || [])
        .map((r) => {
          const label = escapeHtml(r.building || r.category || r.id);
          return `<li data-id="${r.id}"><strong>${escapeHtml(r.id)}</strong> — ${label} <span class="hint">(${escapeHtml(r.status)})</span></li>`;
        })
        .join("") || "<li class='hint'>No saved sessions yet</li>";
  }

  $("runForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = {
      building: String(fd.get("building") || ""),
      audience: String(fd.get("audience") || ""),
      liked_brands: String(fd.get("liked_brands") || ""),
      avoid: String(fd.get("avoid") || ""),
      max_length: Number(fd.get("max_length")),
      generate_count: Number(fd.get("generate_count")),
      extensions: String(fd.get("extensions") || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      domain_check_top: Number(fd.get("domain_check_top")),
      conflict_check_top: Number(fd.get("conflict_check_top")),
      run_pipeline: true,
    };

    try {
      $("btnCreate").disabled = true;
      const byok = readByok();
      setStatus(
        byok.key
          ? `Generating names, scoring, checking domains & conflicts (AI creativity via ${byok.provider})…`
          : "Generating names, scoring, checking domains & conflicts…",
      );
      const data = await api("/api/runs", {
        method: "POST",
        body: JSON.stringify(payload),
        headers: llmHeaders(),
      });
      setActiveRun(data.run, data.candidates || []);
      await refreshRuns();
      const r = data.result || {};
      const domains = r.domains || {};
      const conflicts = r.conflicts || {};
      setStatus(
        `Done — ${r.generated || state.candidates.length} names` +
          (r.llm ? `, ${r.llm} AI` : "") +
          `, domains ${domains.checked || 0}, conflicts ${conflicts.checked || 0}.` +
          (r.llm_note ? ` ${r.llm_note}` : "") +
          (r.llm_error ? ` AI: ${r.llm_error}` : ""),
      );
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    } finally {
      $("btnCreate").disabled = false;
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
      renderDirections(state.run, state.candidates);
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

  ["search", "filterCom", "filterAny", "filterLow", "filterRadioPass", "filterFav", "minScore"].forEach((id) => {
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
    setStatus("Saved AI key for this browser tab. Clear key removes it.");
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
  setStatus("Ready — answer a few questions and hit Generate.");
  refreshRuns().catch((err) => setStatus(`Error loading sessions: ${err.message}`));
})();
