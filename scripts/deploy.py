from __future__ import annotations

import argparse
import os
import posixpath
import stat
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]


def make_tarball() -> Path:
    tmp = Path(tempfile.gettempdir()) / f"media2api-{int(time.time())}.tar.gz"
    exclude_names = {".venv", "__pycache__", ".pytest_cache", "var"}
    with tarfile.open(tmp, "w:gz") as tar:
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if any(part in exclude_names for part in rel.parts):
                continue
            tar.add(path, arcname=f"media2api/{rel.as_posix()}")
    return tmp


def connect(host: str, user: str, password: str, port: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=user, password=password, look_for_keys=False, allow_agent=False, timeout=20)
    return client


def run(client: paramiko.SSHClient, command: str, check: bool = True) -> str:
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if check and code != 0:
        raise RuntimeError(f"remote command failed ({code}): {command}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    return out + err


def upload(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    sftp = client.open_sftp()
    try:
        sftp.put(str(local), remote)
    finally:
        sftp.close()


def deploy(host: str, user: str, password: str, port: int, remote_dir: str, public_port: int, api_key: str) -> None:
    tarball = make_tarball()
    client = connect(host, user, password, port)
    try:
        print(run(client, "uname -a; command -v docker || true; docker --version || true; docker compose version || true", check=False))
        run(client, f"mkdir -p {remote_dir}")
        remote_tar = posixpath.join(remote_dir, "media2api.tar.gz")
        upload(client, tarball, remote_tar)
        run(
            client,
            f"cd {remote_dir} && rm -rf media2api && tar -xzf media2api.tar.gz && cd media2api && "
            f"cat > .env <<'EOF'\n"
            f"MEDIA2API_PORT={public_port}\n"
            f"PUBLIC_BASE_URL=http://{host}:{public_port}\n"
            f"MEDIA2API_BOOTSTRAP_KEY={api_key}\n"
            f"MEDIA2API_ADMIN_TOKEN=admin-token-{int(time.time())}\n"
            f"DATABASE_URL=postgresql+psycopg://media2api:media2api@postgres:5432/media2api\n"
            f"ASSET_DIR=/app/var/assets\n"
            f"REDIS_URL=redis://redis:6379/0\n"
            f"EOF"
        )
        compose = "docker compose"
        probe = run(client, "docker compose version >/dev/null 2>&1 || echo legacy", check=False).strip()
        if "legacy" in probe:
            compose = "docker-compose"
        run(client, f"cd {remote_dir}/media2api && {compose} up -d --build")
        health_url = f"http://127.0.0.1:{public_port}/health"
        for _ in range(60):
            result = run(client, f"curl -fsS {health_url} || true", check=False)
            if '"status":"ok"' in result:
                print(result)
                break
            time.sleep(2)
        else:
            logs = run(client, f"cd {remote_dir}/media2api && {compose} logs --tail=200", check=False)
            raise RuntimeError(f"health check failed\n{logs}")
        print(f"DEPLOYED_URL=http://{host}:{public_port}")
        print(f"API_KEY={api_key}")
    finally:
        client.close()
        tarball.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("DEPLOY_HOST", "192.168.31.26"))
    parser.add_argument("--user", default=os.getenv("DEPLOY_USER", "root"))
    parser.add_argument("--password", default=os.getenv("DEPLOY_PASSWORD", ""))
    parser.add_argument("--port", type=int, default=int(os.getenv("DEPLOY_SSH_PORT", "22")))
    parser.add_argument("--remote-dir", default=os.getenv("DEPLOY_REMOTE_DIR", "/opt/media2api"))
    parser.add_argument("--public-port", type=int, default=int(os.getenv("MEDIA2API_PORT", "8080")))
    parser.add_argument("--api-key", default=os.getenv("MEDIA2API_BOOTSTRAP_KEY", "dev-admin-key"))
    args = parser.parse_args()
    if not args.password:
        parser.error("--password or DEPLOY_PASSWORD is required")
    deploy(args.host, args.user, args.password, args.port, args.remote_dir, args.public_port, args.api_key)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"DEPLOY_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
