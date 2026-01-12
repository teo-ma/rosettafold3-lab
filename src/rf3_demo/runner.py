from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def _tail_file_bytes(path: Path, max_bytes: int) -> str:
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


@dataclass(frozen=True)
class RunResult:
    out_dir: Path
    stdout: str
    stderr: str


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value is not None and value.strip() else default


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def run_rf3_fold(
    *,
    inputs_path: Path,
    out_dir: Path,
    overrides: Iterable[str] = (),
    ckpt_path: Path | None = None,
    timeout_seconds: int | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> RunResult:
    """Run `rf3 fold` using Hydra-style overrides.

    Notes:
    - Hydra uses `key=value` (not `--key value`).
    - `inputs` is required and must point to a JSON/CIF/PDB file.
    """

    ensure_dir(out_dir)

    resolved_ckpt = ckpt_path or Path(_env("RF3_CKPT_PATH", "/models/rf3.ckpt"))

    cmd: list[str] = [
        "rf3",
        "fold",
        f"inputs={str(inputs_path)}",
        f"out_dir={str(out_dir)}",
        "dump_predictions=true",
        f"ckpt_path={str(resolved_ckpt)}",
    ]

    for ov in overrides:
        ov = ov.strip()
        if not ov:
            continue
        cmd.append(ov)

    # If stdout/stderr paths are provided, stream output into those files to enable
    # real-time progress viewing while the job is running.
    if stdout_path is not None or stderr_path is not None:
        stdout_path = stdout_path or (out_dir / "stdout.txt")
        stderr_path = stderr_path or (out_dir / "stderr.txt")
        ensure_dir(stdout_path.parent)
        ensure_dir(stderr_path.parent)

        with stdout_path.open("w", encoding="utf-8") as out_f, stderr_path.open(
            "w", encoding="utf-8"
        ) as err_f:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            assert proc.stdout is not None
            assert proc.stderr is not None

            def _drain(src, dst):
                for line in src:
                    dst.write(line)
                    dst.flush()

            t_out = threading.Thread(
                target=_drain, args=(proc.stdout, out_f), daemon=True
            )
            t_err = threading.Thread(
                target=_drain, args=(proc.stderr, err_f), daemon=True
            )
            t_out.start()
            t_err.start()

            try:
                proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise
            finally:
                try:
                    proc.stdout.close()
                except Exception:
                    pass
                try:
                    proc.stderr.close()
                except Exception:
                    pass

            t_out.join(timeout=5)
            t_err.join(timeout=5)

            if proc.returncode != 0:
                raise RuntimeError(
                    "rf3 fold failed"
                    f"\nexit_code={proc.returncode}"
                    f"\nstdout_tail=\n{_tail_file_bytes(stdout_path, 20000)}"
                    f"\nstderr_tail=\n{_tail_file_bytes(stderr_path, 20000)}"
                )

        return RunResult(out_dir=out_dir, stdout="", stderr="")

    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            "rf3 fold failed"
            f"\nexit_code={proc.returncode}"
            f"\nstdout=\n{proc.stdout}"
            f"\nstderr=\n{proc.stderr}"
        )

    return RunResult(out_dir=out_dir, stdout=proc.stdout, stderr=proc.stderr)
