from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from rf3_demo.runner import run_rf3_fold


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value is not None and value.strip() else default


@dataclass
class Job:
    id: str
    status: str  # queued|running|succeeded|failed
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    out_dir: Optional[Path] = None
    inputs_path: Optional[Path] = None
    overrides: List[str] = None  # type: ignore[assignment]


class FoldRequest(BaseModel):
    inputs: Any = Field(
        ..., description="RF3 input JSON object or list (will be written to a temp file)."
    )
    overrides: List[str] = Field(
        default_factory=list,
        description="Optional Hydra overrides, e.g. ['num_steps=50','diffusion_batch_size=1'].",
    )


app = FastAPI(title="RosettaFold3 inference demo", version="0.1.0")

_jobs: Dict[str, Job] = {}
_jobs_lock = threading.Lock()
_worker_lock = threading.Lock()  # serialize GPU work


def _ckpt_path() -> Path:
    return Path(_env("RF3_CKPT_PATH", "/models/rf3.ckpt"))


def _ckpt_ready() -> bool:
    try:
        p = _ckpt_path()
        return p.exists() and p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


def _base_work_dir() -> Path:
    return Path(_env("RF3_WORKDIR", "/tmp/rf3-demo"))


def _job_dir(job_id: str) -> Path:
    return _base_work_dir() / "jobs" / job_id


def _write_inputs(job_id: str, payload: Any) -> Path:
    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    inputs_path = job_dir / "inputs.json"
    inputs_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return inputs_path


