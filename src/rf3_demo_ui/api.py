from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles


def _backend_base_url() -> str:
    return os.getenv("RF3_API_BASE_URL", "").rstrip("/")


def _require_backend() -> str:
    base = _backend_base_url()
    if not base:
        raise HTTPException(
            status_code=500,
            detail="RF3_API_BASE_URL is not configured for this demo UI.",
        )
    return base


app = FastAPI(title="RosettaFold3 demo UI", version="0.1.0")

# Serve static assets bundled in the image (e.g., 3Dmol.js).
_static_dir = Path(__file__).with_name("static")
if _static_dir.exists():
  app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/")
def demo_page() -> HTMLResponse:
    samples = [
        {
            "name": "Simple protein (short)",
            "inputs": {
                "name": "simple_protein_demo",
                "components": [
                    {"seq": "MKKFFDSRREQMKKFFDSRREQMKKFFDSRREQ", "chain_id": "A"}
                ],
            },
            "overrides": [],
        },
        {
            "name": "Single chain (medium)",
            "inputs": {
                "name": "single_chain_medium",
                "components": [
                    {
                        "seq": "MSTNPKPQRKTKRNTNRRPQDVKFPGGGQIVGGVLTGADSVGVGKSTLLLRFYSQGQGKTK",
                        "chain_id": "A",
                    }
                ],
            },
            "overrides": [],
        },
        {
            "name": "Two chains (toy complex)",
            "inputs": {
                "name": "toy_complex",
                "components": [
                    {"seq": "MKKFFDSRREQMKKFFDSRREQ", "chain_id": "A"},
                    {"seq": "GHHHHHHSSGVDLGTENLYFQSM", "chain_id": "B"},
                ],
            },
            "overrides": [],
        },
    ]

    samples_json = json.dumps(samples)
    default_payload = json.dumps(samples[0]["inputs"], indent=2)

    html = f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <meta http-equiv=\"Cache-Control\" content=\"no-store, max-age=0\" />
    <meta http-equiv=\"Pragma\" content=\"no-cache\" />
    <meta http-equiv=\"Expires\" content=\"0\" />
    <title>RosettaFold3 蛋白质实验室</title>
    <style>
      :root {{
        --bg: #0b1220;
        --card: rgba(255, 255, 255, 0.06);
        --card2: rgba(255, 255, 255, 0.03);
        --border: rgba(255, 255, 255, 0.10);
        --text: #e5e7eb;
        --muted: rgba(229, 231, 235, 0.72);
        --accent: #60a5fa;
        --accent2: #22c55e;
        --danger: #f87171;
        --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: var(--sans);
        background: radial-gradient(1100px 700px at 20% 0%, rgba(96, 165, 250, 0.15), transparent 60%),
                    radial-gradient(900px 600px at 80% 10%, rgba(34, 197, 94, 0.12), transparent 55%),
                    var(--bg);
        color: var(--text);
      }}
      a {{ color: var(--accent); }}
      code {{ font-family: var(--mono); color: rgba(229,231,235,0.9); }}
      .container {{ max-width: 1180px; margin: 0 auto; padding: 22px; }}
      .header {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; }}
      .title {{ margin: 0; font-size: 28px; letter-spacing: 0.2px; }}
      .subtitle {{ margin: 6px 0 0 0; color: var(--muted); font-size: 13px; }}
      .grid {{ display: grid; gap: 14px; margin-top: 14px; }}
      @media (min-width: 980px) {{
        .grid {{ grid-template-columns: 1.1fr 0.9fr; }}
        .span2 {{ grid-column: 1 / -1; }}
      }}
      .card {{
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 14px;
        box-shadow: 0 10px 26px rgba(0,0,0,0.25);
      }}
      .card h2 {{ margin: 0 0 8px 0; font-size: 16px; }}
      .hint {{ color: var(--muted); font-size: 13px; margin: 0 0 10px 0; }}
      label {{ display: inline-flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
      select {{
        background: var(--card2);
        color: var(--text);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 8px 10px;
      }}
      textarea {{
        width: 100%;
        background: rgba(0,0,0,0.25);
        color: var(--text);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 10px 12px;
        font-family: var(--mono);
        font-size: 12px;
        line-height: 1.4;
      }}
      pre {{
        background: rgba(0,0,0,0.25);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 10px 12px;
        font-family: var(--mono);
        font-size: 12px;
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 320px;
        overflow: auto;
        margin: 0;
      }}
      .row {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
      .btn {{
        appearance: none;
        border: 1px solid rgba(255,255,255,0.14);
        background: rgba(96,165,250,0.18);
        color: var(--text);
        padding: 8px 12px;
        border-radius: 12px;
        cursor: pointer;
        font-weight: 600;
      }}
      .btn:hover {{ border-color: rgba(255,255,255,0.22); }}
      .btn.primary {{ background: rgba(96,165,250,0.28); }}
      .btn.secondary {{ background: rgba(148,163,184,0.14); }}
      .btn.small {{ padding: 6px 10px; border-radius: 10px; font-weight: 600; }}
      .linkbtn {{
        background: none;
        border: none;
        color: var(--accent);
        cursor: pointer;
        padding: 0;
        font-weight: 600;
        text-decoration: underline;
      }}
      .pill {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.12);
        color: var(--muted);
        font-size: 12px;
      }}
      #viewerMsg {{ color: var(--muted); margin: 0 0 10px 0; font-size: 13px; }}
      /* 3Dmol creates an absolute-positioned canvas; keep it inside this box. */
      #viewer {{
        width: 100%;
        height: 600px;
        border-radius: 12px;
        border: 1px solid var(--border);
        background: rgba(0,0,0,0.22);
        position: relative;
        overflow: hidden;
      }}
      #files {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
      .file {{
        display: flex;
        gap: 10px;
        align-items: center;
        flex-wrap: wrap;
        padding: 10px 12px;
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.10);
        background: rgba(0,0,0,0.18);
      }}
      .filename {{
        font-family: var(--mono);
        font-size: 12px;
        color: rgba(229,231,235,0.92);
      }}
      .tag {{
        font-family: var(--mono);
        font-size: 11px;
        padding: 3px 8px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.12);
        color: rgba(229,231,235,0.75);
        background: rgba(255,255,255,0.06);
      }}
    </style>
  </head>
  <body>
    <div class=\"container\">
      <div class=\"header\">
        <div>
          <h1 class=\"title\">RosettaFold3 蛋白质实验室</h1>
          <p class=\"subtitle\">Submit to <code>/fold</code>, poll <code>/jobs/&lt;job_id&gt;</code>. Health: <a href=\"/health\" target=\"_blank\" rel=\"noreferrer\">/health</a></p>
        </div>
        <div class=\"pill\">Tip: output filenames trigger download (no inline preview).</div>
      </div>

      <div class=\"grid\">
        <div class=\"card\">
          <h2>Inputs</h2>
          <p class=\"hint\">Pick a sample, optionally edit JSON + Hydra overrides, then run.</p>

          <div class=\"row\" style=\"margin-bottom: 10px;\">
            <label>
              Sample
              <select id=\"sampleSelect\"></select>
            </label>
            <button id=\"loadSampleBtn\" class=\"btn secondary\" type=\"button\">Load sample</button>
            <button id=\"submitBtn\" class=\"btn primary\" type=\"button\">Run fold</button>
          </div>

          <p class=\"hint\">Service expects <code>{{name, components:[{{seq, chain_id}}...]}}</code>.</p>
          <textarea id=\"inputsJson\" rows=\"16\">{default_payload}</textarea>

          <div style=\"height: 10px;\"></div>
          <p class=\"hint\">Hydra overrides (one per line), e.g. <code>num_steps=50</code>.</p>
          <textarea id=\"overrides\" rows=\"5\"></textarea>
        </div>

        <div class=\"card\">
          <h2>Status</h2>
          <p class=\"hint\">Job JSON + live logs tail while running.</p>

          <div class=\"row\" style=\"margin-bottom: 10px;\">
            <span class=\"tag\">Job status</span>
          </div>
          <pre id=\"status\">Idle</pre>

          <div style=\"height: 12px;\"></div>
          <div class=\"row\" style=\"margin-bottom: 10px;\">
            <span class=\"tag\">Live logs</span>
          </div>
          <pre id=\"logs\">(no logs yet)</pre>
        </div>

        <div class=\"card span2\">
          <h2>Visualization</h2>
          <p class=\"hint\">After success, click <b>Render</b> next to <code>predicted.pdb</code>/<code>predicted.cif</code> to visualize. Other outputs download.</p>
          <div id=\"viewerMsg\"></div>
          <div id=\"viewer\"></div>
        </div>

        <div class=\"card span2\">
          <h2>Outputs</h2>
          <p class=\"hint\">Click a filename to download. Structure files also have a Render button.</p>
          <ul id=\"files\"></ul>
        </div>
      </div>
    </div>

    <!-- 3Dmol.js for structure visualization (bundled in this image). -->
    <script src=\"/static/3Dmol-min.js\"></script>

    <script>
      const samples = {samples_json};
      const sampleSelect = document.getElementById('sampleSelect');
      const inputsJson = document.getElementById('inputsJson');
      const overrides = document.getElementById('overrides');
      const statusEl = document.getElementById('status');
      const logsEl = document.getElementById('logs');
      const filesEl = document.getElementById('files');
      const viewerEl = document.getElementById('viewer');
      const viewerMsgEl = document.getElementById('viewerMsg');
      const loadSampleBtn = document.getElementById('loadSampleBtn');
      const submitBtn = document.getElementById('submitBtn');

      function setStatus(text) {{
        statusEl.textContent = text;
      }}

      function setLogs(text) {{
        if (!logsEl) return;
        logsEl.textContent = text;
      }}

      function clearFiles() {{
        while (filesEl.firstChild) filesEl.removeChild(filesEl.firstChild);
      }}

      async function downloadFile(jobId, filename) {{
        const url = '/jobs/' + jobId + '/files/' + encodeURIComponent(filename);
        const resp = await fetch(url, {{ cache: 'no-store' }});
        if (!resp.ok) {{
          throw new Error('Download failed: HTTP ' + resp.status);
        }}
        const blob = await resp.blob();

        const a = document.createElement('a');
        const objectUrl = URL.createObjectURL(blob);
        a.href = objectUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(objectUrl);
      }}

      function renderFiles(jobId, files) {{
        clearFiles();
        if (!files || files.length === 0) return;
        for (const filename of files) {{
          const li = document.createElement('li');
          li.className = 'file';

          const nameSpan = document.createElement('span');
          nameSpan.className = 'filename';
          nameSpan.textContent = filename;
          li.appendChild(nameSpan);

          const lower = String(filename).toLowerCase();
          const ext = lower.includes('.') ? lower.slice(lower.lastIndexOf('.') + 1) : '';
          if (ext) {{
            const tag = document.createElement('span');
            tag.className = 'tag';
            tag.textContent = '.' + ext;
            li.appendChild(tag);
          }}

          const isStructure = lower.endsWith('.pdb') || lower.endsWith('.cif') || lower.endsWith('.mmcif');
          if (isStructure) {{
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = 'Render';
            btn.className = 'btn small secondary';
            btn.addEventListener('click', async () => {{
              try {{
                await renderStructure(jobId, filename);
              }} catch (e) {{
                setViewerMessage('Viewer error: ' + e);
              }}
            }});
            li.appendChild(btn);
          }}

          const dlBtn = document.createElement('button');
          dlBtn.type = 'button';
          dlBtn.textContent = 'Download';
          dlBtn.className = 'btn small primary';
          dlBtn.addEventListener('click', async () => {{
            try {{
              await downloadFile(jobId, filename);
            }} catch (e) {{
              setStatus('Download error: ' + e);
            }}
          }});
          li.appendChild(dlBtn);

          filesEl.appendChild(li);
        }}
      }}

      function setViewerMessage(text) {{
        if (!viewerMsgEl) return;
        viewerMsgEl.textContent = text;
      }}

      async function renderStructure(jobId, filename) {{
        if (!viewerEl) return;

        setViewerMessage('Loading: ' + filename + ' ...');

        // 3Dmol is attached to window as $3Dmol.
        const D = window.$3Dmol;
        if (!D) {{
          setViewerMessage('3D viewer not available (3Dmol.js did not load).');
          return;
        }}

        try {{
          const url = `/jobs/${{jobId}}/files/${{encodeURIComponent(filename)}}`;
          const resp = await fetch(url, {{ cache: 'no-store' }});
          if (!resp.ok) {{
            setViewerMessage('Failed to load structure: HTTP ' + resp.status);
            return;
          }}

          const text = await resp.text();
          const ext = (filename.split('.').pop() || '').toLowerCase();
          const format = (ext === 'pdb') ? 'pdb' : 'cif';

          // Create/replace viewer.
          viewerEl.textContent = '';
          const viewer = D.createViewer(viewerEl);
          try {{
            // Dark background so it doesn't look like an opened image page.
            viewer.setBackgroundColor(0x0b1220, 1);
          }} catch (e) {{
            // ignore
          }}
          viewer.addModel(text, format);
          viewer.setStyle({{}}, {{ cartoon: {{ color: 'spectrum' }} }});
          viewer.zoomTo();
          viewer.render();
          setViewerMessage('Rendered: ' + filename);
        }} catch (e) {{
          setViewerMessage('Viewer error: ' + e);
        }}
      }}

      function pickPreferredStructure(files) {{
        if (!files) return null;
        if (files.includes('predicted.pdb')) return 'predicted.pdb';
        if (files.includes('predicted.cif')) return 'predicted.cif';
        // fallback: any pdb/cif
        for (const f of files) {{
          const lower = String(f).toLowerCase();
          if (lower.endsWith('.pdb') || lower.endsWith('.cif') || lower.endsWith('.mmcif')) return f;
        }}
        return null;
      }}

      function populateSamples() {{
        for (let i = 0; i < samples.length; i++) {{
          const opt = document.createElement('option');
          opt.value = String(i);
          opt.textContent = samples[i].name;
          sampleSelect.appendChild(opt);
        }}
      }}

      function loadSample() {{
        const idx = parseInt(sampleSelect.value, 10);
        const s = samples[idx] || samples[0];
        inputsJson.value = JSON.stringify(s.inputs, null, 2);
        overrides.value = (s.overrides || []).join('\\n');
        clearFiles();
        setStatus('Loaded sample: ' + s.name);
      }}

      async function submitJob() {{
        clearFiles();
        setViewerMessage('');
        setLogs('(no logs yet)');

        let inputs;
        try {{
          inputs = JSON.parse(inputsJson.value);
        }} catch (e) {{
          setStatus('Invalid JSON: ' + e);
          return;
        }}

        const ovs = overrides.value
          .split(/\\r?\\n/)
          .map(s => s.trim())
          .filter(s => s.length > 0);

        setStatus('Submitting job...');
        const resp = await fetch('/fold', {{
          method: 'POST',
          headers: {{ 'content-type': 'application/json' }},
          body: JSON.stringify({{ inputs: inputs, overrides: ovs }})
        }});
        if (!resp.ok) {{
          const t = await resp.text();
          setStatus('Submit failed: HTTP ' + resp.status + '\\n' + t);
          return;
        }}

        const data = await resp.json();
        const jobId = data.job_id;
        setStatus('Submitted job_id=' + jobId + '\\nPolling...');

        for (let i = 0; i < 600; i++) {{
          const r = await fetch(`/jobs/${{jobId}}`, {{ cache: 'no-store' }});
          if (!r.ok) {{
            setStatus('Polling failed: HTTP ' + r.status);
            return;
          }}
          const j = await r.json();
          setStatus(JSON.stringify(j, null, 2));

          // Live logs (best-effort)
          try {{
            const lr = await fetch(`/jobs/${{jobId}}/logs?tail_bytes=20000`, {{ cache: 'no-store' }});
            if (lr.ok) {{
              const lj = await lr.json();
              const combined =
                '--- stdout (tail) ---\\n' + (lj.stdout || '') +
                '\\n\\n--- stderr (tail) ---\\n' + (lj.stderr || '');
              setLogs(combined);
            }}
          }} catch (e) {{
            // ignore
          }}

          if (j.status === 'succeeded' || j.status === 'failed') {{
            renderFiles(jobId, j.files);
            if (j.status === 'succeeded') {{
              const structure = pickPreferredStructure(j.files || []);
              if (structure) {{
                setViewerMessage('Ready: ' + structure + ' (click Render in Outputs)');
              }} else {{
                setViewerMessage('No structure file found in outputs.');
              }}
            }}
            return;
          }}
          await new Promise(res => setTimeout(res, 2000));
        }}

        setStatus('Timed out waiting for job completion.');
      }}

      populateSamples();
      loadSampleBtn.addEventListener('click', loadSample);
      submitBtn.addEventListener('click', submitJob);
      loadSample();
    </script>
  </body>
