from __future__ import annotations

import argparse
import os
import posixpath
import sys
import tarfile
import time
from pathlib import Path
from urllib.parse import quote

import paramiko


ROOT = Path(__file__).resolve().parents[1]


def make_tarball() -> Path:
    tmp_dir = ROOT / "var" / "deploy"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"media2api-bare-{int(time.time())}.tar.gz"
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


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def systemd_env_line(name: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'Environment="{name}={escaped}"\n'


def deploy(host: str, user: str, password: str, port: int, remote_dir: str, public_port: int, api_key: str, seed_defaults: bool, github_token: str = "") -> None:
    tarball = make_tarball()
    client = connect(host, user, password, port)
    app_dir = posixpath.join(remote_dir, "media2api")
    data_dir = posixpath.join(remote_dir, "var")
    db_url = "postgresql+psycopg://media2api:media2api@127.0.0.1:5432/media2api"
    redis_url = "__MEDIA2API_REDIS_URL__"
    seed_defaults_value = "true" if seed_defaults else "false"
    github_token_env = systemd_env_line("MEDIA2API_GITHUB_TOKEN", github_token)
    service = f"""[Unit]
Description=media2api unified media gateway
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
WorkingDirectory={app_dir}
Environment=DATABASE_URL={db_url}
Environment=ASSET_DIR={data_dir}/assets
Environment=PUBLIC_BASE_URL=http://{host}:{public_port}
Environment=MEDIA2API_BOOTSTRAP_KEY={api_key}
Environment=MEDIA2API_ADMIN_PASSWORD={api_key}
Environment=MEDIA2API_ADMIN_TOKEN=admin-token-{int(time.time())}
Environment=REDIS_URL={redis_url}
Environment=MEDIA2API_INLINE_ASYNC=false
Environment=MEDIA2API_WORKER_CONCURRENCY=2
Environment=MEDIA2API_SEED_DEFAULTS={seed_defaults_value}
Environment=MEDIA2API_PROXY_KERNEL_BOOTSTRAP_ROUTES=true
Environment=MEDIA2API_PROXY_KERNEL_DIR={data_dir}/proxy-kernels
Environment=MEDIA2API_SOURCE_REPO_DIR={remote_dir}/source-repo
{github_token_env.rstrip()}
ExecStart={app_dir}/.venv/bin/python -m uvicorn media2api.main:app --host 0.0.0.0 --port {public_port}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
    worker_service = f"""[Unit]
Description=media2api database queue worker
After=network.target postgresql.service redis-server.service media2api.service

[Service]
Type=simple
WorkingDirectory={app_dir}
Environment=DATABASE_URL={db_url}
Environment=ASSET_DIR={data_dir}/assets
Environment=PUBLIC_BASE_URL=http://{host}:{public_port}
Environment=MEDIA2API_BOOTSTRAP_KEY={api_key}
Environment=MEDIA2API_ADMIN_PASSWORD={api_key}
Environment=MEDIA2API_ADMIN_TOKEN=admin-token-{int(time.time())}
Environment=REDIS_URL={redis_url}
Environment=MEDIA2API_INLINE_ASYNC=false
Environment=MEDIA2API_WORKER_CONCURRENCY=2
Environment=MEDIA2API_SEED_DEFAULTS={seed_defaults_value}
Environment=MEDIA2API_PROXY_KERNEL_BOOTSTRAP_ROUTES=true
Environment=MEDIA2API_PROXY_KERNEL_DIR={data_dir}/proxy-kernels
Environment=MEDIA2API_SOURCE_REPO_DIR={remote_dir}/source-repo
{github_token_env.rstrip()}
ExecStart={app_dir}/.venv/bin/python -m media2api.worker
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
    try:
        print(run(client, "uname -a; python3 --version; psql --version || true; redis-server --version || true; systemctl --version | head -1", check=False))
        run(client, f"mkdir -p {shell_quote(remote_dir)} {shell_quote(data_dir)}")
        remote_tar = posixpath.join(remote_dir, "media2api-bare.tar.gz")
        upload(client, tarball, remote_tar)
        run(client, f"cd {shell_quote(remote_dir)} && rm -rf media2api && tar -xzf media2api-bare.tar.gz")

        run(
            client,
            r"""set -e
if ! python3 -m venv --help >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3-venv python3-pip
fi
if ! command -v psql >/dev/null 2>&1; then
  apt-get update
  apt-get install -y postgresql postgresql-contrib
fi
if ! command -v redis-server >/dev/null 2>&1; then
  apt-get update
  apt-get install -y redis-server
fi
systemctl enable --now postgresql || true
systemctl enable --now redis-server || true
""",
        )

        run(
            client,
            r"""set -e
runuser -u postgres -- psql -tc "SELECT 1 FROM pg_roles WHERE rolname='media2api'" | grep -q 1 || runuser -u postgres -- psql -c "CREATE USER media2api WITH PASSWORD 'media2api';"
runuser -u postgres -- psql -tc "SELECT 1 FROM pg_database WHERE datname='media2api'" | grep -q 1 || runuser -u postgres -- createdb -O media2api media2api
runuser -u postgres -- psql -d media2api -c "GRANT ALL PRIVILEGES ON DATABASE media2api TO media2api;"
""",
        )

        redis_password = run(
            client,
            r"""awk '/^[[:space:]]*requirepass[[:space:]]+/ {print $2; exit}' /etc/redis/redis.conf /etc/redis/redis-server.conf 2>/dev/null || true""",
            check=False,
        ).strip()
        redis_runtime_url = (
            f"redis://:{quote(redis_password, safe='')}@127.0.0.1:6379/0"
            if redis_password
            else "redis://127.0.0.1:6379/0"
        )
        redis_ping = run(client, f"redis-cli -u {shell_quote(redis_runtime_url)} ping 2>/dev/null || true", check=False)
        if "PONG" not in redis_ping:
            raise RuntimeError(f"redis health check failed: {redis_ping.strip() or 'no response'}")
        service = service.replace(redis_url, redis_runtime_url)
        worker_service = worker_service.replace(redis_url, redis_runtime_url)

        run(client, f"cd {shell_quote(app_dir)} && python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -r requirements.txt", check=True)
        service_path = "/etc/systemd/system/media2api.service"
        worker_service_path = "/etc/systemd/system/media2api-worker.service"
        run(
            client,
            f"cat > {service_path} <<'EOF'\n{service}\nEOF\n"
            f"cat > {worker_service_path} <<'EOF'\n{worker_service}\nEOF\n"
            "systemctl daemon-reload\n"
            "systemctl enable media2api media2api-worker\n"
            "systemctl restart media2api\n"
            "systemctl restart media2api-worker"
        )

        health_url = f"http://127.0.0.1:{public_port}/health"
        for _ in range(60):
            result = run(client, f"curl -fsS {health_url} || true", check=False)
            if '"status":"ok"' in result:
                print(result)
                break
            time.sleep(2)
        else:
            status = run(client, "systemctl status media2api --no-pager || true", check=False)
            logs = run(client, "journalctl -u media2api -n 200 --no-pager || true", check=False)
            raise RuntimeError(f"health check failed\n{status}\n{logs}")

        print(f"DEPLOYED_URL=http://{host}:{public_port}")
        print(f"ADMIN_URL=http://{host}:{public_port}/admin")
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
    parser.add_argument("--seed-defaults", action=argparse.BooleanOptionalAction, default=os.getenv("MEDIA2API_SEED_DEFAULTS", "true").lower() == "true")
    parser.add_argument("--github-token", default=os.getenv("MEDIA2API_GITHUB_TOKEN", os.getenv("GITHUB_TOKEN", "")))
    args = parser.parse_args()
    if not args.password:
        parser.error("--password or DEPLOY_PASSWORD is required")
    deploy(args.host, args.user, args.password, args.port, args.remote_dir, args.public_port, args.api_key, args.seed_defaults, args.github_token)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"DEPLOY_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
