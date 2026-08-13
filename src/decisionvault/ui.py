from __future__ import annotations


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>DecisionVault — Persistent Decision Memory</title>
  <style>
    :root{color-scheme:dark;--bg:#080d1a;--panel:#11182a;--text:#edf2ff;--muted:#9eabc4;--line:#26334d;--accent:#8ab4ff;--good:#8ee6b6;--warn:#ffd58a}
    *{box-sizing:border-box} body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at top,#172440 0,var(--bg) 48%);color:var(--text)}
    main{width:min(1120px,calc(100% - 32px));margin:auto;padding:44px 0 64px}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}
    h1{margin:8px 0 12px;font-size:clamp(38px,7vw,72px);line-height:.98;letter-spacing:-.04em}.lede{max-width:780px;color:var(--muted);font-size:clamp(16px,2.5vw,20px);line-height:1.6}
    .badges{display:flex;flex-wrap:wrap;gap:8px;margin:22px 0 28px}.badge{border:1px solid var(--line);background:rgba(17,24,42,.82);border-radius:999px;padding:8px 12px;color:#cbd7ef;font-size:13px}
    .grid{display:grid;grid-template-columns:1.1fr .9fr;gap:18px}.card{border:1px solid var(--line);background:linear-gradient(180deg,rgba(17,24,42,.97),rgba(12,18,32,.97));border-radius:20px;padding:22px;box-shadow:0 20px 60px rgba(0,0,0,.2)}
    h2{margin:0 0 8px;font-size:20px}.muted,.foot{color:var(--muted);line-height:1.58}.foot{margin-top:26px;font-size:13px}label{display:block;margin:18px 0 8px;font-size:13px;font-weight:700;color:#cdd8ef}
    input{width:100%;border:1px solid var(--line);border-radius:12px;padding:13px 14px;background:#090e1a;color:var(--text);outline:none}input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(138,180,255,.14)}
    button{margin-top:12px;width:100%;border:0;border-radius:12px;padding:14px 16px;font-weight:800;background:linear-gradient(135deg,#8ab4ff,#a493ff);color:#07101e;cursor:pointer}button:disabled{cursor:wait;opacity:.62}
    .status{margin-top:12px;min-height:22px;font-size:13px;color:var(--muted)}.health{display:flex;align-items:center;gap:9px;margin-top:18px;font-size:14px}.dot{width:9px;height:9px;border-radius:50%;background:var(--warn);box-shadow:0 0 16px currentColor}.dot.ok{background:var(--good)}
    .flow{display:grid;gap:10px;margin-top:18px}.step{border:1px solid var(--line);border-radius:12px;padding:12px 14px;color:#cbd7ef;background:rgba(9,14,26,.55)}
    .results{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px}.result{border:1px solid var(--line);border-radius:16px;padding:18px;background:rgba(8,13,24,.72);min-height:210px}.result.off{border-color:#4a4455}.result.on{border-color:#315e52}.result h3{margin:0 0 12px;font-size:15px;color:#d7e1f5}
    .strategy{font-size:clamp(20px,3vw,28px);font-weight:900;overflow-wrap:anywhere}.kv{margin-top:12px;font-size:13px;color:var(--muted);line-height:1.7}.explanation{margin-top:12px;color:#d7e1f5;line-height:1.55;font-size:14px}.delta{margin-top:16px;padding:14px 16px;border-radius:14px;border:1px solid #315e52;background:rgba(49,94,82,.16);color:#d8f6e6;display:none}code{color:#d9e5ff}
    @media(max-width:820px){.grid,.results{grid-template-columns:1fr}main{padding-top:28px}}
  </style>
</head>
<body><main>
  <div class="eyebrow">CockroachDB × AWS · Agentic Memory</div>
  <h1>DecisionVault</h1>
  <p class="lede">Outcome-aware persistent memory for agent teams, demonstrated on payment recovery. This live proof shows one agent recording what failed and a second agent changing behavior after recalling that outcome from CockroachDB.</p>
  <div class="badges"><span class="badge">CockroachDB Cloud</span><span class="badge">Distributed Vector Index</span><span class="badge">Managed MCP</span><span class="badge">AWS Lambda</span><span class="badge">NVIDIA bounded advisor</span></div>
  <section class="grid">
    <div class="card"><h2>Run the live cross-agent proof</h2><p class="muted">Agent A records a temporary failed episode. Agent B then handles the same similar situation with Memory OFF and Memory ON. The server returns the comparison and deletes the temporary scope.</p>
      <label for="token">Demo access token</label><input id="token" type="password" autocomplete="off" placeholder="Paste the judge/demo token" /><button id="run" type="button">Run live memory proof</button><div id="status" class="status" role="status" aria-live="polite"></div><div class="health"><span id="healthDot" class="dot"></span><span id="healthText">Checking AWS Lambda…</span></div>
    </div>
    <div class="card"><h2>Authority boundary</h2><div class="flow"><div class="step">1 · Agent A records outcome evidence in a shared CockroachDB scope</div><div class="step">2 · Agent B recalls that evidence and the deterministic policy commits the strategy</div><div class="step">3 · NVIDIA may explain the committed strategy only</div><div class="step">4 · Scope boundaries prevent unrelated agents from seeing the memory</div></div><p class="foot">The model cannot select a different strategy. Provider failure never blocks or changes the deterministic memory-aware decision.</p></div>
  </section>
  <section class="card" style="margin-top:18px"><h2>Same situation. One controlled variable: persistent memory.</h2><div class="results">
    <div class="result off"><h3>Memory OFF</h3><div id="offStrategy" class="strategy">—</div><div id="offKv" class="kv">Run the live proof to populate this result.</div><div id="offExplanation" class="explanation"></div></div>
    <div class="result on"><h3>Memory ON</h3><div id="onStrategy" class="strategy">—</div><div id="onKv" class="kv">Run the live proof to populate this result.</div><div id="onExplanation" class="explanation"></div></div>
  </div><div id="delta" class="delta"></div></section>
  <p class="foot">Production hardening: health is public and read-only; mutating/demo calls require <code>X-DecisionVault-Token</code>; secrets are not embedded in this page; error responses do not expose database URLs, API keys, or AWS credentials.</p>
</main><script>
const $=id=>document.getElementById(id),run=$('run');
async function health(){try{const r=await fetch('/health',{cache:'no-store'}),j=await r.json();if(!r.ok||j.status!=='ok')throw new Error();$('healthDot').classList.add('ok');$('healthText').textContent=`Live on AWS Lambda · CockroachDB ${j.database_configured?'configured':'missing'} · NVIDIA ${j.nvidia_advisor_configured?'configured':'missing'}`}catch(_){$('healthText').textContent='Health check unavailable'}}
function render(prefix,v){const producers=(v.recalled_producer_agent_ids||[]).join(',')||'none';$(prefix+'Strategy').textContent=v.strategy||'—';$(prefix+'Kv').textContent=`memory_influenced=${v.memory_influenced} · recalled=${(v.recalled_episode_ids||[]).length} · producer_agents=${producers} · provider=${v.model_provider||'none'}`;$(prefix+'Explanation').textContent=v.model_explanation||''}
run.addEventListener('click',async()=>{const token=$('token').value.trim();if(!token){$('status').textContent='Enter the demo access token first.';return}run.disabled=true;$('status').textContent='Agent A records outcome → Agent B Memory OFF → Agent B Memory ON → cleanup…';const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),28000);try{const r=await fetch('/demo',{method:'POST',headers:{'content-type':'application/json','x-decisionvault-token':token},body:'{}',signal:controller.signal}),j=await r.json();if(!r.ok)throw new Error(j.error==='unauthorized'?'Invalid demo token.':`Demo failed (${r.status}).`);render('off',j.memory_off);render('on',j.memory_on);const changed=j.memory_off.strategy!==j.memory_on.strategy&&j.memory_on.memory_influenced===true&&j.cross_agent_memory_used===true;$('delta').style.display='block';$('delta').textContent=changed?`PASS · ${j.producer_agent_id} memory changed ${j.consumer_agent_id} behavior: ${j.memory_off.strategy} → ${j.memory_on.strategy}. Temporary scope cleaned=${j.cleaned}.`:'The run completed, but the expected cross-agent causal strategy change was not observed.';$('status').textContent='Live cross-agent proof completed.'}catch(e){$('status').textContent=e.name==='AbortError'?'Demo timed out. Try again.':e.message}finally{clearTimeout(timer);run.disabled=false}});health();
</script></body></html>"""
