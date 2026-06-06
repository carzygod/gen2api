from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError


TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAJklEQVR4nGM8ceIEA27AhEduBEsD"
    "Rg0YNWDUMBqGgYGBgQEA1LID4Zyv2nQAAAAASUVORK5CYII="
)


class Media2APIError(RuntimeError):
    def __init__(self, status_code: int, payload: dict[str, Any] | str):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"media2api request failed: {status_code} {payload}")


class Media2APIClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        req = urlrequest.Request(f"{self.base_url}{path}", data=body, headers=request_headers, method=method)
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload_data: dict[str, Any] | str = json.loads(raw)
            except Exception:
                payload_data = raw
            raise Media2APIError(exc.code, payload_data) from exc

    def download(self, url: str, output_path: Path) -> Path:
        with urlrequest.urlopen(url, timeout=self.timeout_seconds) as resp:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(resp.read())
        return output_path

    def list_models(self) -> dict[str, Any]:
        return self.request("GET", "/v1/models")

    def create_image(self, prompt: str, model: str = "t2i-fast", response_format: str = "url") -> dict[str, Any]:
        return self.request(
            "POST",
            "/v1/images/generations",
            {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "response_format": response_format,
            },
        )

    def create_asset_from_base64(
        self,
        b64_json: str,
        filename: str,
        kind: str = "image",
        purpose: str = "reference",
        mime_type: str = "image/png",
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            "/v1/assets",
            {
                "b64_json": b64_json,
                "filename": filename,
                "kind": kind,
                "purpose": purpose,
                "mime_type": mime_type,
            },
        )

    def create_video(self, prompt: str, model: str = "i2v-fast", image_asset_id: str | None = None, duration: int = 3) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": "16:9",
        }
        if image_asset_id:
            payload["image"] = image_asset_id
        return self.request("POST", "/v1/videos/generations", payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/media-jobs/{job_id}")

    def get_video_generation(self, job_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/videos/generations/{job_id}")

    def wait_for_job(self, job_id: str, timeout_seconds: float = 180, poll_interval_seconds: float = 1.0) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            job = self.get_job(job_id)
            if job["status"] in {"completed", "failed", "cancelled", "expired"}:
                return job
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"job {job_id} did not finish within {timeout_seconds} seconds")

    def analytics(self, group_by: str = "provider_id,logical_model") -> dict[str, Any]:
        return self.request("GET", f"/v1/admin/analytics?group_by={group_by}")


def run_demo(client: Media2APIClient, download_dir: Path, timeout_seconds: float) -> dict[str, Any]:
    models = client.list_models()
    if not models.get("data"):
        raise RuntimeError("model list is empty")

    image = client.create_image("SDK example image")
    image_item = image["data"][0]
    image_asset_id = image_item["asset_id"]

    uploaded = client.create_asset_from_base64(TINY_PNG_BASE64, "reference.png")
    video = client.create_video("SDK example image to video", image_asset_id=uploaded["id"])
    video_job = client.wait_for_job(video["id"], timeout_seconds=timeout_seconds)
    if video_job["status"] != "completed":
        raise RuntimeError(f"video job did not complete: {video_job}")
    if not video_job.get("outputs"):
        raise RuntimeError(f"video job has no outputs: {video_job}")

    video_asset = video_job["outputs"][0]
    if video_asset["kind"] != "video":
        raise RuntimeError(f"expected video output, got {video_asset}")
    downloaded_video = client.download(video_asset["url"], download_dir / f"{video_asset['id']}.mp4")

    thumbnail_path = None
    if video_asset.get("thumbnail_url"):
        thumbnail_path = client.download(video_asset["thumbnail_url"], download_dir / f"{video_asset['thumbnail_asset_id']}.png")

    analytics = client.analytics()
    return {
        "models": len(models["data"]),
        "image_job_id": image["job_id"],
        "image_asset_id": image_asset_id,
        "uploaded_asset_id": uploaded["id"],
        "video_job_id": video_job["id"],
        "video_asset_id": video_asset["id"],
        "downloaded_video": str(downloaded_video),
        "downloaded_thumbnail": str(thumbnail_path) if thumbnail_path else "",
        "analytics_rows": len(analytics.get("data", [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="media2api minimal Python SDK example")
    parser.add_argument("--base-url", default=os.getenv("MEDIA2API_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--api-key", default=os.getenv("MEDIA2API_API_KEY", "dev-admin-key"))
    parser.add_argument("--download-dir", default=os.getenv("MEDIA2API_EXAMPLE_DOWNLOAD_DIR", "var/example-downloads"))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("MEDIA2API_EXAMPLE_TIMEOUT", "180")))
    args = parser.parse_args()

    client = Media2APIClient(args.base_url, args.api_key)
    result = run_demo(client, Path(args.download_dir), args.timeout)
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
