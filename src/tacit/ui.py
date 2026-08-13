"""The single-page overlap-graph UI, shipped as a module constant.

Kept as a Python string rather than a static asset for two reasons: it travels
with the package, so ``scripts/sync_functions.sh`` vendors it into the Functions
app with everything else and there is no package-data configuration to get
wrong; and the Functions host serves it from the same origin as ``/api/graph``,
so there is no CORS to configure.

No CDN, no build step, no framework. The force simulation is ~40 lines of plain
JavaScript over SVG, which is enough for the scale this graph is meaningful at
(tens of entities) and means the page renders inside a locked-down network where
a CDN fetch would simply hang.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>tacit - organizational memory</title>
<style>
  :root {
    --bg:#0f1115; --panel:#171a21; --line:#262b36; --ink:#e6e9ef; --muted:#8b93a7;
    --entity:#4aa3ff; --shared:#ffb454; --project:#3ddc97; --home:#ff6b8a;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
  header { padding:14px 20px; border-bottom:1px solid var(--line); display:flex;
           align-items:baseline; gap:16px; flex-wrap:wrap; }
  h1 { font-size:15px; margin:0; font-weight:600; letter-spacing:.02em; }
  .sub { color:var(--muted); font-size:12px; }
  main { display:grid; grid-template-columns:1fr 380px; height:calc(100vh - 53px); }
  @media (max-width:900px){ main { grid-template-columns:1fr; } aside { display:none; } }
  #canvas { position:relative; overflow:hidden; }
  svg { width:100%; height:100%; display:block; cursor:grab; }
  svg:active { cursor:grabbing; }
  aside { border-left:1px solid var(--line); background:var(--panel);
          overflow-y:auto; padding:16px 18px; }
  .stats { display:flex; gap:18px; flex-wrap:wrap; margin:0; padding:0; list-style:none; }
  .stats li { color:var(--muted); font-size:12px; }
  .stats b { color:var(--ink); font-size:15px; display:block; font-weight:600; }
  .legend { display:flex; gap:14px; font-size:12px; color:var(--muted); align-items:center; }
  .dot { width:9px; height:9px; border-radius:50%; display:inline-block; margin-right:5px; }
  h2 { font-size:13px; margin:0 0 4px; }
  .hint { color:var(--muted); font-size:12px; }
  .mem { border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin:10px 0;
         background:#12151b; }
  .mem .t { font-weight:600; margin-bottom:3px; }
  .mem .p { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px;
            color:var(--muted); word-break:break-all; }
  .tag { display:inline-block; font-size:11px; padding:1px 7px; border-radius:99px;
         border:1px solid var(--line); color:var(--muted); margin:5px 5px 0 0; }
  .tag.own { border-color:var(--home); color:var(--home); }
  .alias { font-size:11px; color:var(--muted); }
  .err { margin:20px; padding:14px 16px; border:1px solid #5a2530; background:#24141a;
         border-radius:8px; color:#ffb3c0; }
  text { pointer-events:none; user-select:none; }
</style>
</head>
<body>
<header>
  <h1>tacit</h1>
  <span class="sub">cross-team overlap &mdash; who already knows about what</span>
  <ul class="stats" id="stats"></ul>
  <span class="legend">
    <span><i class="dot" style="background:var(--shared)"></i>shared by 2+ teams</span>
    <span><i class="dot" style="background:var(--entity)"></i>entity</span>
    <span><i class="dot" style="background:var(--project)"></i>project</span>
  </span>
</header>
<main>
  <div id="canvas"><svg id="svg"></svg></div>
  <aside id="panel">
    <h2>Nothing selected</h2>
    <p class="hint">Click an <b>entity</b> to see the memories behind it and which
    teams wrote them. Orange entities are known to more than one team &mdash; those
    are the ones somebody is about to rediscover the hard way.</p>
  </aside>
</main>
<script>
const KEY = new URLSearchParams(location.search).get("code") || "";
const NS = "http://www.w3.org/2000/svg";
const svg = document.getElementById("svg");
const panel = document.getElementById("panel");

function el(tag, attrs) {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

fetch("graph" + (KEY ? "?code=" + encodeURIComponent(KEY) : ""))
  .then(r => r.ok ? r.json() : r.text().then(t => { throw new Error(r.status + " " + t); }))
  .then(render)
  .catch(e => {
    document.querySelector("main").innerHTML =
      '<div class="err"><b>Could not load the graph.</b><br>' + esc(e.message) +
      '<br><br>If this is the deployed app, append <code>?code=&lt;function key&gt;</code> to the URL.</div>';
  });

function render(data) {
  const stats = data.stats || {};
  document.getElementById("stats").innerHTML = [
    ["shared_entities", "shared"], ["entities", "entities"],
    ["projects", "projects"], ["visible_memories", "memories"],
  ].map(([k, label]) => "<li><b>" + (stats[k] ?? 0) + "</b>" + label + "</li>").join("");

  if (!data.nodes.length) {
    panel.innerHTML = "<h2>Empty graph</h2><p class=hint>No memory mentions anything "
      + "in the shared vocabulary yet. Add entities with <code>tacit ontology add</code>, "
      + "then <code>tacit reindex</code>.</p>";
    return;
  }

  const W = svg.clientWidth || 900, H = svg.clientHeight || 600;
  const nodes = data.nodes.map((n, i) => Object.assign({}, n, {
    // Seeded ring layout: deterministic, so the same data always draws the
    // same picture and a demo is reproducible.
    x: W / 2 + Math.cos(i * 2.399) * (80 + (i % 7) * 26),
    y: H / 2 + Math.sin(i * 2.399) * (80 + (i % 7) * 26),
    vx: 0, vy: 0,
  }));
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const edges = data.edges.filter(e => byId[e.source] && byId[e.target]);

  for (let step = 0; step < 320; step++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        let d2 = dx * dx + dy * dy || 0.01;
        const rep = 5200 / d2;
        const d = Math.sqrt(d2);
        const ux = dx / d, uy = dy / d;
        a.vx -= ux * rep; a.vy -= uy * rep;
        b.vx += ux * rep; b.vy += uy * rep;
      }
    }
    for (const e of edges) {
      const a = byId[e.source], b = byId[e.target];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (d - 120) * 0.012;
      const ux = dx / d, uy = dy / d;
      a.vx += ux * f * d * 0.02; a.vy += uy * f * d * 0.02;
      b.vx -= ux * f * d * 0.02; b.vy -= uy * f * d * 0.02;
    }
    for (const n of nodes) {
      n.vx += (W / 2 - n.x) * 0.0016;
      n.vy += (H / 2 - n.y) * 0.0016;
      n.x += (n.vx *= 0.82); n.y += (n.vy *= 0.82);
      n.x = Math.max(40, Math.min(W - 40, n.x));
      n.y = Math.max(30, Math.min(H - 30, n.y));
    }
  }

  svg.innerHTML = "";
  const root = el("g", {});
  svg.appendChild(root);

  for (const e of edges) {
    const a = byId[e.source], b = byId[e.target];
    root.appendChild(el("line", {
      x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: "#2c3340",
      "stroke-width": Math.min(1 + e.weight * 0.7, 4),
    }));
  }

  for (const n of nodes) {
    const entity = n.kind === "entity";
    const r = entity ? Math.min(9 + n.memories * 1.7, 24) : 11;
    const fill = entity ? (n.shared ? "var(--shared)" : "var(--entity)")
                        : (n.shared ? "var(--home)" : "var(--project)");
    const g = el("g", { style: entity ? "cursor:pointer" : "cursor:default" });
    const c = el("circle", {
      cx: n.x, cy: n.y, r: r, fill: fill,
      stroke: "#0f1115", "stroke-width": 2,
    });
    g.appendChild(c);
    const label = el("text", {
      x: n.x, y: n.y + r + 13, "text-anchor": "middle",
      fill: entity ? "#dfe4ee" : "#9aa4b8", "font-size": entity ? 12 : 11,
      "font-weight": entity && n.shared ? 600 : 400,
    });
    label.textContent = n.label;
    g.appendChild(label);
    if (entity) g.addEventListener("click", () => select(n, data));
    root.appendChild(g);
  }
}

function select(node, data) {
  const mems = (data.memories || {})[node.id] || [];
  const teams = [...new Set(mems.map(m => m.project))];
  const home = (data.stats || {}).home_project;
  let html = "<h2>" + esc(node.label) + "</h2>";
  html += '<p class="hint">' + esc(node.kind_of_entity) + " &middot; "
       + mems.length + " memor" + (mems.length === 1 ? "y" : "ies") + " across "
       + teams.length + " project" + (teams.length === 1 ? "" : "s") + "</p>";
  if (node.aliases && node.aliases.length) {
    html += '<p class="alias">also written as: ' + node.aliases.map(esc).join(", ") + "</p>";
  }
  if (node.shared) {
    html += '<p class="hint" style="color:var(--shared)">Known to more than one team &mdash; '
         + "this is knowledge that would otherwise be rediscovered.</p>";
  }
  for (const m of mems) {
    html += '<div class="mem"><div class="t">' + esc(m.title) + "</div>"
         + '<div class="p">' + esc(m.path) + "</div>"
         + '<span class="tag' + (m.project === home ? " own" : "") + '">'
         + esc(m.project) + (m.team ? " &middot; " + esc(m.team) : "") + "</span>"
         + '<span class="tag">' + esc(m.category) + "</span>"
         + '<span class="tag">' + esc(m.visibility) + "</span></div>";
  }
  panel.innerHTML = html;
}
</script>
</body>
</html>
"""
