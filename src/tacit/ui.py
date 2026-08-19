"""The single-page overlap-graph UI, shipped as a module constant.

Kept as a Python string rather than a static asset for two reasons: it travels
with the package, so ``scripts/sync_functions.sh`` vendors it into the Functions
app with everything else and there is no package-data configuration to get
wrong; and the Functions host serves it from the same origin as its data, so
there is no CORS to configure.

The page talks to two endpoints, both resolved *relative* to itself so the same
HTML works under the local server (``/graph``) and the Functions host
(``/api/graph``):

* ``graph``  — nodes, edges and per-entity drill-down for this viewer
* ``search`` — the same ranked hits ``memory_search`` returns to an agent

D3 is loaded from a CDN. That is a deliberate reversal of this file's original
"no CDN" rule, which existed so the page would render on an air-gapped network;
the trade was accepted for the force layout, and the page says plainly when the
fetch fails rather than showing an empty canvas.
"""

from __future__ import annotations

#: Pinned rather than tracking latest: this is a script tag on a page that
#: renders access-controlled data, so the version should change deliberately.
D3_SRC = "https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>tacit — organizational memory</title>
<script src="__D3_SRC__"></script>
<style>
  :root {
    --bg:#0b0d12; --panel:#12151d; --raised:#171b25; --line:#242a37;
    --ink:#e8ecf4; --muted:#8791a6; --faint:#5c6579;
    --entity:#7c8cff; --shared:#ff9f43; --project:#2ee6a8; --home:#ff5c8a;
    --focus:#7c8cff;
  }
  * { box-sizing:border-box; }
  html,body { height:100%; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
         -webkit-font-smoothing:antialiased;
         display:flex; flex-direction:column; height:100vh; overflow:hidden; }

  header { padding:12px 20px; border-bottom:1px solid var(--line);
           display:flex; align-items:center; gap:20px; flex-wrap:wrap;
           background:linear-gradient(180deg,#12151d,#0d1016); }
  .brand { font-size:15px; font-weight:650; letter-spacing:.01em; }
  .brand span { color:var(--muted); font-weight:400; margin-left:8px; font-size:12px; }
  .stats { display:flex; gap:20px; margin-left:auto; list-style:none; padding:0; margin-block:0; }
  .stats li { color:var(--faint); font-size:11px; text-transform:uppercase;
              letter-spacing:.06em; }
  .stats b { color:var(--ink); font-size:16px; display:block; font-weight:650;
             letter-spacing:0; text-transform:none; }

  .controls { display:flex; gap:8px; align-items:center; padding:9px 16px;
              border-bottom:1px solid var(--line); background:var(--panel);
              flex-wrap:wrap; }
  .search { position:relative; flex:1 1 240px; min-width:180px; }
  .search input { width:100%; padding:8px 12px 8px 32px; border-radius:8px;
                  border:1px solid var(--line); background:var(--raised);
                  color:var(--ink); font:inherit; outline:none; }
  .search input:focus { border-color:var(--focus); box-shadow:0 0 0 3px rgba(124,140,255,.15); }
  .search svg { position:absolute; left:10px; top:50%; transform:translateY(-50%);
                width:14px; height:14px; stroke:var(--faint); fill:none; stroke-width:2; }
  select { padding:7px 8px; border-radius:8px; border:1px solid var(--line);
           background:var(--raised); color:var(--ink); font:inherit; outline:none;
           max-width:150px; }
  select:focus { border-color:var(--focus); }
  label.f { display:flex; align-items:center; gap:5px; font-size:10px; color:var(--faint);
            text-transform:uppercase; letter-spacing:.05em; white-space:nowrap; }

  /* flex rather than a height calc: the control bar wraps on narrow windows,
     so its height is not knowable in CSS. Below the breakpoint the panel moves
     under the graph rather than disappearing — it holds the search results,
     which are the point of the page, not decoration. */
  main { display:grid; grid-template-columns:1fr 380px; flex:1; min-height:0; }
  @media (max-width:900px){
    main { grid-template-columns:1fr; grid-template-rows:minmax(280px,45vh) 1fr; }
    aside { border-left:none; border-top:1px solid var(--line); }
  }

  #canvas { position:relative; overflow:hidden; }
  svg#graph { width:100%; height:100%; display:block; cursor:grab; }
  svg#graph:active { cursor:grabbing; }
  .link { stroke:#2b3346; fill:none; }
  .link.hot { stroke:var(--shared); stroke-opacity:.85; }
  .node circle { cursor:pointer; transition:filter .15s; }
  .node:hover circle { filter:brightness(1.35); }
  .node text { font-size:11px; fill:var(--muted); pointer-events:none;
               user-select:none; paint-order:stroke; stroke:var(--bg);
               stroke-width:3px; stroke-linejoin:round; }
  .node.sel text { fill:var(--ink); font-weight:600; }
  .legend { position:absolute; left:16px; bottom:14px; display:flex; gap:16px;
            font-size:11px; color:var(--faint); }
  .dot { width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:6px; }
  .empty { position:absolute; inset:0; display:grid; place-items:center;
           color:var(--faint); font-size:13px; text-align:center; padding:40px; }

  aside { border-left:1px solid var(--line); background:var(--panel);
          overflow-y:auto; padding:16px 18px 40px; }
  aside h2 { font-size:12px; margin:0 0 2px; text-transform:uppercase;
             letter-spacing:.07em; color:var(--faint); font-weight:600; }
  .hint { color:var(--faint); font-size:12px; margin:6px 0 0; }
  .card { border:1px solid var(--line); border-radius:10px; padding:11px 13px;
          margin:10px 0; background:var(--raised); }
  .card.hit { cursor:pointer; }
  .card.hit:hover { border-color:var(--focus); }
  .card .t { font-weight:600; margin-bottom:3px; }
  .card .p { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px;
             color:var(--faint); word-break:break-all; }
  .card .snip { font-size:12px; color:var(--muted); margin-top:7px;
                border-left:2px solid var(--line); padding-left:9px;
                white-space:pre-wrap; max-height:8.5em; overflow:hidden; }
  .row { display:flex; align-items:center; gap:8px; margin-top:7px; flex-wrap:wrap; }
  .tag { font-size:10px; padding:2px 8px; border-radius:99px; border:1px solid var(--line);
         color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
  .tag.foreign { border-color:var(--shared); color:var(--shared); }
  .tag.trunc { border-color:var(--line); color:var(--faint); text-transform:none; }
  .score { margin-left:auto; font-family:ui-monospace,Menlo,monospace;
           font-size:11px; color:var(--faint); }
  .alias { font-size:11px; color:var(--faint); margin-top:4px; }
  .err { margin:16px 0; padding:13px 15px; border:1px solid #5a2530; background:#22131a;
         border-radius:9px; color:#ffb3c0; font-size:13px; }
  .spin { color:var(--faint); font-size:12px; padding:8px 0; }
</style>
</head>
<body>
<header>
  <div class="brand">tacit <span id="viewer"></span></div>
  <ul class="stats" id="stats"></ul>
</header>

<div class="controls">
  <div class="search">
    <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
    <input id="q" type="search" autocomplete="off"
           placeholder="Ask memory, as you would a teammate — e.g. why does the webhook signature fail in staging">
  </div>
  <label class="f">scope
    <select id="scope">
      <option value="project+org">this project + org</option>
      <option value="project">this project</option>
      <option value="org">other teams only</option>
    </select>
  </label>
  <label class="f">project <select id="project"></select></label>
  <label class="f">category <select id="category"></select></label>
</div>

<main>
  <div id="canvas">
    <svg id="graph"></svg>
    <div class="legend">
      <span><i class="dot" style="background:var(--project)"></i>project</span>
      <span><i class="dot" style="background:var(--entity)"></i>entity</span>
      <span><i class="dot" style="background:var(--shared)"></i>known to 2+ teams</span>
    </div>
    <div class="empty" id="empty" hidden></div>
  </div>
  <aside id="panel"></aside>
</main>

<script>
// The function key travels in the query string on the deployed app; every
// request this page makes has to carry it forward.
const KEY = new URLSearchParams(location.search).get("code") || "";
const url = (path, params) => {
  const p = new URLSearchParams(params || {});
  if (KEY) p.set("code", KEY);
  Object.keys(params || {}).forEach(k => { if (!params[k]) p.delete(k); });
  if (KEY) p.set("code", KEY);
  const qs = p.toString();
  return path + (qs ? "?" + qs : "");
};

const el = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

let GRAPH = null;      // last graph payload
let HOME = "";         // the project this viewer looks from
let selected = null;   // selected entity node id

// --------------------------------------------------------------- rendering
const svg = d3.select("#graph");
let sim = null;

function renderGraph(data) {
  svg.selectAll("*").remove();
  const box = el("canvas").getBoundingClientRect();
  const w = box.width, h = box.height;
  const nodes = data.nodes.map(d => Object.assign({}, d));
  const byId = new Map(nodes.map(n => [n.id, n]));
  const links = data.edges
    .filter(e => byId.has(e.source) && byId.has(e.target))
    .map(e => Object.assign({}, e));

  el("empty").hidden = nodes.length > 0;
  if (!nodes.length) {
    el("empty").textContent =
      "No entities to plot yet. The graph is drawn from the shared vocabulary — " +
      "add entries with `tacit ontology add`, then run `tacit reindex`.";
    return;
  }

  const root = svg.append("g");
  svg.call(d3.zoom().scaleExtent([0.3, 4])
      .on("zoom", ev => root.attr("transform", ev.transform)));

  // forceLink rewrites link.source/target from ids to node objects, so any
  // accessor that runs after the simulation starts must cope with both.
  const end = v => (typeof v === "object" ? v : byId.get(v));

  const radius = d => d.kind === "project"
    ? 9 + Math.sqrt(d.memories || 1) * 2.6
    : 6 + Math.sqrt(d.memories || 1) * 3.2;
  const colour = d => d.kind === "project"
    ? (d.shared ? "var(--home)" : "var(--project)")
    : (d.shared ? "var(--shared)" : "var(--entity)");

  const link = root.append("g").selectAll("path").data(links).join("path")
      .attr("class", d => "link" + (end(d.target).shared ? " hot" : ""))
      .attr("stroke-width", d => Math.min(1 + (d.weight || 1) * 0.7, 4))
      .attr("stroke-opacity", 0.5);

  const node = root.append("g").selectAll("g").data(nodes).join("g")
      .attr("class", "node")
      .on("click", (ev, d) => { ev.stopPropagation(); select(d); });

  node.append("circle")
      .attr("r", radius)
      .attr("fill", colour)
      .attr("stroke", "var(--bg)")
      .attr("stroke-width", 2);

  node.append("text")
      .attr("dy", d => -radius(d) - 6)
      .attr("text-anchor", "middle")
      .text(d => d.label + (d.memories > 1 ? "  " + d.memories : ""));

  node.call(d3.drag()
      .on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.25).restart();
                                d.fx = d.x; d.fy = d.y; })
      .on("drag",  (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on("end",   (ev, d) => { if (!ev.active) sim.alphaTarget(0); }));

  if (sim) sim.stop();
  sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id(d => d.id)
                       .distance(d => 70 + (end(d.target).projects || 1) * 22)
                       .strength(0.35))
      .force("charge", d3.forceManyBody().strength(-420))
      .force("collide", d3.forceCollide().radius(d => radius(d) + 22))
      .force("center", d3.forceCenter(w / 2, h / 2))
      // Without a gentle pull to the middle a sparse graph drifts off-canvas,
      // since charge repulsion has nothing to push against at the edges.
      .force("x", d3.forceX(w / 2).strength(0.06))
      .force("y", d3.forceY(h / 2).strength(0.09))
      .on("tick", () => {
        link.attr("d", d => {
          const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
          const dr = Math.hypot(dx, dy) * 1.9;
          return `M${d.source.x},${d.source.y}A${dr},${dr} 0 0,1 ${d.target.x},${d.target.y}`;
        });
        node.attr("transform", d => `translate(${d.x},${d.y})`);
      });

  svg.on("click", () => { selected = null; node.classed("sel", false); showIdle(); });
  window.__nodes = node;
}

function select(d) {
  selected = d.id;
  if (window.__nodes) window.__nodes.classed("sel", n => n.id === d.id);
  if (d.kind === "project") { showProject(d); return; }
  showEntity(d);
}

// ------------------------------------------------------------- side panel
function showIdle() {
  const s = (GRAPH && GRAPH.stats) || {};
  el("panel").innerHTML =
    '<h2>Overlap</h2>' +
    '<p class="hint">Entities sit between the projects that wrote about them. ' +
    'An entity known to <b style="color:var(--shared)">more than one team</b> is ' +
    'knowledge somebody is about to rediscover the hard way.</p>' +
    '<p class="hint">Click a node to see the memories behind it, or search above ' +
    'to query memory exactly as an agent does.</p>' +
    (s.vocabulary_size === 0
      ? '<div class="err">The shared vocabulary is empty, so no entities can be ' +
        'plotted. Add some with <code>tacit ontology add</code>, then ' +
        '<code>tacit reindex</code>.</div>'
      : '');
}

function showEntity(d) {
  const mems = (GRAPH.memories || {})[d.id] || [];
  const aliases = (d.aliases || []).join(", ");
  el("panel").innerHTML =
    '<h2>' + esc(d.kind_of_entity || "entity") + '</h2>' +
    '<div style="font-size:16px;font-weight:650">' + esc(d.label) + '</div>' +
    (aliases ? '<div class="alias">also called ' + esc(aliases) + '</div>' : '') +
    '<p class="hint">' + mems.length + ' memor' + (mems.length === 1 ? 'y' : 'ies') +
    ' across ' + d.projects + ' project' + (d.projects === 1 ? '' : 's') + '</p>' +
    mems.map(m =>
      '<div class="card"><div class="t">' + esc(m.title) + '</div>' +
      '<div class="p">' + esc(m.path) + '</div>' +
      '<div class="row"><span class="tag">' + esc(m.category) + '</span>' +
      (m.project && m.project !== HOME
        ? '<span class="tag foreign">from ' + esc(m.project) + '</span>' : '') +
      '</div></div>').join("");
}

function showProject(d) {
  el("panel").innerHTML =
    '<h2>project</h2>' +
    '<div style="font-size:16px;font-weight:650">' + esc(d.label) + '</div>' +
    (d.team ? '<div class="alias">team ' + esc(d.team) + '</div>' : '') +
    '<p class="hint">' + d.memories + ' visible memories' +
    (d.label === HOME ? ' — this is where you are looking from' : '') + '</p>';
}

function renderHits(query, hits) {
  if (!hits.length) {
    el("panel").innerHTML = '<h2>Search</h2><p class="hint">No memory answers ' +
      '&ldquo;' + esc(query) + '&rdquo; yet. That gap is itself worth recording.</p>';
    return;
  }
  el("panel").innerHTML = '<h2>' + hits.length + ' hit' +
    (hits.length === 1 ? '' : 's') + '</h2>' +
    '<p class="hint">The same ranked sections an agent receives.</p>' +
    hits.map(h =>
      '<div class="card hit" data-entity="' + esc((h.entities || [])[0] || "") + '">' +
      '<div class="t">' + esc(h.title) + '</div>' +
      '<div class="p">' + esc(h.path) + (h.heading ? ' &rsaquo; ' + esc(h.heading) : '') +
      '</div>' +
      (h.content ? '<div class="snip">' + esc(h.content) + '</div>' : '') +
      '<div class="row"><span class="tag">' + esc(h.category || "general") + '</span>' +
      (h.project ? '<span class="tag foreign">from ' + esc(h.project) + '</span>' : '') +
      (h.truncated ? '<span class="tag trunc">truncated</span>' : '') +
      '<span class="score">' + (h.score || 0).toFixed(2) + '</span>' +
      '</div></div>').join("");
}

// ----------------------------------------------------------------- loading
function fillSelect(id, values, current, blank) {
  const s = el(id);
  s.innerHTML = '<option value="">' + blank + '</option>' +
    values.map(v => '<option' + (v === current ? ' selected' : '') + '>' +
                    esc(v) + '</option>').join("");
}

async function loadGraph() {
  const params = { scope: el("scope").value, project: el("project").value };
  let res;
  try {
    res = await fetch(url("graph", params));
  } catch (e) {
    el("panel").innerHTML = '<div class="err">Could not reach the graph endpoint.<br>' +
      esc(e.message) + '</div>';
    return;
  }
  if (!res.ok) {
    const body = await res.text();
    el("panel").innerHTML = '<div class="err">graph returned HTTP ' + res.status +
      '<br>' + esc(body.slice(0, 300)) +
      (res.status === 401 ? '<br><br>Append <code>?code=&lt;function key&gt;</code> ' +
        'to the URL on the deployed app.' : '') + '</div>';
    return;
  }
  GRAPH = await res.json();
  HOME = (GRAPH.stats || {}).home_project || "";
  el("viewer").textContent = HOME ? "viewed from " + HOME : "";

  const s = GRAPH.stats || {};
  el("stats").innerHTML = [
    ["memories", s.visible_memories], ["projects", s.projects],
    ["entities", s.entities], ["shared", s.shared_entities],
  ].map(([k, v]) => '<li>' + k + '<b>' + (v == null ? "-" : v) + '</b></li>').join("");

  const projects = GRAPH.nodes.filter(n => n.kind === "project").map(n => n.label);
  fillSelect("project", projects, el("project").value, "all projects");
  renderGraph(GRAPH);
  // A filter change reloads the graph *and* re-runs the query; without this
  // guard the idle blurb would overwrite the results that just arrived.
  if (!selected && !el("q").value.trim()) showIdle();
}

let timer = null;
async function runSearch() {
  const q = el("q").value.trim();
  if (!q) { showIdle(); return; }
  el("panel").innerHTML = '<div class="spin">searching…</div>';
  const params = {
    q, scope: el("scope").value, project: el("project").value,
    category: el("category").value, top: "8",
  };
  try {
    const res = await fetch(url("search", params));
    if (!res.ok) {
      const body = await res.text();
      el("panel").innerHTML = '<div class="err">search returned HTTP ' + res.status +
        '<br>' + esc(body.slice(0, 300)) + '</div>';
      return;
    }
    renderHits(q, await res.json());
  } catch (e) {
    el("panel").innerHTML = '<div class="err">' + esc(e.message) + '</div>';
  }
}

el("q").addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(runSearch, 280);
});
el("scope").addEventListener("change", () => { loadGraph(); runSearch(); });
el("project").addEventListener("change", () => { loadGraph(); runSearch(); });
el("category").addEventListener("change", runSearch);
// Re-render rather than only re-centring: the panel moves below the graph at
// the breakpoint, which changes the canvas aspect ratio entirely.
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (GRAPH) renderGraph(GRAPH); }, 150);
});

fillSelect("category",
  ["onboarding", "gotcha", "architecture", "convention", "general"], "", "any category");

if (typeof d3 === "undefined") {
  el("panel").innerHTML = '<div class="err">D3 could not be loaded from the CDN, ' +
    'so the graph cannot render. Search still works. If this network blocks ' +
    'external scripts, serve d3.min.js from this origin instead.</div>';
  el("empty").hidden = false;
  el("empty").textContent = "D3 unavailable — graph disabled.";
} else {
  loadGraph();
}
</script>
</body>
</html>
""".replace("__D3_SRC__", D3_SRC)
