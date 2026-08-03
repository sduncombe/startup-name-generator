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
    const bar = $("progressBar");
    progress.hidden = false;
    progress.dataset.busy = busy ? "true" : "false";
    $("status").textContent = label;
    if (!busy) {
      bar.style.width = "100%";
      bar.style.animation = "none";
    } else {
      bar.style.width = "";
      bar.style.animation = "";
    }
  }

  function setIdleMessage(msg) {
    $("progress").hidden = !msg;
    $("progress").dataset.busy = "false";
    $("status").textContent = msg || "";
    $("progressBar").style.width = msg ? "100%" : "0%";
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
      .join("");
  }

  function scoreOf(c, key) {
    if (key === "total_score") return Number(c.total_score || 0);
    if (key === "name") return String(c.name || "").toLowerCase();
    if (key === "conflict_level") return String(c.conflict_level || "");
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
    return (comOk || anyOk) && conflictOk && radioOk;
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
    if (alts) bits.push(`Also: ${alts}`);
    return bits.join(" · ") || "—";
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
        <td class="${conflictClass(c.conflict_level)}">${escapeHtml(c.conflict_level || "—")}</td>
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
    $("byokStatus").textContent = key ? `Key set · ${provider}` : "No AI key";
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
    setBusy(true, "Loading previous session…");
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
          const label = escapeHtml(r.building || r.category || r.id);
          return `<li data-id="${r.id}">${label} <span class="hint">· ${escapeHtml(r.status)}</span></li>`;
        })
        .join("") || "<li class='hint'>No previous sessions</li>";
  }

  $("runForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    persistByokFromFields();
    const fd = new FormData(e.target);
    const domainTop = 40;
    const conflictTop = 40;
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
      domain_check_top: domainTop,
      conflict_check_top: conflictTop,
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

      setBusy(true, "Preparing results…");
      const data = await api(`/api/runs/${runId}`);
      setActiveRun(data.run, data.candidates || []);
      await refreshRuns();

      const r = gen.result || {};
      const bits = [`${state.candidates.length} names`];
      if (r.llm) bits.push(`${r.llm} from AI`);
      setIdleMessage(bits.join(" · "));
      $("building").blur();
    } catch (err) {
      setIdleMessage(`Something went wrong: ${err.message}`);
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

  // Autosave key as the user types/pastes — no separate Save control
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

  refreshByokStatus();
  $("progress").hidden = true;
  refreshRuns().catch(() => {});
})();
