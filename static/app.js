(() => {
  const $ = (id) => document.getElementById(id);

  const form = $("search-form");
  const searchBtn = $("search-btn");
  const stopBtn = $("stop-btn");
  const message = $("message");
  const progress = $("progress");
  const resultsPanel = $("results");
  const rowsEl = $("rows");
  const countEl = $("count");
  const visibleNote = $("visible-note");
  const fWebsite = $("f-website");
  const fPhone = $("f-phone");

  let allResults = [];
  let jobId = null;
  let pollTimer = null;

  /* ---------- helpers ---------- */
  function esc(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function safeUrl(url) {
    try {
      const u = new URL(url);
      return u.protocol === "http:" || u.protocol === "https:" ? u.href : "";
    } catch {
      return "";
    }
  }

  function showMessage(text, type = "error") {
    message.textContent = text;
    message.className = `banner banner-${type}`;
    message.hidden = false;
  }

  function clearMessage() {
    message.hidden = true;
    message.textContent = "";
  }

  function visibleResults() {
    return allResults.filter(
      (r) => (!fWebsite.checked || r.website) && (!fPhone.checked || r.phone)
    );
  }

  /* ---------- rendering ---------- */
  function render() {
    const rows = visibleResults();
    countEl.textContent = allResults.length;
    visibleNote.textContent =
      rows.length !== allResults.length ? `(showing ${rows.length})` : "";

    const empty = '<td class="empty">—</td>';

    rowsEl.innerHTML = rows
      .map((r) => {
        const site = safeUrl(r.website);
        const map = safeUrl(r.maps_url);
        const rating =
          r.rating !== "" && r.rating != null
            ? `${esc(r.rating)} <small class="muted">(${esc(r.reviews || 0)})</small>`
            : "";
        const closed = r.status && r.status !== "Operational";
        const siteLabel = site.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
        return `<tr>
          <td class="name"><strong>${esc(r.name)}</strong><small>${esc(r.category)}</small></td>
          <td>${esc(r.address)}</td>
          ${r.phone ? `<td>${esc(r.phone)}</td>` : empty}
          ${site ? `<td><a href="${esc(site)}" target="_blank" rel="noopener noreferrer">${esc(siteLabel)}</a></td>` : empty}
          <td class="num">${rating || "—"}</td>
          <td>${r.status ? `<span class="pill${closed ? " closed" : ""}">${esc(r.status)}</span>` : "—"}</td>
          <td>${map ? `<a href="${esc(map)}" target="_blank" rel="noopener noreferrer">Open</a>` : "—"}</td>
        </tr>`;
      })
      .join("");

    resultsPanel.hidden = allResults.length === 0;
    $("export-csv").disabled = $("export-xlsx").disabled = rows.length === 0;
  }

  function setRunning(running) {
    searchBtn.disabled = running;
    searchBtn.textContent = running ? "Searching…" : "Search businesses";
    progress.hidden = !running;
    stopBtn.disabled = false;
  }

  /* ---------- search + polling ---------- */
  async function poll() {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Lost track of the search.");

      allResults = data.results;
      render();

      $("progress-msg").textContent = data.message;
      $("progress-count").textContent = `${data.count} / ${data.target}`;
      $("bar-fill").style.width = `${Math.min(100, (data.count / data.target) * 100)}%`;

      if (data.state === "running") {
        pollTimer = setTimeout(poll, 1500);
        return;
      }

      setRunning(false);
      if (data.state === "error") {
        showMessage(data.error + (data.count ? ` (${data.count} results were collected before the error.)` : ""));
      } else if (data.state === "cancelled") {
        showMessage(`Stopped. ${data.count} results collected.`, "info");
      } else if (data.count === 0) {
        showMessage("No businesses found. Try a broader business type or another location.", "info");
      }
    } catch (err) {
      setRunning(false);
      showMessage(err.message);
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearMessage();
    clearTimeout(pollTimer);
    allResults = [];
    fWebsite.checked = fPhone.checked = false;
    render();
    $("bar-fill").style.width = "0%";
    $("progress-msg").textContent = "Starting browser…";
    $("progress-count").textContent = "";
    setRunning(true);

    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          keyword: $("keyword").value,
          location: $("location").value,
          max_results: $("max-results").value,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not start the search.");
      jobId = data.job_id;
      poll();
    } catch (err) {
      setRunning(false);
      showMessage(err.message);
    }
  });

  stopBtn.addEventListener("click", async () => {
    if (!jobId) return;
    stopBtn.disabled = true;
    $("progress-msg").textContent = "Stopping…";
    try {
      await fetch(`/api/cancel/${jobId}`, { method: "POST" });
    } catch {
      /* the poll loop will report the final state */
    }
  });

  fWebsite.addEventListener("change", render);
  fPhone.addEventListener("change", render);

  /* ---------- export ---------- */
  async function exportAs(format) {
    clearMessage();
    const rows = visibleResults();
    if (!rows.length) return;

    try {
      const res = await fetch(`/api/export/${format}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ results: rows }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "Export failed.");
      }
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `leads.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);
    } catch (err) {
      showMessage(err.message);
    }
  }

  $("export-csv").addEventListener("click", () => exportAs("csv"));
  $("export-xlsx").addEventListener("click", () => exportAs("xlsx"));
})();
