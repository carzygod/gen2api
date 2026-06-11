from __future__ import annotations

import os
from pathlib import Path


class Settings:
    app_name = "media2api"
    env = os.getenv("MEDIA2API_ENV", "development")
    database_url = os.getenv("DATABASE_URL", "sqlite:///./var/media2api.db")
    asset_store = os.getenv("MEDIA2API_ASSET_STORE", "local").lower()
    asset_dir = Path(os.getenv("ASSET_DIR", "./var/assets"))
    s3_endpoint = os.getenv("MEDIA2API_S3_ENDPOINT", "").rstrip("/")
    s3_bucket = os.getenv("MEDIA2API_S3_BUCKET", "")
    s3_region = os.getenv("MEDIA2API_S3_REGION", "us-east-1")
    s3_access_key = os.getenv("MEDIA2API_S3_ACCESS_KEY", "")
    s3_secret_key = os.getenv("MEDIA2API_S3_SECRET_KEY", "")
    s3_prefix = os.getenv("MEDIA2API_S3_PREFIX", "").strip("/")
    public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
    bootstrap_api_key = os.getenv("MEDIA2API_BOOTSTRAP_KEY", "dev-admin-key")
    admin_token = os.getenv("MEDIA2API_ADMIN_TOKEN", "dev-admin-token")
    admin_password = os.getenv("MEDIA2API_ADMIN_PASSWORD", "")
    redis_url = os.getenv("REDIS_URL", "")
    inline_async = os.getenv("MEDIA2API_INLINE_ASYNC", "true").lower() == "true"
    default_user_email = os.getenv("MEDIA2API_DEFAULT_USER", "admin@media2api.local")
    seed_defaults_enabled = os.getenv("MEDIA2API_SEED_DEFAULTS", "true").lower() == "true"
    image_sync_wait = os.getenv("MEDIA2API_IMAGE_SYNC_WAIT", "true").lower() == "true"
    asset_url_ttl_seconds = int(os.getenv("MEDIA2API_ASSET_URL_TTL_SECONDS", "86400"))
    asset_max_bytes = int(os.getenv("MEDIA2API_ASSET_MAX_BYTES", str(200 * 1024 * 1024)))
    asset_max_image_width = int(os.getenv("MEDIA2API_ASSET_MAX_IMAGE_WIDTH", "8192"))
    asset_max_image_height = int(os.getenv("MEDIA2API_ASSET_MAX_IMAGE_HEIGHT", "8192"))
    asset_max_image_pixels = int(os.getenv("MEDIA2API_ASSET_MAX_IMAGE_PIXELS", str(8192 * 8192)))
    asset_max_video_width = int(os.getenv("MEDIA2API_ASSET_MAX_VIDEO_WIDTH", "7680"))
    asset_max_video_height = int(os.getenv("MEDIA2API_ASSET_MAX_VIDEO_HEIGHT", "4320"))
    asset_max_video_duration_seconds = int(os.getenv("MEDIA2API_ASSET_MAX_VIDEO_DURATION_SECONDS", "3600"))
    asset_remote_url_max_length = int(os.getenv("MEDIA2API_ASSET_REMOTE_URL_MAX_LENGTH", "2048"))
    asset_remote_url_max_redirects = int(os.getenv("MEDIA2API_ASSET_REMOTE_URL_MAX_REDIRECTS", "3"))
    asset_remote_url_allow_private = os.getenv("MEDIA2API_ASSET_REMOTE_URL_ALLOW_PRIVATE", "false").lower() == "true"
    asset_remote_url_allowed_hosts = {
        host.strip().rstrip(".").lower()
        for host in os.getenv("MEDIA2API_ASSET_REMOTE_URL_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    proxy_kernel_dir = Path(os.getenv("MEDIA2API_PROXY_KERNEL_DIR", "./var/proxy-kernels"))
    asset_signing_secret = os.getenv("MEDIA2API_ASSET_SIGNING_SECRET") or bootstrap_api_key
    secret_encryption_key = os.getenv("MEDIA2API_SECRET_ENCRYPTION_KEY") or asset_signing_secret
    webhook_max_attempts = int(os.getenv("MEDIA2API_WEBHOOK_MAX_ATTEMPTS", "3"))
    webhook_retry_delay_seconds = float(os.getenv("MEDIA2API_WEBHOOK_RETRY_DELAY_SECONDS", "0.25"))
    webhook_url_max_length = int(os.getenv("MEDIA2API_WEBHOOK_URL_MAX_LENGTH", "2048"))
    webhook_url_allow_private = os.getenv("MEDIA2API_WEBHOOK_URL_ALLOW_PRIVATE", "false").lower() == "true"
    webhook_url_allowed_hosts = {
        host.strip().rstrip(".").lower()
        for host in os.getenv("MEDIA2API_WEBHOOK_URL_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    worker_concurrency = int(os.getenv("MEDIA2API_WORKER_CONCURRENCY", "1"))
    worker_poll_interval_seconds = float(os.getenv("MEDIA2API_WORKER_POLL_INTERVAL_SECONDS", "1"))
    worker_stalled_job_seconds = int(os.getenv("MEDIA2API_WORKER_STALLED_JOB_SECONDS", "120"))

    def ensure_dirs(self) -> None:
        if self.asset_store == "local":
            self.asset_dir.mkdir(parents=True, exist_ok=True)
        self.proxy_kernel_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url.replace("sqlite:///", "", 1)
            if db_path and db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