</html>
"""

    return HTMLResponse(
        content=html,
        headers={
            "cache-control": "no-store, max-age=0",
            "pragma": "no-cache",
            "expires": "0",
        },
    )


async def _proxy(request: Request, path: str) -> Response:
    base = _require_backend()
    url = f"{base}{path}"

    headers = dict(request.headers)
    headers.pop("host", None)

    body = await request.body()

    timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.request(
            request.method,
            url,
            params=dict(request.query_params),
            headers=headers,
            content=body,
        )

    content_type = resp.headers.get("content-type")
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type,
        headers={"cache-control": "no-store"},
    )


@app.api_route("/health", methods=["GET"])
async def proxy_health(request: Request) -> Response:
    return await _proxy(request, "/health")


@app.api_route("/fold", methods=["POST"])
async def proxy_fold(request: Request) -> Response:
    return await _proxy(request, "/fold")


@app.api_route("/jobs/{job_id}", methods=["GET"])
async def proxy_job(job_id: str, request: Request) -> Response:
    return await _proxy(request, f"/jobs/{job_id}")


@app.api_route("/jobs/{job_id}/logs", methods=["GET"])
async def proxy_job_logs(job_id: str, request: Request) -> Response:
  return await _proxy(request, f"/jobs/{job_id}/logs")


@app.api_route("/jobs/{job_id}/files/{filename}", methods=["GET"])
async def proxy_job_file(job_id: str, filename: str) -> StreamingResponse:
    base = _require_backend()
    url = f"{base}/jobs/{job_id}/files/{filename}"

    timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    try:
        upstream = await client.get(url)
        if upstream.status_code >= 400:
            content = await upstream.aread()
            await client.aclose()
            return StreamingResponse(
                iter([content]),
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "text/plain"),
            )

        # Preserve attachment behavior (e.g., for .gif) by forwarding Content-Disposition.
        extra_headers: Dict[str, str] = {"cache-control": "no-store"}
        cd = upstream.headers.get("content-disposition")
        if cd:
          extra_headers["content-disposition"] = cd

        async def gen():
            async for chunk in upstream.aiter_bytes():
                yield chunk
            await client.aclose()

        return StreamingResponse(
            gen(),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/octet-stream"),
            headers=extra_headers,
        )

    except Exception:
        await client.aclose()
        raise
