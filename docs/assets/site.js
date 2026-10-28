/* Static, dependency-free interactions for the RDQA project page. */
(() => {
  "use strict";

  const citation = document.getElementById("citation-text");
  const copyButton = document.getElementById("copy-citation");
  const copyStatus = document.getElementById("copy-status");
  let copyReset;

  if (citation && copyButton) {
    const originalLabel = copyButton.textContent;
    copyButton.addEventListener("click", async () => {
      clearTimeout(copyReset);
      try {
        if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(citation.textContent.trim() + "\n");
        copyButton.textContent = "Copied ✓";
        if (copyStatus) copyStatus.textContent = "BibTeX citation copied to clipboard.";
      } catch {
        const selection = window.getSelection();
        if (selection) {
          const range = document.createRange();
          range.selectNodeContents(citation);
          selection.removeAllRanges();
          selection.addRange(range);
        }
        copyButton.textContent = "Selected";
        if (copyStatus) copyStatus.textContent = "Citation selected. Press Control+C or Command+C to copy, or use the Download link.";
      }
      copyReset = setTimeout(() => { copyButton.textContent = originalLabel; }, 2500);
    });
  }

  const body = document.getElementById("leaderboard-body");
  const search = document.getElementById("model-search");
  const scaffoldFilter = document.getElementById("scaffold-filter");
  const metricSort = document.getElementById("metric-sort");
  const resetButton = document.getElementById("reset-filters");
  const count = document.getElementById("result-count");
  const description = document.getElementById("result-description");
  const note = document.getElementById("leaderboard-note");
  const caption = document.getElementById("leaderboard-caption");
  const tabs = Array.from(document.querySelectorAll("[data-result-set]"));
  if (![body, search, scaffoldFilter, metricSort, resetButton, count, description, note, caption].every(Boolean)) return;

  const sortOptions = [
    ["adjusted", "Adjusted accuracy: highest first"],
    ["adjusted-asc", "Adjusted accuracy: lowest first"],
    ["raw", "Raw accuracy: highest first"],
    ["raw-asc", "Raw accuracy: lowest first"],
    ["plr", "PLR: lowest first"],
    ["plr-desc", "PLR: highest first"],
    ["name", "System A–Z"],
    ["name-desc", "System Z–A"]
  ];
  metricSort.replaceChildren(...sortOptions.map(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    return option;
  }));

  const controls = [search, scaffoldFilter, metricSort, resetButton, ...tabs];
  controls.forEach(control => { control.disabled = true; });
  let data;
  let activeSet = "paper";

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function metricValue(row, metric) {
    return typeof row[metric] === "number" && Number.isFinite(row[metric]) ? row[metric] : null;
  }

  function sortState() {
    const value = metricSort.value;
    const metric = value.split("-")[0];
    const ascending = value.endsWith("-asc") || value === "plr" || value === "name";
    return { metric, ascending };
  }

  function compareRows(a, b) {
    const { metric, ascending } = sortState();
    if (metric === "name") return (ascending ? 1 : -1) * a.name.localeCompare(b.name, "en");
    const av = metricValue(a, metric);
    const bv = metricValue(b, metric);
    // Missing scores always follow reported scores in either direction.
    if (av === null && bv !== null) return 1;
    if (av !== null && bv === null) return -1;
    if (av !== null && bv !== null && av !== bv) return (ascending ? 1 : -1) * (av - bv);
    return a.name.localeCompare(b.name, "en");
  }

  function agentRanks(rows) {
    const { metric, ascending } = sortState();
    const rankMetric = metric === "name" ? "adjusted" : metric;
    const direction = metric === "name" ? -1 : ascending ? 1 : -1;
    const candidates = rows.filter(row => row.type === "agent" && metricValue(row, rankMetric) !== null)
      .sort((a, b) => direction * (a[rankMetric] - b[rankMetric]) || a.name.localeCompare(b.name, "en"));
    const ranks = new Map();
    let lastValue;
    let rank = 0;
    candidates.forEach((row, index) => {
      if (index === 0 || row[rankMetric] !== lastValue) rank = index + 1;
      ranks.set(row.id, rank);
      lastValue = row[rankMetric];
    });
    return ranks;
  }

  function scoreCell(row, metric) {
    const value = metricValue(row, metric);
    const cell = element("td", value === null ? "—" : value.toFixed(1) + "%", "score-cell" + (value === null ? " missing-score" : ""));
    if (value === null) cell.title = metric === "raw" && activeSet === "paper"
      ? "Overall raw accuracy is not reported in Table 3."
      : "Not reported, or the evaluation denominator is not established.";
    if (metric === "adjusted") cell.classList.add("adjusted-score");
    return cell;
  }

  function sourceCell(row) {
    const cell = element("td");
    try {
      const url = new URL(row.source.url);
      if (url.protocol !== "https:") throw new Error("Unsupported source URL");
      const link = element("a", row.source.label + " ↗", "source-link");
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.title = row.source.locator;
      link.setAttribute("aria-label", row.name + ": " + row.source.label + " (opens in a new tab)");
      cell.append(link);
    } catch {
      cell.textContent = "Unavailable";
    }
    return cell;
  }

  function render() {
    const resultSet = data.sets[activeSet];
    const query = search.value.trim().toLocaleLowerCase("en");
    const rows = resultSet.rows.filter(row =>
      (scaffoldFilter.value === "all" || row.scaffold === scaffoldFilter.value) &&
      [row.name, row.model || "", row.scaffold].join(" ").toLocaleLowerCase("en").includes(query)
    ).sort(compareRows);
    const ranks = agentRanks(resultSet.rows);
    body.replaceChildren();
    if (!rows.length) {
      const row = element("tr");
      const cell = element("td", "No systems match these filters. Try another search or select Reset.", "empty-state");
      cell.colSpan = 7;
      row.append(cell);
      body.append(row);
    }
    rows.forEach(row => {
      const tr = element("tr");
      if (row.type === "reference") tr.classList.add("reference-row");
      if (row.type === "human") tr.classList.add("human-row");
      const rank = element("td", ranks.has(row.id) ? String(ranks.get(row.id)) : "—", "rank-cell");
      if (!ranks.has(row.id)) rank.title = row.type === "artifact" ? "Different record sets are not ranked." : "Reference row or no reported ranking metric.";
      const system = element("th");
      system.scope = "row";
      system.append(element("span", row.model || row.name, "system-name"));
      let detail;
      if (row.type === "reference") detail = "RDQA reference baseline · N not reported";
      else if (row.type === "human") detail = "Human reference · N not reported";
      else if (row.type === "artifact") detail = row.sampleNote;
      else detail = (row.group === "open" ? "Open model" : "Closed model") + " · N not reported";
      system.append(element("span", detail, "system-meta"));
      const scaffold = element("td");
      scaffold.append(element("span", row.scaffold, "scaffold-badge"));
      tr.append(rank, system, scaffold, scoreCell(row, "raw"), scoreCell(row, "plr"), scoreCell(row, "adjusted"), sourceCell(row));
      body.append(tr);
    });
    count.textContent = rows.length + " of " + resultSet.rows.length + " " + (activeSet === "paper" ? "published rows" : "repository artifacts");
    description.textContent = resultSet.description;
    note.textContent = resultSet.note;
    caption.textContent = activeSet === "paper"
      ? "Published Table 3. Percentages; generic agents ranked by the selected metric. References are unranked."
      : "Partial repository artifacts. Different record sets; no comparative ranks. Percentages are descriptive.";
    const { metric } = sortState();
    document.querySelectorAll(".leaderboard thead th").forEach((th, index) => {
      const selected = ({ name: 1, raw: 3, plr: 4, adjusted: 5 })[metric] === index;
      if (selected) th.setAttribute("aria-sort", sortState().ascending ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    });
  }

  function resetFilters() {
    search.value = "";
    scaffoldFilter.value = "all";
    metricSort.value = data.sets[activeSet].defaultSort;
    render();
  }

  function selectSet(key) {
    if (!data.sets[key]) return;
    activeSet = key;
    tabs.forEach(tab => {
      const selected = tab.dataset.resultSet === key;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-pressed", String(selected));
    });
    const all = element("option", "All scaffolds");
    all.value = "all";
    scaffoldFilter.replaceChildren(all, ...Array.from(new Set(data.sets[key].rows.map(row => row.scaffold)))
      .sort((a, b) => a.localeCompare(b, "en")).map(value => {
        const option = element("option", value);
        option.value = value;
        return option;
      }));
    resetFilters();
  }

  function validData(value) {
    if (value?.schemaVersion !== 1 || !value.sets) return false;
    return ["paper", "artifacts"].every(key => {
      const set = value.sets[key];
      return set && typeof set.description === "string" && typeof set.note === "string" && Array.isArray(set.rows) &&
        set.rows.every(row => typeof row.id === "string" && typeof row.name === "string" && typeof row.scaffold === "string" &&
          ["agent", "reference", "human", "artifact"].includes(row.type) && row.source && typeof row.source.url === "string" &&
          ["raw", "plr", "adjusted"].every(metric => row[metric] === null || (typeof row[metric] === "number" && Number.isFinite(row[metric]) && row[metric] >= 0 && row[metric] <= 100)));
    });
  }

  const form = search.closest("form");
  if (form) form.addEventListener("submit", event => event.preventDefault());
  search.addEventListener("input", () => { if (data) render(); });
  scaffoldFilter.addEventListener("change", () => { if (data) render(); });
  metricSort.addEventListener("change", () => { if (data) render(); });
  resetButton.addEventListener("click", () => { if (data) resetFilters(); });
  tabs.forEach(tab => tab.addEventListener("click", () => { if (data) selectSet(tab.dataset.resultSet); }));

  fetch(new URL("data/leaderboard.json", document.baseURI), { cache: "no-cache" })
    .then(response => {
      if (!response.ok) throw new Error("Results data could not be loaded");
      return response.json();
    })
    .then(value => {
      if (!validData(value)) throw new Error("Invalid results data");
      data = value;
      controls.forEach(control => { control.disabled = false; });
      selectSet("paper");
    })
    .catch(() => {
      const row = element("tr");
      const cell = element("td", undefined, "empty-state");
      cell.colSpan = 7;
      cell.append(document.createTextNode("The interactive results could not be loaded. "));
      const fallback = element("a", "Open the verified source data");
      fallback.href = "data/leaderboard.json";
      cell.append(fallback, document.createTextNode(" or read Table 3 in the paper."));
      row.append(cell);
      body.replaceChildren(row);
      description.textContent = "Results are temporarily unavailable in this view. The source data and paper remain linked.";
      count.textContent = "Results unavailable";
    });
})();