def _tail_text_file(path: Path, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes), 0)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _run_job(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = time.time()

    try:
        # Ensure only one GPU job at a time.
        with _worker_lock:
            assert job.inputs_path is not None
            out_dir = _job_dir(job_id) / "out"
            out_dir.mkdir(parents=True, exist_ok=True)

            # Create log files early so the UI can tail them while running.
            stdout_path = out_dir / "stdout.txt"
            stderr_path = out_dir / "stderr.txt"
            try:
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
            except OSError:
                pass

            with _jobs_lock:
                j2 = _jobs.get(job_id)
                if j2:
                    j2.out_dir = out_dir

            result = run_rf3_fold(
                inputs_path=job.inputs_path,
                out_dir=out_dir,
                overrides=job.overrides or [],
                timeout_seconds=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )

        # Persist logs for easy download/inspection from the UI.
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            if result.stdout:
                (out_dir / "stdout.txt").write_text(result.stdout or "", encoding="utf-8")
            if result.stderr:
                (out_dir / "stderr.txt").write_text(result.stderr or "", encoding="utf-8")
        except OSError:
            # Best-effort; job still considered successful if rf3 fold succeeded.
            pass

        # Surface a top-level structure file so the UI can visualize it.
        try:
            # Prefer PDB, else CIF/mmCIF.
            candidates = []
            for p in out_dir.rglob("*"):
                if not p.is_file():
                    continue
                suf = p.suffix.lower()
                if suf in {".pdb", ".cif", ".mmcif"}:
                    candidates.append(p)

            def _rank(path: Path) -> int:
                suf = path.suffix.lower()
                if suf == ".pdb":
                    return 0
                if suf in {".cif", ".mmcif"}:
                    return 1
                return 9

            candidates.sort(key=_rank)

            if candidates:
                chosen = candidates[0]
                target_suffix = chosen.suffix.lower()
                if target_suffix == ".mmcif":
                    target_suffix = ".cif"
                target = out_dir / f"predicted{target_suffix}"
                if not target.exists():
                    shutil.copyfile(chosen, target)
        except OSError:
            pass

        with _jobs_lock:
            job = _jobs[job_id]
            job.status = "succeeded"
            job.finished_at = time.time()
            job.out_dir = out_dir

    except Exception as e:  # noqa: BLE001
        with _jobs_lock:
            job = _jobs[job_id]
            job.status = "failed"
            job.finished_at = time.time()
            job.error = str(e)


@app.get("/health")
def health() -> Dict[str, str]:
    return {
        "status": "ok",
        "checkpoint_ready": "true" if _ckpt_ready() else "false",
    }


@app.get("/", response_class=HTMLResponse)
def demo_page() -> str:
        # Keep this page self-contained (no external assets) so it works in locked-down environments.
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

        return f"""<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>RosettaFold3 Demo</title>
    </head>
    <body>
        <h1>RosettaFold3 Demo</h1>
        <p>
            This page submits jobs to <code>/fold</code> and polls <code>/jobs/&lt;job_id&gt;</code>.
            Health: <a href=\"/health\" target=\"_blank\" rel=\"noreferrer\">/health</a>
        </p>

        <h2>Sample inputs</h2>
        <label>
            Choose a sample:
            <select id=\"sampleSelect\"></select>
        </label>
        <button id=\"loadSampleBtn\" type=\"button\">Load sample</button>

        <h2>Inputs JSON</h2>
        <p>Edit the JSON if needed. The service expects an object like <code>{{name, components:[{{seq, chain_id}}...]}}</code>.</p>
        <textarea id=\"inputsJson\" rows=\"18\" cols=\"100\">{default_payload}</textarea>

        <h2>Hydra overrides (optional)</h2>
        <p>One per line, e.g. <code>num_steps=50</code>.</p>
        <textarea id=\"overrides\" rows=\"5\" cols=\"100\"></textarea>

        <p>
            <button id=\"submitBtn\" type=\"button\">Run fold</button>
        </p>

        <h2>Job status</h2>
        <pre id=\"status\">Idle</pre>

        <h2>Outputs</h2>
        <ul id=\"files\"></ul>

        <script>
            const samples = {samples_json};
            const sampleSelect = document.getElementById('sampleSelect');
            const inputsJson = document.getElementById('inputsJson');
            const overrides = document.getElementById('overrides');
            const statusEl = document.getElementById('status');
            const filesEl = document.getElementById('files');
            const loadSampleBtn = document.getElementById('loadSampleBtn');
            const submitBtn = document.getElementById('submitBtn');

            function setStatus(text) {{
                statusEl.textContent = text;
            }}

            function clearFiles() {{
                while (filesEl.firstChild) filesEl.removeChild(filesEl.firstChild);
            }}

            function renderFiles(jobId, files) {{
                clearFiles();
                if (!files || files.length === 0) return;
                for (const filename of files) {{
                    const li = document.createElement('li');
                    const a = document.createElement('a');
                    a.href = `/jobs/${{jobId}}/files/${{encodeURIComponent(filename)}}`;
                    a.textContent = filename;
                    a.target = '_blank';
                    a.rel = 'noreferrer';
                    li.appendChild(a);
                    filesEl.appendChild(li);
                }}
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

                let inputs;
                try {{
                    inputs = JSON.parse(inputsJson.value);
                }} catch (e) {{
                    setStatus('Invalid JSON: ' + e);
                    return;
                }}

                const ovs = overrides.value.split(/\\r?\\n/).map(s => s.trim()).filter(s => s.length > 0);

                setStatus('Submitting job...');
                const resp = await fetch('/fold', {{
                    method: 'POST',
                    headers: {{'content-type': 'application/json'}},
                    body: JSON.stringify({{inputs: inputs, overrides: ovs}})
                }});
                if (!resp.ok) {{
                    const t = await resp.text();
                    setStatus('Submit failed: HTTP ' + resp.status + '\\n' + t);
                    return;
                }}
                const data = await resp.json();
                const jobId = data.job_id;
                setStatus('Submitted job_id=' + jobId + '\\nPolling...');

                // Poll job status until completion.
                for (let i = 0; i < 600; i++) {{
                    const r = await fetch(`/jobs/${{jobId}}`, {{cache: 'no-store'}});
                    if (!r.ok) {{
                        setStatus('Polling failed: HTTP ' + r.status);
                        return;
                    }}
                    const j = await r.json();
                    setStatus(JSON.stringify(j, null, 2));
                    if (j.status === 'succeeded' || j.status === 'failed') {{
                        renderFiles(jobId, j.files);
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


@app.post("/fold")
def fold(req: FoldRequest) -> Dict[str, str]:
    if not _ckpt_ready():
        raise HTTPException(
            status_code=503,
            detail="Model checkpoint is not ready yet. Please retry in a few minutes.",
        )
    job_id = str(uuid.uuid4())
    inputs_path = _write_inputs(job_id, req.inputs)

    job = Job(
        id=job_id,
        status="queued",
        created_at=time.time(),
        inputs_path=inputs_path,
        overrides=req.overrides,
    )

    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    thread.start()

    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> Dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")

        result: Dict[str, Any] = {
            "id": job.id,
            "status": job.status,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "error": job.error,
        }

        if job.out_dir and job.out_dir.exists():
            # Return a file listing (flat). For running jobs this will include partial logs.
            if job.status in {"running", "succeeded", "failed"}:
                result["files"] = sorted(
                    [p.name for p in job.out_dir.iterdir() if p.is_file()]
                )

        return result


@app.get("/jobs/{job_id}/logs")
def job_logs(
    job_id: str,
    tail_bytes: int = 20000,
) -> Dict[str, Any]:
    """Return tail of stdout/stderr for a job.

    Intended for real-time progress viewing while a job is running.
    """

    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        out_dir = job.out_dir
        status = job.status

    if not out_dir or not out_dir.exists():
        return {"id": job_id, "status": status, "stdout": "", "stderr": ""}

    stdout_path = out_dir / "stdout.txt"
    stderr_path = out_dir / "stderr.txt"

    return {
        "id": job_id,
        "status": status,
        "stdout": _tail_text_file(stdout_path, tail_bytes),
        "stderr": _tail_text_file(stderr_path, tail_bytes),
    }


@app.get("/jobs/{job_id}/files/{filename}")
def job_file(job_id: str, filename: str):
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if not job.out_dir:
            raise HTTPException(status_code=400, detail="job output dir not available")

        path = job.out_dir / filename
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(
        path,
        filename=filename,
        headers={"cache-control": "no-store"},
    )
