# media2api SDK Examples

This directory contains minimal client examples that call the deployed HTTP API directly.

## Python

Run against a local server:

```powershell
.venv\Scripts\python.exe examples\media2api_sdk.py `
  --base-url http://127.0.0.1:8080 `
  --api-key dev-admin-key `
  --download-dir var\example-downloads
```

Run against the current deployed server:

```powershell
.venv\Scripts\python.exe examples\media2api_sdk.py `
  --base-url http://192.168.31.26:18082 `
  --api-key dev-admin-key `
  --download-dir var\remote-example-downloads
```

The example covers:

- `GET /v1/models`
- `POST /v1/images/generations`
- `POST /v1/assets`
- `POST /v1/videos/generations`
- polling `GET /v1/media-jobs/{job_id}`
- signed asset download
- `GET /v1/admin/analytics`

The script uses only Python standard library modules.

## Reference HTTP Connector

`reference_connector.py` is a minimal sidecar template for already-authorized
provider accounts. It implements the HTTP surface expected by the generic
`http_adapter`:

- `GET /health`
- `GET /capabilities`
- `GET /quota`
- `POST /v1/images/generations`
- `POST /v1/images/edits`
- `POST /v1/videos/generations`
- `GET /tasks/{task_id}`
- `POST /tasks/{task_id}/cancel`

Run it locally:

```powershell
.venv\Scripts\python.exe examples\reference_connector.py `
  --host 127.0.0.1 `
  --port 18120 `
  --token reference-connector-token
```

Then configure a provider with `base_config.base_url=http://127.0.0.1:18120`
and an account credential such as `secret://...` or `env://...`. The reference
implementation returns deterministic placeholder media; replace the submit,
poll, cancel, and quota functions with calls to your authorized upstream
resource.

After creating the provider and account, sync the connector-published
capabilities into the platform:

```powershell
curl -X POST -H "Authorization: Bearer dev-admin-key" `
  "http://127.0.0.1:8080/v1/admin/providers/{provider_id}/sync-capabilities"
```

The smoke test below exercises that capability sync, provider health check,
quota sync, contract test, synchronous image generation, and asynchronous
polling path.

Verify the full platform integration path:

```powershell
.venv\Scripts\python.exe scripts\reference_connector_smoke_test.py
```
