"""The public story page, shipped as a module constant.

Same rationale as ``ui.py``: a Python string travels with the package, so
``scripts/sync_functions.sh`` vendors it into the Functions app for free, and
the page needs no package-data configuration.

Unlike ``ui.py`` this page renders no tenant data and calls no endpoint — it is
what TEAM-ONBOARDING.md points a new team at before they have a key, so it is
served at the API root with ``AuthLevel.ANONYMOUS`` and loads nothing from a
CDN: every asset, including the architecture diagram, is inline markup, which
is also why its Content-Security-Policy needs no ``connect-src`` or
``script-src`` allowance beyond ``'unsafe-inline'``.

The copy is drawn from README.md, DESIGN.md, TEAM-ONBOARDING.md and
benchmark/RESULTS.md — this file should not invent claims those documents do
not make; update both sides together if the story changes.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>tacit — organizational memory for AI agents</title>
<style>
  :root {
    --bg:#0b0d12; --panel:#12151d; --raised:#171b25; --line:#242a37;
    --ink:#e8ecf4; --muted:#8791a6; --faint:#5c6579;
    --entity:#7c8cff; --shared:#ff9f43; --project:#2ee6a8; --home:#ff5c8a;
    --focus:#7c8cff;
    --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  }
  * { box-sizing:border-box; }
  html,body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.6 var(--sans); }
  body { -webkit-font-smoothing:antialiased; }
  a { color:inherit; }
  code { font-family:var(--mono); font-size:0.92em; color:var(--ink); }
  h1,h2,h3 { font-weight:650; letter-spacing:-0.01em; margin:0; }
  a:focus-visible, button:focus-visible { outline:2px solid var(--focus); outline-offset:2px; }

  .tl { background:
          radial-gradient(1100px 460px at 85% -8%, rgba(124,140,255,.10), transparent 60%),
          radial-gradient(900px 440px at -8% 4%, rgba(46,230,168,.07), transparent 55%),
          var(--bg); }
  .wrap { max-width:1180px; margin:0 auto; padding:0 clamp(18px,4vw,48px); }

  /* Nav */
  nav.tl-nav { position:sticky; top:0; z-index:20; backdrop-filter:blur(8px);
    background:rgba(11,13,18,.86); border-bottom:1px solid var(--line);
    display:flex; align-items:center; gap:clamp(14px,2vw,28px); flex-wrap:wrap;
    padding:14px clamp(18px,4vw,48px); }
  .tl-brand { font-weight:700; font-size:15px; }
  .tl-brand span { color:var(--muted); font-weight:400; font-size:12px; margin-left:8px; }
  .tl-nav-links { display:flex; align-items:center; gap:clamp(12px,2vw,22px);
    font-size:13.5px; font-weight:600; color:var(--muted); margin-left:auto; flex-wrap:wrap; }
  .tl-nav-links a:hover { color:var(--ink); }

  .btn { display:inline-flex; align-items:center; gap:6px; padding:10px 16px;
    border-radius:10px; font-size:13.5px; font-weight:650; border:1px solid var(--line);
    cursor:pointer; text-decoration:none; }
  .btn-lg { padding:13px 22px; font-size:15px; border-radius:12px; }
  .btn-primary { background:var(--entity); color:#0b0d12; border-color:var(--entity); }
  .btn-primary:hover { background:#93a1ff; }
  .btn-ghost { background:transparent; color:var(--ink); border-color:var(--line); }
  .btn-ghost:hover { border-color:var(--entity); color:var(--entity); }

  /* Hero */
  header.tl-hero { display:grid; grid-template-columns:1.15fr 1fr; gap:clamp(24px,4vw,56px);
    align-items:center; padding:clamp(40px,7vw,84px) clamp(18px,4vw,48px) clamp(28px,5vw,56px); }
  @media (max-width:860px){ header.tl-hero { grid-template-columns:1fr; } }
  .tl-eyebrow { font-family:var(--mono); font-size:11.5px; font-weight:600; letter-spacing:.06em;
    color:var(--entity); text-transform:uppercase; display:block; margin-bottom:16px; }
  h1.tl-h1 { font-size:clamp(28px,4vw,46px); line-height:1.14; margin:0 0 18px; }
  h1.tl-h1 .hl { color:var(--project); }
  .tl-hero p.tl-sub { font-size:clamp(14.5px,1.4vw,16.5px); line-height:1.6; color:var(--muted);
    max-width:58ch; margin:0 0 26px; }
  .tl-cta-row { display:flex; flex-wrap:wrap; gap:12px; }

  .tl-specimen { background:var(--panel); border:1px solid var(--line); border-radius:16px;
    padding:22px 24px; box-shadow:0 20px 50px rgba(0,0,0,.35); }
  .tl-spec-head { display:flex; justify-content:space-between; align-items:baseline;
    font-family:var(--mono); font-size:11px; letter-spacing:.04em; color:var(--faint);
    text-transform:uppercase; padding-bottom:14px; border-bottom:1px solid var(--line); margin-bottom:4px; }
  .tl-spec-tag { color:var(--shared); font-weight:700; }
  .tl-spec-rows > div { display:flex; gap:14px; align-items:baseline; padding:10px 0;
    border-bottom:1px solid var(--line); }
  .tl-spec-rows > div:last-child { border-bottom:0; }
  .tl-spec-rows dt { flex:0 0 84px; font-family:var(--mono); font-size:10.5px; color:var(--faint);
    text-transform:uppercase; letter-spacing:.05em; }
  .tl-spec-rows dd { margin:0; font-size:13px; line-height:1.5; color:var(--ink); }
  .tl-spec-rows dd em { font-style:normal; font-family:var(--mono); font-size:11.5px; color:var(--project); }
  .tl-spec-foreign { display:inline-block; margin-top:4px; font-size:10px; font-weight:700;
    letter-spacing:.05em; text-transform:uppercase; color:var(--shared);
    border:1px solid var(--shared); border-radius:99px; padding:2px 9px; }
  .tl-spec-foot { font-family:var(--mono); font-size:10px; color:var(--faint);
    letter-spacing:.03em; padding-top:12px; }

  /* Ledger */
  .tl-ledger { display:grid; grid-template-columns:repeat(4,1fr); border-top:1px solid var(--line);
    border-bottom:1px solid var(--line); }
  @media (max-width:760px){ .tl-ledger { grid-template-columns:1fr 1fr; } }
  .tl-ledger-cell { padding:18px 22px; border-left:1px solid var(--line); }
  .tl-ledger-cell:first-child { border-left:0; }
  .tl-ledger-v { font-family:var(--mono); font-size:16px; font-weight:700; color:var(--ink); }
  .tl-ledger-l { font-size:12px; color:var(--muted); margin-top:5px; line-height:1.4; }

  /* Sections */
  section.tl-sec { padding:clamp(30px,5vw,58px) 0; }
  h2.tl-h2 { font-size:clamp(21px,2.4vw,28px); margin:0 0 8px; }
  p.tl-lede { color:var(--muted); font-size:14.5px; max-width:70ch; margin:0 0 24px; line-height:1.6; }

  /* Billboard */
  .tl-billboard { background:linear-gradient(180deg,#12172a,#0c1018); border:1px solid var(--line);
    border-radius:20px; padding:clamp(22px,4vw,40px); }
  .tl-bb-eyebrow { font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.06em;
    color:var(--entity); text-transform:uppercase; }
  .tl-billboard h3 { font-size:clamp(20px,2.8vw,30px); font-weight:650; margin:10px 0 26px; max-width:36ch; }
  .tl-bb-flow { display:flex; flex-wrap:wrap; align-items:stretch; gap:8px; }
  .tl-bb-wrap { display:flex; align-items:center; gap:8px; flex:1 1 250px; }
  .tl-bb-card { flex:1; background:rgba(255,255,255,.02); border:1px solid var(--line);
    border-radius:14px; padding:18px 20px; }
  .tl-bb-n { font-family:var(--mono); font-size:10.5px; font-weight:700; letter-spacing:.08em;
    text-transform:uppercase; color:var(--entity); }
  .tl-bb-t { font-size:15.5px; font-weight:700; margin-top:8px; line-height:1.3; }
  .tl-bb-d { font-size:12.5px; line-height:1.55; color:var(--muted); margin:8px 0 0; }
  .tl-bb-chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
  .tl-bb-chips span { font-size:10px; font-weight:600; padding:3px 9px; border-radius:99px;
    background:rgba(124,140,255,.12); color:var(--entity); border:1px solid rgba(124,140,255,.3); }
  .tl-bb-stats { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:12px; }
  .tl-bb-stats > div { background:rgba(255,255,255,.02); border:1px solid var(--line);
    border-radius:9px; padding:9px 10px; }
  .tl-bb-stats b { font-size:16px; color:var(--project); display:block; }
  .tl-bb-stats span { font-size:10.5px; color:var(--muted); line-height:1.3; }
  .tl-bb-arrow { color:var(--faint); font-size:20px; font-weight:700; }

  /* Audience tabs */
  .tl-tabs { display:flex; flex-wrap:wrap; gap:8px; margin:18px 0 18px; }
  .tl-tab { padding:8px 16px; border-radius:99px; border:1px solid var(--line); background:transparent;
    color:var(--muted); font:inherit; font-weight:600; font-size:13px; cursor:pointer; }
  .tl-tab:hover { color:var(--ink); }
  .tl-tab.is-active { background:var(--ink); color:#0b0d12; border-color:var(--ink); }
  .tl-aud-card { background:var(--panel); border:1px solid var(--line); border-radius:16px;
    padding:clamp(20px,3vw,30px); }
  .tl-aud-card h3 { font-size:clamp(16px,1.8vw,20px); margin:0 0 16px; }
  .tl-aud-card ul { margin:0; padding:0; list-style:none; display:grid; gap:12px; }
  .tl-aud-card li { position:relative; padding-left:28px; font-size:13.8px; line-height:1.55; color:#c7cede; }
  .tl-aud-card li::before { content:"✓"; position:absolute; left:0; top:0; color:var(--project); font-weight:800; }

  /* Architecture */
  .tl-diagram { background:var(--panel); border:1px solid var(--line); border-radius:16px;
    padding:clamp(10px,2vw,20px); overflow:auto; }
  .tl-diagram svg { width:100%; height:auto; display:block; font-family:var(--sans); }

  /* Flow (write/read) */
  .tl-flows { display:grid; grid-template-columns:1fr 1fr; gap:22px; }
  @media (max-width:800px){ .tl-flows { grid-template-columns:1fr; } }
  .tl-flow-h { font-size:12px; font-weight:700; letter-spacing:.05em; text-transform:uppercase;
    color:var(--muted); margin-bottom:12px; }
  .tl-flow-h.write { color:var(--project); }
  .tl-flow-h.read { color:var(--entity); }
  .tl-flow { display:flex; flex-direction:column; gap:8px; }
  .tl-step { background:var(--panel); border:1px solid var(--line); border-radius:12px;
    padding:14px 16px; display:flex; gap:12px; align-items:flex-start; }
  .tl-step-num { font-family:var(--mono); font-size:16px; font-weight:700; color:var(--faint);
    flex-shrink:0; width:22px; }
  .tl-step-t { font-size:13.5px; font-weight:700; }
  .tl-step-d { font-size:12.3px; color:var(--muted); margin-top:3px; line-height:1.45; }

  /* Capabilities */
  .tl-cap-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:14px; }
  .tl-cap { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px 20px; }
  .tl-cap::before { content:""; display:block; width:20px; height:3px; background:var(--entity);
    margin-bottom:12px; border-radius:2px; }
  .tl-cap-t { font-size:14.5px; font-weight:700; }
  .tl-cap-d { font-size:12.3px; color:var(--muted); margin-top:6px; line-height:1.45; }

  /* Chips */
  .tl-chips { display:flex; flex-wrap:wrap; gap:9px; }
  .tl-chip { font-size:12.5px; font-weight:600; color:var(--ink); background:var(--raised);
    border:1px solid var(--line); border-radius:99px; padding:7px 14px; }

  /* Configure */
  .tl-cfg-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px;
    margin-bottom:20px; }
  .tl-cfg-card { background:var(--panel); border:1px solid var(--line); border-radius:16px;
    padding:clamp(20px,3vw,26px); }
  .tl-cfg-card h3 { font-size:15.5px; margin:0 0 4px; }
  .tl-cfg-sub { font-size:12.3px; color:var(--muted); margin:0 0 16px; }
  .tl-cfg-steps { margin:0 0 16px; padding:0; list-style:none; display:grid; gap:10px; }
  .tl-cfg-steps li { display:flex; gap:10px; align-items:baseline; font-size:13px; line-height:1.5; color:#c7cede; }
  .tl-cfg-steps b { font-family:var(--mono); font-size:10.5px; color:var(--entity); flex-shrink:0; }
  pre.tl-code { background:#05070b; color:#c9d4ec; border:1px solid var(--line); border-radius:10px;
    padding:14px 16px; font-family:var(--mono); font-size:12.3px; line-height:1.7; overflow-x:auto; margin:0; }
  pre.tl-code .c { color:var(--faint); }
  .tl-env-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(270px,1fr)); gap:12px; }
  .tl-env-item { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .tl-env-item code { font-size:12px; font-weight:700; }
  .tl-env-req { font-size:9.5px; font-weight:700; letter-spacing:.04em; text-transform:uppercase;
    color:var(--home); margin-left:8px; }
  .tl-env-opt { font-size:9.5px; font-weight:700; letter-spacing:.04em; text-transform:uppercase;
    color:var(--faint); margin-left:8px; }
  .tl-env-item p { margin:6px 0 0; font-size:12.3px; color:var(--muted); line-height:1.45; }

  /* Final CTA + footer */
  section.tl-final { text-align:center; padding:clamp(40px,6vw,72px) 24px; }
  section.tl-final h2 { font-size:clamp(22px,3vw,32px); margin:0 0 12px; }
  section.tl-final p { color:var(--muted); font-size:14.5px; margin:0 0 24px; }
  footer.tl-footer { display:flex; flex-wrap:wrap; gap:10px 16px; justify-content:space-between;
    padding:26px clamp(18px,4vw,48px); border-top:1px solid var(--line); color:var(--faint); font-size:12px; }
  footer.tl-footer a:hover { color:var(--ink); }
</style>
</head>
<body class="tl">

<nav class="tl-nav">
  <div class="tl-brand">tacit<span>organizational memory for AI agents</span></div>
  <div class="tl-nav-links">
    <a href="#why">Why</a>
    <a href="#how">How it works</a>
    <a href="#architecture">Architecture</a>
    <a href="#configure">Configure</a>
    <a class="btn btn-primary" href="ui" data-graph-link>Open the graph →</a>
  </div>
</nav>

<header class="tl-hero">
  <div>
    <span class="tl-eyebrow">Azure AI Search · Model Context Protocol · Any agent, any team</span>
    <h1 class="tl-h1">The gotcha your agent just learned — <span class="hl">remembered for the next one</span>.</h1>
    <p class="tl-sub">
      tacit is organizational memory for AI coding agents: Anthropic's memory-stores model,
      rebuilt on Azure so any MCP-speaking agent — GitHub Copilot, Claude Code, Cursor —
      writes durable facts as it works, and the next agent, on any team, in any repo, answers
      from two or three memory hits instead of re-deriving them.
    </p>
    <div class="tl-cta-row">
      <a class="btn btn-primary btn-lg" href="ui" data-graph-link>Open the graph →</a>
      <a class="btn btn-ghost btn-lg" href="#architecture">Read the architecture</a>
    </div>
  </div>

  <figure class="tl-specimen" aria-label="Sample memory hit returned by memory_search">
    <div class="tl-spec-head"><span>Memory hit</span><span class="tl-spec-tag">Specimen</span></div>
    <dl class="tl-spec-rows">
      <div><dt>Query</dt><dd>&ldquo;why does the webhook signature fail in staging&rdquo;</dd></div>
      <div><dt>Path</dt><dd><em>gotchas/webhook-header-casing.md</em></dd></div>
      <div><dt>Finding</dt><dd>The gateway lowercases the header name before HMAC verification.</dd></div>
      <div><dt>Category</dt><dd>gotcha</dd></div>
      <div><dt>Origin</dt><dd>from <em>payments-api</em> <span class="tl-spec-foreign">crossed a team</span></dd></div>
      <div><dt>Score</dt><dd><em>0.91</em> · BM25 + vector + semantic</dd></div>
    </dl>
    <div class="tl-spec-foot">Sample hit · the same ranked section an agent receives</div>
  </figure>
</header>

<section class="tl-ledger wrap" aria-label="Key facts">
  <div class="tl-ledger-cell"><div class="tl-ledger-v">66% fewer tokens</div>
    <div class="tl-ledger-l">Six onboarding questions, cold vs warm — 10,085 → 3,405</div></div>
  <div class="tl-ledger-cell"><div class="tl-ledger-v">1 shared index set</div>
    <div class="tl-ledger-l">Every project in the org, one Azure AI Search service</div></div>
  <div class="tl-ledger-cell"><div class="tl-ledger-v">3 ranking layers</div>
    <div class="tl-ledger-l">BM25 + vector + semantic, fused by Azure's RRF</div></div>
  <div class="tl-ledger-cell"><div class="tl-ledger-v">Any MCP client</div>
    <div class="tl-ledger-l">GitHub Copilot · Claude Code · Cursor · tacit CLI</div></div>
</section>

<section class="tl-sec wrap" id="why">
  <div class="tl-billboard">
    <span class="tl-bb-eyebrow">The 60-second pitch</span>
    <h3>From a session's hard-won lesson to every agent's shortcut — on any team.</h3>
    <div class="tl-bb-flow">
      <div class="tl-bb-wrap">
        <div class="tl-bb-card">
          <div class="tl-bb-n">01 · The problem</div>
          <div class="tl-bb-t">Knowledge dies with the session</div>
          <p class="tl-bb-d">
            The <code>make bootstrap</code> you can't skip, the gateway that lowercases
            webhook headers, the CI job you must never rename — an agent that learns this
            forgets it the moment the session ends. The next agent re-reads the repo and
            relearns it the hard way. Worse at organizational scale: team B relearns what
            team A already paid for.
          </p>
        </div>
        <div class="tl-bb-arrow">→</div>
      </div>
      <div class="tl-bb-wrap">
        <div class="tl-bb-card">
          <div class="tl-bb-n">02 · What it does</div>
          <div class="tl-bb-t">One shared memory, reached by any agent</div>
          <p class="tl-bb-d">
            Agents write durable facts through MCP tools; a MemoryService stamps provenance
            server-side and projects every write into Azure AI Search, so the next
            <code>memory_search</code> answers from a hit, not repo excavation.
          </p>
          <div class="tl-bb-chips">
            <span>Model Context Protocol</span><span>Azure AI Search</span>
            <span>Azure Functions</span><span>Keyless identity</span>
          </div>
        </div>
        <div class="tl-bb-arrow">→</div>
      </div>
      <div class="tl-bb-wrap">
        <div class="tl-bb-card">
          <div class="tl-bb-n">03 · Who it's for</div>
          <div class="tl-bb-t">Any engineering org running AI coding agents</div>
          <p class="tl-bb-d">
            Teams on GitHub Copilot, Claude Code or Cursor who want their agents' lessons to
            outlive the session — and to reach other teams, not just the repo that learned
            them. One endpoint serves every project.
          </p>
        </div>
        <div class="tl-bb-arrow">→</div>
      </div>
      <div class="tl-bb-wrap">
        <div class="tl-bb-card">
          <div class="tl-bb-n">04 · Potential impact</div>
          <div class="tl-bb-t">Less repo excavation, answered in one call</div>
          <div class="tl-bb-stats">
            <div><b>66% fewer</b><span>tokens, onboarding questions cold vs warm</span></div>
            <div><b>Pays back</b><span>before engineer #2 finishes day one</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="tl-sec wrap">
  <h2 class="tl-h2">Built for every stakeholder</h2>
  <div class="tl-tabs" id="tl-tabs"></div>
  <div class="tl-aud-card" id="tl-aud-card"></div>
</section>

<section class="tl-sec wrap" id="architecture">
  <h2 class="tl-h2">Solution architecture</h2>
  <p class="tl-lede">
    Two transports, one tool contract, one MemoryService — fronting a single Azure AI Search
    service shared by every project in the organization.
  </p>
  <div class="tl-diagram">
    <svg viewBox="0 0 1180 580" role="img" aria-label="tacit solution architecture">
      <defs>
        <marker id="aP" markerWidth="10" markerHeight="10" refX="7" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill="#7c8cff"/>
        </marker>
        <marker id="aT" markerWidth="10" markerHeight="10" refX="7" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill="#2ee6a8"/>
        </marker>
        <marker id="aO" markerWidth="10" markerHeight="10" refX="7" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill="#ff9f43"/>
        </marker>
      </defs>

      <!-- Azure boundary -->
      <rect x="268" y="16" width="896" height="524" rx="16" fill="none" stroke="#7c8cff"
            stroke-width="1.3" stroke-dasharray="8 6" opacity="0.6"/>
      <rect x="288" y="2" width="70" height="26" rx="7" fill="#7c8cff"/>
      <text x="323" y="19" text-anchor="middle" font-size="11" font-weight="700" fill="#0b0d12">AZURE</text>

      <!-- Group: Agents -->
      <rect x="16" y="40" width="234" height="420" rx="14" fill="rgba(124,140,255,0.05)" stroke="#7c8cff" stroke-width="1.2"/>
      <text x="34" y="64" font-size="12.5" font-weight="700" fill="#7c8cff">Agents</text>
      <text x="34" y="80" font-size="10.5" fill="#8791a6">any MCP-speaking client</text>

      <g>
        <rect x="36" y="96" width="196" height="76" rx="10" fill="#171b25" stroke="#242a37" stroke-width="1.2"/>
        <rect x="36" y="96" width="4" height="76" fill="#7c8cff"/>
        <text x="52" y="128" font-size="13" font-weight="700" fill="#e8ecf4">GitHub Copilot</text>
        <text x="52" y="146" font-size="10.5" fill="#8791a6">VS Code · Copilot CLI</text>
      </g>
      <g>
        <rect x="36" y="210" width="196" height="76" rx="10" fill="#171b25" stroke="#242a37" stroke-width="1.2"/>
        <rect x="36" y="210" width="4" height="76" fill="#7c8cff"/>
        <text x="52" y="242" font-size="13" font-weight="700" fill="#e8ecf4">Claude Code / Cursor</text>
        <text x="52" y="260" font-size="10.5" fill="#8791a6">any MCP client</text>
      </g>
      <g>
        <rect x="36" y="324" width="196" height="76" rx="10" fill="#171b25" stroke="#242a37" stroke-width="1.2"/>
        <rect x="36" y="324" width="4" height="76" fill="#7c8cff"/>
        <text x="52" y="356" font-size="13" font-weight="700" fill="#e8ecf4">tacit CLI</text>
        <text x="52" y="374" font-size="10.5" fill="#8791a6">uv run tacit ...</text>
      </g>

      <!-- Group: transports -->
      <rect x="284" y="40" width="250" height="310" rx="14" fill="rgba(124,140,255,0.05)" stroke="#7c8cff" stroke-width="1.2" stroke-dasharray="7 5"/>
      <text x="302" y="64" font-size="12.5" font-weight="700" fill="#7c8cff">Two runtimes, one tool contract</text>

      <g>
        <rect x="304" y="96" width="210" height="76" rx="10" fill="#171b25" stroke="#242a37" stroke-width="1.2"/>
        <rect x="304" y="96" width="4" height="76" fill="#7c8cff"/>
        <text x="320" y="128" font-size="13" font-weight="700" fill="#e8ecf4">tacit-mcp (stdio)</text>
        <text x="320" y="146" font-size="10.5" fill="#8791a6">per-engineer Entra identity</text>
      </g>
      <g>
        <rect x="304" y="210" width="210" height="76" rx="10" fill="#171b25" stroke="#242a37" stroke-width="1.2"/>
        <rect x="304" y="210" width="4" height="76" fill="#7c8cff"/>
        <text x="320" y="238" font-size="13" font-weight="700" fill="#e8ecf4">Azure Functions</text>
        <text x="320" y="255" font-size="10.5" fill="#8791a6">Flex Consumption</text>
        <text x="320" y="270" font-size="10.5" fill="#8791a6">/runtime/webhooks/mcp</text>
      </g>

      <!-- MemoryService -->
      <g>
        <rect x="568" y="170" width="250" height="200" rx="14" fill="#171b25" stroke="#2ee6a8" stroke-width="1.4"/>
        <rect x="568" y="170" width="4" height="200" fill="#2ee6a8"/>
        <text x="586" y="200" font-size="14.5" font-weight="700" fill="#e8ecf4">MemoryService</text>
        <text x="586" y="225" font-size="11" fill="#8791a6">stamps project / team / visibility</text>
        <text x="586" y="245" font-size="11" fill="#8791a6">sha256 preconditions on writes</text>
        <text x="586" y="265" font-size="11" fill="#8791a6">immutable versions, tombstone deletes</text>
        <text x="586" y="285" font-size="11" fill="#8791a6">never trusts caller-supplied scope</text>
      </g>

      <!-- Group: AI Search -->
      <rect x="862" y="40" width="302" height="480" rx="14" fill="rgba(255,159,67,0.05)" stroke="#ff9f43" stroke-width="1.2"/>
      <text x="880" y="64" font-size="12.5" font-weight="700" fill="#ff9f43">Azure AI Search</text>
      <text x="880" y="80" font-size="10.5" fill="#8791a6">one index set per organization</text>

      <g>
        <rect x="882" y="96" width="262" height="96" rx="10" fill="#171b25" stroke="#242a37" stroke-width="1.2"/>
        <rect x="882" y="96" width="4" height="96" fill="#ff9f43"/>
        <text x="898" y="122" font-size="12.5" font-weight="700" fill="#e8ecf4">tacit-memories</text>
        <text x="898" y="140" font-size="10.5" fill="#8791a6">system of record</text>
        <text x="898" y="155" font-size="10.5" fill="#8791a6">1 doc per (project, path)</text>
      </g>
      <g>
        <rect x="882" y="210" width="262" height="96" rx="10" fill="#171b25" stroke="#242a37" stroke-width="1.2"/>
        <rect x="882" y="210" width="4" height="96" fill="#ff9f43"/>
        <text x="898" y="236" font-size="12.5" font-weight="700" fill="#e8ecf4">tacit-chunks</text>
        <text x="898" y="254" font-size="10.5" fill="#8791a6">what search runs against</text>
        <text x="898" y="269" font-size="10.5" fill="#8791a6">1 doc per ## section, embedded</text>
      </g>
      <g>
        <rect x="882" y="324" width="262" height="76" rx="10" fill="#171b25" stroke="#242a37" stroke-width="1.2"/>
        <rect x="882" y="324" width="4" height="76" fill="#ff9f43"/>
        <text x="898" y="350" font-size="12.5" font-weight="700" fill="#e8ecf4">tacit-versions</text>
        <text x="898" y="368" font-size="10.5" fill="#8791a6">append-only audit trail</text>
      </g>
      <g>
        <rect x="882" y="418" width="262" height="76" rx="10" fill="#171b25" stroke="#242a37" stroke-width="1.2"/>
        <rect x="882" y="418" width="4" height="76" fill="#ff9f43"/>
        <text x="898" y="444" font-size="12.5" font-weight="700" fill="#e8ecf4">tacit-ontology</text>
        <text x="898" y="462" font-size="10.5" fill="#8791a6">shared vocabulary of entities</text>
      </g>

      <!-- Connectors -->
      <path d="M232,134 L304,134" stroke="#7c8cff" stroke-width="2" fill="none" marker-end="url(#aP)"/>
      <path d="M232,248 L304,248" stroke="#7c8cff" stroke-width="2" fill="none" marker-end="url(#aP)"/>
      <path d="M232,362 Q460,410 568,306" stroke="#7c8cff" stroke-width="1.6" fill="none"
            stroke-dasharray="6 4" marker-end="url(#aP)"/>
      <path d="M514,134 L568,215" stroke="#7c8cff" stroke-width="2" fill="none" marker-end="url(#aP)"/>
      <path d="M514,248 L568,325" stroke="#7c8cff" stroke-width="2" fill="none" marker-end="url(#aP)"/>
      <path d="M818,270 L862,270" stroke="#2ee6a8" stroke-width="2.2" fill="none" marker-end="url(#aT)"/>
      <path d="M1013,192 L1013,210" stroke="#ff9f43" stroke-width="1.6" fill="none"
            stroke-dasharray="5 4" marker-end="url(#aO)"/>
      <path d="M1013,418 C1150,418 1150,306 1013,306" stroke="#ff9f43" stroke-width="1.4" fill="none"
            stroke-dasharray="5 4" marker-end="url(#aO)"/>

      <text x="700" y="248" font-size="10" fill="#8791a6" text-anchor="middle">keyless</text>
      <text x="1085" y="415" font-size="9.5" fill="#8791a6" text-anchor="middle">annotations</text>
      <text x="1030" y="204" font-size="9.5" fill="#8791a6">re-projected</text>

      <!-- Legend -->
      <circle cx="20" cy="548" r="5" fill="#7c8cff"/><text x="32" y="552" font-size="10.5" fill="#8791a6">MCP transport</text>
      <circle cx="150" cy="548" r="5" fill="#2ee6a8"/><text x="162" y="552" font-size="10.5" fill="#8791a6">core service</text>
      <circle cx="270" cy="548" r="5" fill="#ff9f43"/><text x="282" y="552" font-size="10.5" fill="#8791a6">AI Search index</text>
    </svg>
  </div>
</section>

<section class="tl-sec wrap" id="how">
  <h2 class="tl-h2">How a memory flows</h2>
  <div class="tl-flows">
    <div>
      <div class="tl-flow-h write">Write — during a session</div>
      <div class="tl-flow">
        <div class="tl-step"><div class="tl-step-num">01</div><div>
          <div class="tl-step-t">Learn</div>
          <div class="tl-step-d">An agent hits a gotcha, decision, or convention worth keeping.</div></div></div>
        <div class="tl-step"><div class="tl-step-num">02</div><div>
          <div class="tl-step-t">memory_create</div>
          <div class="tl-step-d">The server stamps project/team/visibility — never the caller.</div></div></div>
        <div class="tl-step"><div class="tl-step-num">03</div><div>
          <div class="tl-step-t">Version</div>
          <div class="tl-step-d">An immutable row is appended to tacit-versions; nothing is silently edited.</div></div></div>
        <div class="tl-step"><div class="tl-step-num">04</div><div>
          <div class="tl-step-t">Chunk &amp; embed</div>
          <div class="tl-step-d">Sections are re-projected into tacit-chunks, one doc per heading.</div></div></div>
      </div>
    </div>
    <div>
      <div class="tl-flow-h read">Read — the next session, any repo</div>
      <div class="tl-flow">
        <div class="tl-step"><div class="tl-step-num">01</div><div>
          <div class="tl-step-t">Ask</div>
          <div class="tl-step-d">The next agent calls memory_search — in this repo, or another one entirely.</div></div></div>
        <div class="tl-step"><div class="tl-step-num">02</div><div>
          <div class="tl-step-t">Resolve</div>
          <div class="tl-step-d">Scope × visibility × viewer collapses to one filter before ranking runs.</div></div></div>
        <div class="tl-step"><div class="tl-step-num">03</div><div>
          <div class="tl-step-t">Rank</div>
          <div class="tl-step-d">BM25 + vector candidates fused by RRF, then ordered by the semantic ranker.</div></div></div>
        <div class="tl-step"><div class="tl-step-num">04</div><div>
          <div class="tl-step-t">Answer</div>
          <div class="tl-step-d">Ranked sections return — a "from other-team" badge if the hit crossed a boundary.</div></div></div>
      </div>
    </div>
  </div>
</section>

<section class="tl-sec wrap" id="capabilities">
  <h2 class="tl-h2">Capabilities</h2>
  <div class="tl-cap-grid">
    <div class="tl-cap"><div class="tl-cap-t">memory_search</div>
      <div class="tl-cap-d">Ranked hits across teams — BM25, vector and semantic in one call.</div></div>
    <div class="tl-cap"><div class="tl-cap-t">memory_brief</div>
      <div class="tl-cap-d">One-call onboarding pack for a new repo or a new hire.</div></div>
    <div class="tl-cap"><div class="tl-cap-t">Sha-preconditioned writes</div>
      <div class="tl-cap-d">memory_create/update require expected_sha256 — conflicts return sha_conflict, never a silent overwrite.</div></div>
    <div class="tl-cap"><div class="tl-cap-t">Tombstone deletes</div>
      <div class="tl-cap-d">memory_delete removes the memory and its chunks together; nothing tombstoned can resurface in a hit.</div></div>
    <div class="tl-cap"><div class="tl-cap-t">Immutable version history</div>
      <div class="tl-cap-d">memory_versions — every write appends; nothing is silently edited away.</div></div>
    <div class="tl-cap"><div class="tl-cap-t">Shared vocabulary</div>
      <div class="tl-cap-d">tacit ontology add resolves "pmt-gw", "the gateway" and "Stripe proxy" to one entity, at write time.</div></div>
    <div class="tl-cap"><div class="tl-cap-t">Scope &amp; visibility</div>
      <div class="tl-cap-d">org/team/private crossed with project/project+org/org, resolved server-side per viewer.</div></div>
    <div class="tl-cap"><div class="tl-cap-t">Overlap graph</div>
      <div class="tl-cap-d">/api/ui plots entities between the projects that wrote about them — orange means known to 2+ teams.</div></div>
    <div class="tl-cap"><div class="tl-cap-t">Keyless end to end</div>
      <div class="tl-cap-d">az login locally, managed identity in Azure — no secrets in config or memory payloads.</div></div>
  </div>
</section>

<section class="tl-sec wrap">
  <h2 class="tl-h2">Technology stack</h2>
  <div class="tl-chips">
    <span class="tl-chip">Azure AI Search</span>
    <span class="tl-chip">Azure Functions · Flex Consumption</span>
    <span class="tl-chip">Model Context Protocol</span>
    <span class="tl-chip">Azure Identity</span>
    <span class="tl-chip">Azure OpenAI · optional embeddings</span>
    <span class="tl-chip">Python</span>
    <span class="tl-chip">uv</span>
    <span class="tl-chip">D3.js</span>
  </div>
</section>

<section class="tl-sec wrap" id="configure">
  <h2 class="tl-h2">Configure &amp; run it</h2>
  <p class="tl-lede">
    One backend, so what a team tries locally is exactly what it gets deployed. Wire up a
    project without cloning anything, or stand up the whole service with one command.
  </p>
  <div class="tl-cfg-grid">
    <div class="tl-cfg-card">
      <h3>Wire up your team</h3>
      <p class="tl-cfg-sub">Point an existing service at a new project — no clone needed</p>
      <ol class="tl-cfg-steps">
        <li><b>01</b><span><code>uv sync --extra dev</code> and <code>az login</code> for keyless access.</span></li>
        <li><b>02</b><span><code>tacit provision</code> — once per Search service, not once per team.</span></li>
        <li><b>03</b><span><code>tacit install --project &lt;slug&gt;</code> prints ready-to-paste MCP config
          for Claude Code, VS Code/Copilot and an AGENTS.md snippet.</span></li>
      </ol>
      <pre class="tl-code"><span class="c">$</span> uv sync --extra dev
<span class="c">$</span> az login
<span class="c">$</span> uv run tacit provision
<span class="c">$</span> uv run tacit install --project contoso-payments \
    --search-endpoint https://&lt;svc&gt;.search.windows.net</pre>
    </div>
    <div class="tl-cfg-card">
      <h3>Deploy the service</h3>
      <p class="tl-cfg-sub">AI Search + Flex Consumption Functions + RBAC — keyless</p>
      <ol class="tl-cfg-steps">
        <li><b>01</b><span><code>azd up</code> provisions the search service, the Functions app, and role assignments.</span></li>
        <li><b>02</b><span>An Azure OpenAI embedding deployment is included by default, so hybrid search is on from the start.</span></li>
        <li><b>03</b><span>Teammates who don't clone point their MCP client at <code>/runtime/webhooks/mcp</code>
          with the shared function key.</span></li>
      </ol>
      <pre class="tl-code"><span class="c">$</span> azd up
<span class="c">$</span> <span class="c"># optional: reuse an existing embedding model instead</span>
<span class="c">$</span> azd env set EMBEDDING_ENDPOINT https://&lt;existing&gt;.openai.azure.com</pre>
    </div>
  </div>
  <h3 style="font-size:15px;font-weight:700;margin:8px 0 12px;">Environment variables</h3>
  <div class="tl-env-grid">
    <div class="tl-env-item"><code>TACIT_SEARCH_ENDPOINT</code><span class="tl-env-req">Required</span>
      <p>Azure AI Search service backing every project.</p></div>
    <div class="tl-env-item"><code>TACIT_PROJECT</code><span class="tl-env-opt">Optional</span>
      <p>Repo slug this process reads/writes; the stdio server infers it.</p></div>
    <div class="tl-env-item"><code>TACIT_TEAM</code><span class="tl-env-opt">Optional</span>
      <p>Owning team — resolves memories published at <code>visibility: team</code>.</p></div>
    <div class="tl-env-item"><code>TACIT_DEFAULT_VISIBILITY</code><span class="tl-env-opt">Optional</span>
      <p>Visibility for new memories. Defaults to <code>org</code>.</p></div>
    <div class="tl-env-item"><code>TACIT_AUTH_MODE</code><span class="tl-env-opt">Optional</span>
      <p><code>default-credential</code> (default) or <code>azure-cli</code>.</p></div>
    <div class="tl-env-item"><code>TACIT_EMBEDDING_ENDPOINT</code><span class="tl-env-opt">Optional</span>
      <p>Azure OpenAI endpoint — set it to turn on hybrid (vector) search.</p></div>
    <div class="tl-env-item"><code>TACIT_EMBEDDING_DEPLOYMENT</code><span class="tl-env-opt">Optional</span>
      <p>Embedding deployment name. Defaults to <code>text-embedding-3-small</code>.</p></div>
    <div class="tl-env-item"><code>TACIT_EMBEDDING_DIMENSIONS</code><span class="tl-env-opt">Optional</span>
      <p>Vector size. Defaults to <code>1536</code>.</p></div>
    <div class="tl-env-item"><code>TACIT_USE_VECTORIZER</code><span class="tl-env-opt">Optional</span>
      <p>Let Search embed queries server-side. Defaults to <code>true</code>.</p></div>
  </div>
</section>

<section class="tl-final wrap">
  <h2>See what your org already knows</h2>
  <p>Open the graph, search across your team's memory, and click into any hit — the same ranked sections an agent receives.</p>
  <a class="btn btn-primary btn-lg" href="ui" data-graph-link>Open the graph →</a>
</section>

<footer class="tl-footer wrap">
  <span>tacit — organizational memory for AI agents</span>
  <a href="https://github.com/lordlinus/tacit" target="_blank" rel="noopener">github.com/lordlinus/tacit</a>
  <span>Built on Azure AI Search · Azure Functions · Model Context Protocol</span>
</footer>

<script>
// Any link into the graph/search app needs the same function key this page
// was opened with, since that page requires it and this one does not.
(function () {
  var code = new URLSearchParams(location.search).get("code");
  if (!code) return;
  document.querySelectorAll("[data-graph-link]").forEach(function (a) {
    a.href = a.getAttribute("href") + "?code=" + encodeURIComponent(code);
  });
})();

// Audience tabs — static content, so this is the only interactive bit.
var AUDIENCES = {
  executive: {
    label: "Executive",
    headline: "A shared organizational asset, not a per-repo notebook.",
    points: [
      "Learnings survive the session and reach other teams, not just the repo that wrote them \u2014 team B stops relearning what team A already paid for.",
      "Six onboarding questions on the included sample cost 66% fewer tokens warm than cold, and the one-time write pays back before the second engineer finishes onboarding.",
      "Keyless end to end: az login locally, managed identity in Azure \u2014 no secrets in code, config, or memory payloads.",
      "Works with whatever agent each team already uses \u2014 GitHub Copilot, Claude Code, Cursor \u2014 over the same MCP tools."
    ]
  },
  architect: {
    label: "Architect",
    headline: "One MemoryService, one shared index set, two runtimes.",
    points: [
      "A single MemoryService stamps project/team/visibility server-side and never trusts the caller \u2014 scope \u00d7 visibility \u00d7 viewer resolves to one filter per search.",
      "Two transports, one tool contract: tacit-mcp over stdio for a per-engineer Entra identity, or the same tools over Azure Functions for teams that don't want to clone.",
      "Every write is sha256-preconditioned and versioned \u2014 conflicts return sha_conflict rather than silently overwriting, and deletes tombstone rather than erase.",
      "One Azure AI Search service serves every project in the org: provisioning runs once per service, not once per team."
    ]
  },
  engineer: {
    label: "Solution Engineer",
    headline: "Composable retrieval: BM25, vectors, and a shared vocabulary.",
    points: [
      "tacit-memories is the system of record; tacit-chunks is a derived, disposable projection \u2014 one doc per section \u2014 so a hit costs the matching section, not the whole file.",
      "Hybrid search fuses BM25 and vector candidates with Azure's RRF, then a semantic ranker orders what survives; each layer degrades gracefully on its own.",
      "Vectors are optional: set TACIT_EMBEDDING_ENDPOINT and tacit uses integrated vectorization, so only the search service needs model access, not every writer.",
      "A small controlled vocabulary resolves \u201cpmt-gw\u201d, \u201cthe gateway\u201d and \u201cStripe proxy\u201d to one canonical entity at write time \u2014 deterministic, no model, no drift."
    ]
  },
  technical: {
    label: "Technical",
    headline: "Provenance stamped server-side, never caller-supplied.",
    points: [
      "memory_create/update never take project, team, or visibility from the request as truth \u2014 the server stamps them, versions the write, then re-projects sections into tacit-chunks.",
      "memory_search resolves scope crossed with visibility into one filter before ranking; a hit from another team carries a project field \u2014 a same-team hit does not.",
      "memory_delete tombstones the memory and removes its chunks together, so deleted content can never resurface in a search hit.",
      "The overlap graph and its search box call the exact same MemoryService and memory_search an agent does \u2014 nothing rendered there is a mock."
    ]
  }
};

(function () {
  var order = ["executive", "architect", "engineer", "technical"];
  var tabs = document.getElementById("tl-tabs");
  var card = document.getElementById("tl-aud-card");

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function render(key) {
    var a = AUDIENCES[key];
    card.innerHTML = "<h3>" + esc(a.headline) + "</h3><ul>" +
      a.points.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul>";
    tabs.querySelectorAll(".tl-tab").forEach(function (btn) {
      btn.classList.toggle("is-active", btn.dataset.key === key);
    });
  }

  tabs.innerHTML = order.map(function (key) {
    return '<button class="tl-tab" data-key="' + key + '">' + esc(AUDIENCES[key].label) + "</button>";
  }).join("");
  tabs.querySelectorAll(".tl-tab").forEach(function (btn) {
    btn.addEventListener("click", function () { render(btn.dataset.key); });
  });
  render("executive");
})();
</script>
</body>
</html>
"""
