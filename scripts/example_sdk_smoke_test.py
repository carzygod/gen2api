from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib import request as urlrequest


ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base_url: str, timeout_seconds: float = 30) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlrequest.urlopen(f"{base_url}/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"server did not become healthy: {last_error}")


def main() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["PUBLIC_BASE_URL"] = base_url
    env["MEDIA2API_INLINE_ASYNC"] = "true"
    env["MEDIA2API_WORKER_CONCURRENCY"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "media2api.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_health(base_url)
        output_dir = ROOT / "var" / "example-sdk-smoke"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "examples" / "media2api_sdk.py"),
                "--base-url",
                base_url,
                "--api-key",
                "dev-admin-key",
                "--download-dir",
                str(output_dir),
                "--timeout",
                "90",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise AssertionError(f"example failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok", payload
        video_path = Path(payload["downloaded_video"])
        assert video_path.exists() and video_path.stat().st_size > 0, payload
        assert payload["analytics_rows"] >= 1, payload
        print("example sdk smoke ok")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
