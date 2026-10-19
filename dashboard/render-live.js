// Renders the header run bar and the live-run view: the node-link graph, the KPI row and the transcript.
// Reads window.MOCK, built from a real run folder by build_data.py.
(function () {
  const M = window.MOCK;
  const el = (id) => document.getElementById(id);

  // The evidence note: what kind of numbers these are (scripted / recorded / measured).
  el("evidencenote").textContent = "\u00b7 " + M.evidence;

  el("runbar").innerHTML = [
    ["Topology", M.run.topology],
    ["Setting", M.run.setting],
    ["Mode", M.run.mode],
    ["Model", M.run.model],
    ["Trial", M.run.trial],
  ].map(([k, v]) => `<span class="pill">${k}: <b>${v}</b></span>`).join("");

  el("graphsub").textContent = M.graph.sub;

  // ---------- The graph ----------
  // Visual language from the Armorer console attack map: a node is a rect on --panel with a hairline,
  // the state ring carries meaning (danger / accent / line-control), names are sans, kinds are mono
  // uppercase, an edge label is mono uppercase with a paper halo (paint-order stroke), and a marker
  // edge gets a soft halo. No dashed or dotted lines anywhere.
  const svg = el("graphsvg");
  const W = 744, H = 300;
  const nodeW = 196, nodeH = 108, seedW = 150, seedH = 96;
  const y1 = 8, y2 = 186;              // row tops
  const sx = 38, a1x = 248, a2x = 510; // row 1: seed, Alice, Bob
  const b1x = 12, b2x = 274, b3x = 536; // row 2: Carol, Dan, Eve (left to right)
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", "100%");

  const stateStyle = {
    infected: { stroke: "var(--danger)", sw: 1.5, pill: ["\u2715", "Infected", "var(--danger-tint)", "var(--danger-border)", "var(--danger)"] },
    clean: { stroke: "var(--accent)", sw: 1.5, pill: ["\u2713", "Clean", "var(--accent-tint)", "var(--accent-border)", "var(--accent-text)"] },
    running: { stroke: "var(--line-control)", sw: 1.25, pill: ["\u22ef", "Running", "var(--panel-strong)", "var(--line-strong)", "var(--muted)"] },
    seed: { stroke: "var(--warning)", sw: 1.5, pill: ["\u25c6", "Canary", "var(--warning-tint)", "var(--warning-border)", "var(--warning)"] },
  };

  function pill(x, y, st) {
    const [icon, text, bg, border, color] = st.pill;
    const w = text.length * 6.8 + 36, h = 20;
    return `<g>
      <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="6" fill="${bg}" stroke="${border}"/>
      <circle cx="${x + 11}" cy="${y + h / 2}" r="8" fill="${color}"/>
      <text x="${x + 11}" y="${y + h / 2 + 3.6}" text-anchor="middle" font-family="var(--font-mono)" font-size="9" font-weight="700" fill="#ffffff">${icon}</text>
      <text x="${x + 25}" y="${y + h / 2 + 4.2}" font-size="11" font-weight="600" fill="${color}">${text}</text>
    </g>`;
  }

  function assistantNode(n, x, y) {
    const st = stateStyle[n.state];
    const sigs = [["memory", "MEM"], ["shared", "SHARED"], ["upload", "UPLD"]].map(([k, lab], i) => {
      const on = n[k] === "on";
      const px = x + 14 + i * 60;
      const fill = on ? "var(--viz-bad)" : "none";
      const stroke = on ? "var(--viz-bad)" : "var(--line-strong)";
      return `<rect x="${px}" y="${y + nodeH - 25}" width="9" height="9" rx="2.5" fill="${fill}" stroke="${stroke}"/>
        <text x="${px + 14}" y="${y + nodeH - 17}" font-family="var(--font-mono)" font-size="10.75" letter-spacing="0.08em" fill="var(--muted)">${lab}</text>`;
    }).join("");
    return `<g>
      <rect x="${x}" y="${y}" width="${nodeW}" height="${nodeH}" rx="10" fill="var(--panel)" stroke="${st.stroke}" stroke-width="${st.sw}"/>
      <text x="${x + 14}" y="${y + 23}" font-family="var(--font-mono)" font-size="11" letter-spacing="0.14em" fill="var(--muted)">HOP ${n.hop}</text>
      <text x="${x + 14}" y="${y + 47}" font-size="18" font-weight="600" fill="var(--text)">${n.name}</text>
      <text x="${x + 14}" y="${y + 63}" font-size="11" fill="var(--muted)">${n.user}</text>
      ${sigs}
      ${pill(x + nodeW - 96, y + 12, st)}
    </g>`;
  }

  function seedNode(s, x, y) {
    const st = stateStyle.seed;
    return `<g>
      <rect x="${x}" y="${y}" width="${seedW}" height="${seedH}" rx="10" fill="var(--warning-tint)" stroke="${st.stroke}" stroke-width="1.5"/>
      <text x="${x + 12}" y="${y + 21}" font-family="var(--font-mono)" font-size="11" letter-spacing="0.14em" fill="var(--muted)">SEED</text>
      <text x="${x + 12}" y="${y + 43}" font-size="15" font-weight="600" fill="var(--text)">${s.name}</text>
      <text x="${x + 12}" y="${y + 61}" font-family="var(--font-mono)" font-size="11" fill="var(--muted)">${s.file}</text>
      ${pill(x + 12, y + 68, st)}
    </g>`;
  }

  // Horizontal edge with arrowhead and an uppercase mono label under the line, paper-haloed.
  function hedge(x1, x2, y, e) {
    const gap = x2 - x1;
    const c = Math.max(8, Math.min(40, gap * 0.4));
    const marker = e.marker === true, pending = e.marker === null;
    const color = marker ? "var(--danger)" : pending ? "var(--line-control)" : "var(--line-strong)";
    const halo = marker ? `<path d="M${x1},${y} C${x1 + c},${y} ${x2 - c},${y} ${x2},${y}" fill="none" stroke="var(--danger)" stroke-width="8" stroke-opacity="0.14"/>` : "";
    const label = e.label && !pending
      ? `<text x="${(x1 + x2) / 2}" y="${y - 7}" text-anchor="middle" font-family="var(--font-mono)" font-size="10.75" font-weight="500" letter-spacing="0.08em" fill="${marker ? "var(--danger)" : "var(--muted)"}" stroke="var(--bg)" stroke-width="4" paint-order="stroke">${e.label.toUpperCase()}</text>`
      : pending ? `<text x="${(x1 + x2) / 2}" y="${y - 7}" text-anchor="middle" font-family="var(--font-mono)" font-size="10.75" letter-spacing="0.08em" fill="var(--muted)">\u22ef</text>` : "";
    return `<g>${halo}<path d="M${x1},${y} C${x1 + c},${y} ${x2 - c},${y} ${x2},${y}" fill="none" stroke="${color}" stroke-width="1.5"/>
      <path d="M${x2 + 1},${y} l-9 -5 l0 10 z" fill="${color}"/>${label}</g>`;
  }

  // The wrap edge: end of row 1 down and back to the start of row 2, like a line return.
  function wrapEdge(x1, ya, x2, yb, e) {
    const marker = e.marker === true;
    const color = marker ? "var(--danger)" : "var(--line-strong)";
    const yTop = ya, yBot = yb;
    const midY = (yTop + yBot) / 2;
    const d = `M${x1},${yTop} C${x1},${midY} ${x2},${midY} ${x2},${yBot}`;
    const halo = marker ? `<path d="${d}" fill="none" stroke="var(--danger)" stroke-width="8" stroke-opacity="0.14"/>` : "";
    const label = `<text x="${(x1 + x2) / 2}" y="${midY - 6}" text-anchor="middle" font-family="var(--font-mono)" font-size="10.75" font-weight="500" letter-spacing="0.08em" fill="${marker ? "var(--danger)" : "var(--muted)"}" stroke="var(--bg)" stroke-width="4" paint-order="stroke">${e.label.toUpperCase()}</text>`;
    return `<g>${halo}<path d="${d}" fill="none" stroke="${color}" stroke-width="1.5"/>
      <path d="M${x2},${yBot + 1} l-5 -9 l10 0 z" fill="${color}"/>${label}</g>`;
  }

  const N = M.graph.nodes;
  const mid1 = y1 + nodeH / 2, mid2 = y2 + nodeH / 2;
  const edgesSvg = [
    hedge(sx + seedW, a1x, mid1, M.graph.edges[0]),
    hedge(a1x + nodeW, a2x, mid1, M.graph.edges[1]),
    wrapEdge(a2x + nodeW / 2, y1 + nodeH, b1x + nodeW / 2, y2, M.graph.edges[2]),
    hedge(b1x + nodeW, b2x, mid2, M.graph.edges[3]),
    hedge(b2x + nodeW, b3x, mid2, M.graph.edges[4]),
  ].join("");

  const nodesSvg = [
    seedNode(M.graph.seed, sx, y1),
    assistantNode(N[0], a1x, y1),
    assistantNode(N[1], a2x, y1),
    assistantNode(N[2], b1x, y2),
    assistantNode(N[3], b2x, y2),
    assistantNode(N[4], b3x, y2),
  ].join("");

  svg.innerHTML = edgesSvg + nodesSvg;

  el("legend").innerHTML = M.graph.legend.map(([state, text]) => {
    const st = stateStyle[state];
    const bg = state === "seed" ? "var(--warning-tint)"
      : state === "infected" ? "var(--danger-tint)"
      : state === "clean" ? "var(--accent-tint)" : "var(--panel-strong)";
    return `<span><i class="sw" style="background:${bg};border-color:${st.stroke}"></i>${text}</span>`;
  }).join("") +
    `<span><i class="sw" style="background:var(--viz-bad);border-color:var(--viz-bad)"></i>Signal on: MEM / SHARED / UPLD squares</span>`;

  // ---------- KPI strip inside the graph card ----------
  el("kpis").innerHTML = M.kpis.map((k) => `
    <div class="kpi">
      <div class="label">${k.label}</div>
      <div class="value">${k.value}</div>
      <div class="note">${k.note}</div>
    </div>`).join("");

  // ---------- The transcript: one session at a time, in order ----------
  el("lines").innerHTML = M.log.map((l) => {
    if (l.kind === "session") {
      return `<div class="tl session"><span class="t">${l.t}</span><span>${l.who}</span><span>hop ${l.hop}</span><span class="rule"></span><span class="note">${l.note}</span></div>`;
    }
    const tag = l.tag ? ` <span class="tag ${l.tag[0]}">${l.tag[1]}</span>` : "";
    if (l.kind === "say") return `<div class="tl say">${l.text}</div>`;
    if (l.kind === "tool") return `<div class="tl tool"><span class="name">${l.name}</span>(<span class="arg">${l.arg}</span>)</div>`;
    return `<div class="tl result">${l.text}${tag}</div>`;
  }).join("");
})();
