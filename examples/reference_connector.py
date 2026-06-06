from __future__ import annotations

import argparse
import base64
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNkaGAAAAACAAH0nWNTAAAAAElFTkSuQmCC"


def json_bytes(payload: dict[str, Any], status: int = 200) -> tuple[int, bytes]:
    return status, json.dumps(payload, ensure_ascii=False).encode("utf-8")


class ReferenceConnectorServer(ThreadingHTTPServer):
    token: str
    tasks: dict[str, dict[str, Any]]

    def __init__(self, server_address: tuple[str, int], token: str) -> None:
        super().__init__(server_address, ReferenceConnectorHandler)
        self.token = token
        self.tasks = {}


class ReferenceConnectorHandler(BaseHTTPRequestHandler):
    server: ReferenceConnectorServer

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or "0")
        if length <= 0:
            return {}
        try:
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.token}"
        return not self.server.token or self.headers.get("authorization") == expected

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        code, body = json_bytes(payload, status)
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_png(self) -> None:
        body = base64.b64decode(PNG_B64)
        self.send_response(200)
        self.send_header("content-type", "image/png")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_if_unauthorized(self) -> bool:
        if self._authorized():
            return False
        self._send_json({"status": "failed", "error": "AUTH_REQUIRED", "message": "missing or invalid connector token"}, 401)
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/media/reference.png":
            self._send_png()
            return
        if self._reject_if_unauthorized():
            return
        if path == "/health":
            self._send_json({"status": "ok", "service": "media2api-reference-connector", "time": int(time.time())})
            return
        if path == "/capabilities":
            self._send_json(
                {
                    "operations": ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video", "video_extend"],
                    "models": ["reference-image", "reference-video"],
                    "operation_capabilities": {
                        "text_to_image": {"output_kind": "image", "params": ["prompt", "model", "n", "size", "seed"]},
                        "image_to_image": {"output_kind": "image", "input_asset_fields": ["image", "images"], "max_input_assets": 4},
                        "image_edit": {"output_kind": "image", "input_asset_fields": ["image", "images", "mask"], "max_input_assets": 5},
                        "text_to_video": {"output_kind": "video", "duration_seconds": {"min": 1, "max": 10}},
                        "image_to_video": {"output_kind": "video", "input_asset_fields": ["image", "images"], "duration_seconds": {"min": 1, "max": 10}},
                        "video_extend": {"output_kind": "video", "input_asset_fields": ["video"], "duration_seconds": {"min": 1, "max": 10}},
                    },
                }
            )
            return
        if path == "/quota":
            query = parse_qs(parsed.query)
            operations = query.get("operation") or ["text_to_image"]
            self._send_json(
                {
                    "status": "ok",
                    "message": "reference quota snapshot",
                    "quota_buckets": [
                        {
                            "type": "credits",
                            "remaining_estimate": 1000,
                            "confidence": 0.99,
                            "operations": operations,
                            "provider_models": ["reference-image", "reference-video"],
                        }
                    ],
                }
            )
            return
        if path.startswith("/tasks/"):
            task_id = path.strip("/").split("/")[1]
            task = self.server.tasks.get(task_id)
            if not task:
                self._send_json({"status": "failed", "error": "TASK_NOT_FOUND", "id": task_id}, 404)
                return
            if task.get("status") == "cancelled":
                self._send_json({"id": task_id, "status": "cancelled"})
                return
            task["polls"] = int(task.get("polls") or 0) + 1
            if task["polls"] >= int(task.get("complete_after") or 1):
                task["status"] = "completed"
                self._send_json(self._completed_response(task.get("operation") or "text_to_image", task_id))
                return
            self._send_json({"id": task_id, "status": "queued"})
            return
        self._send_json({"status": "failed", "error": "NOT_FOUND", "path": path}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if self._reject_if_unauthorized():
            return
        if path.endswith("/cancel") and path.startswith("/tasks/"):
            task_id = path.strip("/").split("/")[1]
            task = self.server.tasks.setdefault(task_id, {"id": task_id, "status": "queued"})
            task["status"] = "cancelled"
            self._send_json({"id": task_id, "status": "cancelled", "message": "cancel requested"})
            return
        if path in {"/v1/images/generations", "/v1/images/edits", "/v1/videos/generations"}:
            payload = self._read_json()
            operation = self._operation_from_path(path, payload)
            prompt = str(payload.get("prompt") or "")
            if "async" in prompt.lower() or payload.get("async"):
                task_id = f"task_{int(time.time() * 1000)}"
                self.server.tasks[task_id] = {"id": task_id, "status": "queued", "operation": operation, "polls": 0, "complete_after": 1}
                self._send_json({"id": task_id, "status": "queued"})
                return
            self._send_json(self._completed_response(operation, f"sync_{int(time.time() * 1000)}"))
            return
        self._send_json({"status": "failed", "error": "NOT_FOUND", "path": path}, 404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if self._reject_if_unauthorized():
            return
        if path.startswith("/tasks/"):
            task_id = path.strip("/").split("/")[1]
            task = self.server.tasks.setdefault(task_id, {"id": task_id, "status": "queued"})
            task["status"] = "cancelled"
            self._send_json({"id": task_id, "status": "cancelled", "message": "delete cancel requested"})
            return
        self._send_json({"status": "failed", "error": "NOT_FOUND", "path": path}, 404)

    def _operation_from_path(self, path: str, payload: dict[str, Any]) -> str:
        if payload.get("operation"):
            return str(payload["operation"])
        if path == "/v1/videos/generations":
            return "image_to_video" if payload.get("image") or payload.get("images") else "text_to_video"
        if path == "/v1/images/edits":
            return "image_edit"
        return "text_to_image"

    def _completed_response(self, operation: str, task_id: str) -> dict[str, Any]:
        if operation in {"text_to_video", "image_to_video", "video_extend"}:
            return {
                "id": task_id,
                "status": "completed",
                "assets": [
                    {
                        "b64_json": base64.b64encode(b"media2api reference video placeholder").decode("ascii"),
                        "mime_type": "video/mp4",
                    }
                ],
            }
        return {
            "id": task_id,
            "status": "completed",
            "data": [
                {
                    "b64_json": PNG_B64,
                    "mime_type": "image/png",
                    "revised_prompt": "reference connector output",
                }
            ],
        }

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_server(host: str, port: int, token: str) -> ReferenceConnectorServer:
    return ReferenceConnectorServer((host, port), token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a reference media2api HTTP connector sidecar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18120)
    parser.add_argument("--token", default="reference-connector-token")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.token)
    print(f"reference connector listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
