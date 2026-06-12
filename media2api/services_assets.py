from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlparse

import httpx
from PIL import Image
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .utils import dumps, loads, new_id


EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class AssetStorage:
    name = "base"

    def write_bytes(self, storage_key: str, data: bytes, mime_type: str) -> None:
        raise NotImplementedError

    def read_bytes(self, storage_key: str) -> bytes:
        raise NotImplementedError

    def delete(self, storage_key: str) -> None:
        raise NotImplementedError

    def path_for(self, storage_key: str) -> Path | None:
        return None


class LocalAssetStorage(AssetStorage):
    name = "local"

    def write_bytes(self, storage_key: str, data: bytes, mime_type: str) -> None:
        target = settings.asset_dir / storage_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read_bytes(self, storage_key: str) -> bytes:
        return (settings.asset_dir / storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        path = settings.asset_dir / storage_key
        if path.exists():
            path.unlink()

    def path_for(self, storage_key: str) -> Path | None:
        return settings.asset_dir / storage_key


class S3AssetStorage(AssetStorage):
    name = "s3"

    def __init__(self) -> None:
        if not settings.s3_endpoint or not settings.s3_bucket or not settings.s3_access_key or not settings.s3_secret_key:
            raise RuntimeError("S3 asset store requires endpoint, bucket, access key, and secret key.")
        self.endpoint = settings.s3_endpoint
        self.bucket = settings.s3_bucket
        self.region = settings.s3_region
        self.access_key = settings.s3_access_key
        self.secret_key = settings.s3_secret_key
        self.prefix = settings.s3_prefix

    def write_bytes(self, storage_key: str, data: bytes, mime_type: str) -> None:
        headers = self._signed_headers("PUT", storage_key, data, {"content-type": mime_type or "application/octet-stream"})
        response = httpx.put(self._url(storage_key), content=data, headers=headers, timeout=120)
        if response.status_code >= 400:
            raise RuntimeError(f"S3_PUT_FAILED:{response.status_code}:{response.text[:500]}")

    def read_bytes(self, storage_key: str) -> bytes:
        headers = self._signed_headers("GET", storage_key, b"", {})
        response = httpx.get(self._url(storage_key), headers=headers, timeout=120)
        if response.status_code >= 400:
            raise FileNotFoundError(f"S3_GET_FAILED:{response.status_code}")
        return response.content

    def delete(self, storage_key: str) -> None:
        headers = self._signed_headers("DELETE", storage_key, b"", {})
        response = httpx.delete(self._url(storage_key), headers=headers, timeout=60)
        if response.status_code >= 400 and response.status_code != 404:
            raise RuntimeError(f"S3_DELETE_FAILED:{response.status_code}:{response.text[:500]}")

    def _object_key(self, storage_key: str) -> str:
        return f"{self.prefix}/{storage_key}".strip("/") if self.prefix else storage_key

    def _url(self, storage_key: str) -> str:
        key = quote(self._object_key(storage_key), safe="/")
        return f"{self.endpoint}/{self.bucket}/{key}"

    def _signed_headers(self, method: str, storage_key: str, data: bytes, headers: dict[str, str]) -> dict[str, str]:
        parsed = urlparse(self._url(storage_key))
        amz_date = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        date_stamp = amz_date[:8]
        payload_hash = hashlib.sha256(data).hexdigest() if data else EMPTY_SHA256
        signed_headers = {
            "host": parsed.netloc,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            **{key.lower(): value for key, value in headers.items()},
        }
        sorted_header_keys = sorted(signed_headers)
        canonical_headers = "".join(f"{key}:{signed_headers[key]}\n" for key in sorted_header_keys)
        signed_header_names = ";".join(sorted_header_keys)
        canonical_request = "\n".join(
            [
                method,
                parsed.path or "/",
                parsed.query,
                canonical_headers,
                signed_header_names,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(self._signing_key(date_stamp), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        signed_headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_header_names}, Signature={signature}"
        )
        return signed_headers

    def _signing_key(self, date_stamp: str) -> bytes:
        k_date = hmac.new(("AWS4" + self.secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
        k_region = hmac.new(k_date, self.region.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
        return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


class AssetService:
    allowed_kinds = {"image", "video", "mask", "thumbnail"}

    def __init__(self) -> None:
        self.storage = S3AssetStorage() if settings.asset_store == "s3" else LocalAssetStorage()

    def create_from_bytes(
        self,
        db: Session,
        user_id: str,
        data: bytes,
        filename: str,
        kind: str,
        purpose: str,
        mime_type: str | None = None,
        source: str = "upload",
        provider_meta: dict[str, Any] | None = None,
    ) -> models.MediaAsset:
        self._validate_size(data)
        suffix = Path(filename).suffix or self._suffix_from_mime(mime_type)
        asset_id = new_id("asset")
        storage_key = f"{user_id}/{asset_id}{suffix}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            path = Path(tmp.name)
            tmp.write(data)
        try:
            return self.create_from_file(
                db=db,
                user_id=user_id,
                file_path=path,
                kind=kind,
                purpose=purpose,
                mime_type=mime_type,
                source=source,
                provider_meta=provider_meta,
                asset_id=asset_id,
                storage_key=storage_key,
            )
        finally:
            path.unlink(missing_ok=True)

    def create_from_base64(
        self,
        db: Session,
        user_id: str,
        b64_data: str,
        filename: str,
        kind: str,
        purpose: str,
        mime_type: str | None = None,
        source: str = "upload",
        provider_meta: dict[str, Any] | None = None,
    ) -> models.MediaAsset:
        if "," in b64_data and b64_data.strip().startswith("data:"):
            header, b64_data = b64_data.split(",", 1)
            if not mime_type:
                mime_type = header.split(";", 1)[0].replace("data:", "")
        return self.create_from_bytes(db, user_id, base64.b64decode(b64_data), filename, kind, purpose, mime_type, source=source, provider_meta=provider_meta)

    def create_from_url(
        self,
        db: Session,
        user_id: str,
        url: str,
        filename: str,
        kind: str,
        purpose: str,
        mime_type: str | None = None,
    ) -> models.MediaAsset:
        data, response_headers = self._download_remote_url(url)
        mime_type = mime_type or response_headers.get("content-type", "").split(";", 1)[0] or mimetypes.guess_type(filename)[0]
        if filename == "upload.bin":
            filename = f"remote{self._suffix_from_mime(mime_type)}"
        return self.create_from_bytes(
            db=db,
            user_id=user_id,
            data=data,
            filename=filename,
            kind=kind,
            purpose=purpose,
            mime_type=mime_type,
            source="remote_url",
            provider_meta={"source_url_hash": hashlib.sha256(url.encode("utf-8")).hexdigest()},
        )

    def create_from_file(
        self,
        db: Session,
        user_id: str,
        file_path: Path,
        kind: str,
        purpose: str,
        mime_type: str | None = None,
        source: str = "upload",
        provider_meta: dict[str, Any] | None = None,
        asset_id: str | None = None,
        storage_key: str | None = None,
        width: int | None = None,
        height: int | None = None,
        duration_ms: int | None = None,
    ) -> models.MediaAsset:
        asset_id = asset_id or new_id("asset")
        if kind not in self.allowed_kinds:
            raise ValueError("ASSET_KIND_UNSUPPORTED")
        mime_type = mime_type or mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self._validate_kind_mime(kind, mime_type)
        if storage_key is None:
            storage_key = f"{user_id}/{asset_id}{file_path.suffix}"

        data = file_path.read_bytes()
        self._validate_size(data)
        sha = hashlib.sha256(data).hexdigest()
        size = len(data)
        if kind in {"image", "mask", "thumbnail"} and (width is None or height is None):
            try:
                with Image.open(file_path) as img:
                    width, height = img.size
            except Exception:
                raise ValueError("ASSET_IMAGE_INVALID")
        if kind == "video":
            probed = self._probe_video_metadata(file_path)
            width = width or probed.get("width")
            height = height or probed.get("height")
            duration_ms = duration_ms or probed.get("duration_ms")
        self._validate_media_limits(kind, width, height, duration_ms)
        self.storage.write_bytes(storage_key, data, mime_type)

        asset = models.MediaAsset(
            id=asset_id,
            user_id=user_id,
            kind=kind,
            purpose=purpose,
            mime_type=mime_type,
            width=width,
            height=height,
            duration_ms=duration_ms,
            size_bytes=size,
            sha256=sha,
            storage_key=storage_key,
            source=source,
            provider_meta_json=dumps(provider_meta or {}),
        )
        db.add(asset)
        db.flush()
        if kind == "video":
            self._attach_video_thumbnail(db, user_id, asset, file_path)
        return asset

    def path_for(self, asset: models.MediaAsset) -> Path:
        path = self.storage.path_for(asset.storage_key)
        if path is None:
            raise RuntimeError("ASSET_STORAGE_NOT_LOCAL")
        return path

    def read_bytes(self, asset: models.MediaAsset) -> bytes:
        return self.storage.read_bytes(asset.storage_key)

    def storage_backend(self) -> str:
        return self.storage.name

    def public_url(self, asset: models.MediaAsset, expires_in: int | None = None) -> str:
        expires_at = int(time.time()) + int(expires_in or settings.asset_url_ttl_seconds)
        signature = self.sign(asset.id, expires_at)
        query = urlencode({"expires": expires_at, "signature": signature})
        return f"{settings.public_base_url}/v1/assets/{asset.id}/content?{query}"

    def sign(self, asset_id: str, expires_at: int) -> str:
        payload = f"{asset_id}:{expires_at}".encode("utf-8")
        secret = settings.asset_signing_secret.encode("utf-8")
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def verify_signature(self, asset_id: str, expires_at: int | None, signature: str | None) -> bool:
        if not expires_at or not signature:
            return False
        if expires_at < int(time.time()):
            return False
        expected = self.sign(asset_id, expires_at)
        return hmac.compare_digest(expected, signature)

    def delete(self, db: Session, asset: models.MediaAsset) -> None:
        self.storage.delete(asset.storage_key)
        db.delete(asset)

    def _suffix_from_mime(self, mime_type: str | None) -> str:
        if mime_type == "image/png":
            return ".png"
        if mime_type in {"image/jpeg", "image/jpg"}:
            return ".jpg"
        if mime_type == "video/mp4":
            return ".mp4"
        return ".bin"

    def _validate_size(self, data: bytes) -> None:
        if len(data) > settings.asset_max_bytes:
            raise ValueError("ASSET_TOO_LARGE")

    def _download_remote_url(self, url: str) -> tuple[bytes, httpx.Headers]:
        current_url = self._validate_remote_url(url)
        redirects = 0
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            while True:
                with client.stream("GET", current_url) as response:
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("REMOTE_URL_REDIRECT_LOCATION_MISSING")
                        if redirects >= settings.asset_remote_url_max_redirects:
                            raise ValueError("REMOTE_URL_REDIRECT_TOO_DEEP")
                        redirects += 1
                        current_url = self._validate_remote_url(urljoin(current_url, location))
                        continue
                    if response.status_code >= 400:
                        raise ValueError(f"REMOTE_URL_FETCH_FAILED:{response.status_code}")
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > settings.asset_max_bytes:
                                raise ValueError("ASSET_TOO_LARGE")
                        except ValueError as exc:
                            if str(exc) == "ASSET_TOO_LARGE":
                                raise
                    data = self._read_limited_response(response)
                    return data, response.headers

    def _read_limited_response(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > settings.asset_max_bytes:
                raise ValueError("ASSET_TOO_LARGE")
            chunks.append(chunk)
        return b"".join(chunks)

    def _validate_remote_url(self, url: str) -> str:
        candidate = (url or "").strip()
        if not candidate or len(candidate) > settings.asset_remote_url_max_length:
            raise ValueError("REMOTE_URL_INVALID")
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("REMOTE_URL_SCHEME_UNSUPPORTED")
        if parsed.username or parsed.password:
            raise ValueError("REMOTE_URL_CREDENTIALS_UNSUPPORTED")
        if not parsed.hostname:
            raise ValueError("REMOTE_URL_HOST_REQUIRED")
        host = parsed.hostname.rstrip(".").lower()
        allowed_hosts = settings.asset_remote_url_allowed_hosts
        if allowed_hosts and host not in allowed_hosts:
            raise ValueError("REMOTE_URL_HOST_NOT_ALLOWED")
        if not settings.asset_remote_url_allow_private and host not in allowed_hosts:
            self._validate_public_host(host, parsed.port, parsed.scheme)
        return candidate

    def _validate_public_host(self, host: str, port: int | None, scheme: str) -> None:
        try:
            infos = socket.getaddrinfo(host, port or (443 if scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("REMOTE_URL_RESOLUTION_FAILED") from exc
        if not infos:
            raise ValueError("REMOTE_URL_RESOLUTION_FAILED")
        for info in infos:
            address = info[4][0]
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError as exc:
                raise ValueError("REMOTE_URL_RESOLUTION_FAILED") from exc
            if not parsed_address.is_global:
                raise ValueError("REMOTE_URL_PRIVATE_ADDRESS_BLOCKED")

    def _validate_kind_mime(self, kind: str, mime_type: str) -> None:
        if kind in {"image", "mask", "thumbnail"} and not mime_type.startswith("image/"):
            raise ValueError("ASSET_MIME_KIND_MISMATCH")
        if kind == "video" and not mime_type.startswith("video/"):
            raise ValueError("ASSET_MIME_KIND_MISMATCH")

    def _validate_media_limits(self, kind: str, width: int | None, height: int | None, duration_ms: int | None) -> None:
        if kind in {"image", "mask", "thumbnail"}:
            if width is None or height is None:
                raise ValueError("ASSET_IMAGE_METADATA_UNAVAILABLE")
            if settings.asset_max_image_width > 0 and width > settings.asset_max_image_width:
                raise ValueError("ASSET_IMAGE_WIDTH_TOO_LARGE")
            if settings.asset_max_image_height > 0 and height > settings.asset_max_image_height:
                raise ValueError("ASSET_IMAGE_HEIGHT_TOO_LARGE")
            if settings.asset_max_image_pixels > 0 and width * height > settings.asset_max_image_pixels:
                raise ValueError("ASSET_IMAGE_PIXELS_TOO_LARGE")
        if kind == "video":
            if width is not None and settings.asset_max_video_width > 0 and width > settings.asset_max_video_width:
                raise ValueError("ASSET_VIDEO_WIDTH_TOO_LARGE")
            if height is not None and settings.asset_max_video_height > 0 and height > settings.asset_max_video_height:
                raise ValueError("ASSET_VIDEO_HEIGHT_TOO_LARGE")
            max_duration_ms = settings.asset_max_video_duration_seconds * 1000
            if duration_ms is not None and max_duration_ms > 0 and duration_ms > max_duration_ms:
                raise ValueError("ASSET_VIDEO_DURATION_TOO_LONG")

    def _probe_video_metadata(self, path: Path) -> dict[str, int]:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            str(path),
        ]
        try:
            completed = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=15)
            payload = json.loads(completed.stdout or "{}")
            streams = payload.get("streams") or []
            stream = streams[0] if streams else {}
            duration = float((payload.get("format") or {}).get("duration") or 0)
            return {
                "width": int(stream.get("width") or 0) or None,
                "height": int(stream.get("height") or 0) or None,
                "duration_ms": int(duration * 1000) if duration > 0 else None,
            }
        except Exception:
            return {}

    def _attach_video_thumbnail(self, db: Session, user_id: str, video_asset: models.MediaAsset, video_path: Path) -> None:
        meta = loads(video_asset.provider_meta_json, {})
        if meta.get("thumbnail_asset_id"):
            return
        thumb_path = self._make_video_thumbnail(video_path, video_asset.width, video_asset.height)
        try:
            thumbnail = self.create_from_file(
                db=db,
                user_id=user_id,
                file_path=thumb_path,
                kind="thumbnail",
                purpose="thumbnail",
                mime_type="image/png",
                source="generated",
                provider_meta={"parent_asset_id": video_asset.id, "source": "video_thumbnail"},
            )
            meta["thumbnail_asset_id"] = thumbnail.id
            meta["thumbnail_url_hint"] = "Use /v1/assets/{thumbnail_asset_id}/content with a signed URL."
            video_asset.provider_meta_json = dumps(meta)
            db.flush()
        finally:
            thumb_path.unlink(missing_ok=True)

    def _make_video_thumbnail(self, video_path: Path, width: int | None, height: int | None) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            "0",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            "scale='min(640,iw)':-2",
            str(tmp_path),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            if tmp_path.exists() and tmp_path.stat().st_size > 0:
                return tmp_path
        except Exception:
            pass
        self._make_fallback_thumbnail(tmp_path, width, height)
        return tmp_path

    def _make_fallback_thumbnail(self, path: Path, width: int | None, height: int | None) -> None:
        canvas_w = min(max(width or 320, 160), 640)
        canvas_h = min(max(height or 180, 90), 360)
        image = Image.new("RGB", (canvas_w, canvas_h), color=(24, 27, 31))
        image.save(path, format="PNG")
