# gen2api / media2api

`gen2api` is a unified AI media generation gateway. The runtime package is named
`media2api`; it exposes one API surface for text-to-image, image editing,
text-to-video, image-to-video, and video extension while keeping model routing,
provider compatibility, account pools, assets, billing, governance, and
operator evidence as separate platform domains.

The project is an independent platform implementation. It is not a fork of a
single reverse-proxy repository, and OpenAI-compatible routes are only an
external compatibility layer. Real upstream access is expected to come from
authorized HTTP connectors, sidecars, or third-party aggregator adapters.

## Current Status

The deployed platform is core-ready and stability-ready. Production readiness
still requires at least one authorized non-mock mixed-media connector/account
that covers all production operations:

- `text_to_image`
- `image_edit`
- `text_to_video`
- `image_to_video`

The admin reports expose this explicitly as
`authorized_external_connector_accounts`.

## Capabilities

- Unified API key authentication for public and admin APIs.
- OpenAI-compatible media routes:
  - `GET /v1/models`
  - `POST /v1/images/generations`
  - `POST /v1/images/edits`
  - `POST /v1/videos/generations`
  - `GET /v1/videos/generations/{job_id}`
- Native media routes:
  - `POST /v1/media-jobs`
  - `GET /v1/media-jobs/{job_id}`
  - `POST /v1/media-jobs/{job_id}/cancel`
  - `POST /v1/assets`
  - `GET /v1/assets/{asset_id}`
  - `GET /v1/assets/{asset_id}/content`
  - `DELETE /v1/assets/{asset_id}`
- Shared `MediaJob` state machine for image and video tasks.
- Platform asset storage with controlled downloads and generated video
  thumbnails.
- Logical model registry and provider-model mappings.
- Account pool scheduling with expiring leases, concurrency limits, health
  score, failure score, quota buckets, and cooldown.
- Router policies for balanced, lowest-cost, fastest, and best-quality
  selection.
- Fallback behavior for provider failure, timeout, temporary rate limit,
  account unavailability, and task loss.
- Billing holds, settlement, refund, usage records, and provider cost records.
- Admin console for users, models, providers, accounts, jobs, assets, billing,
  alerts, webhooks, audit, contracts, readiness, and delivery reports.
- Credential secret store using `secret://...`, `env://...`, and redacted
  serializers.
- Provider contract tests, connector conformance reports, external connector
  preflight, connector manifests, and final acceptance matrix.
- Prometheus metrics and structured request audit logs.

## Architecture

```text
Client / SDK / Third-party App
  -> API Gateway
  -> Auth / Governance
  -> OpenAI-compatible Adapter
  -> Native Media API
  -> MediaJob Runtime
  -> Model Registry
  -> Media Router
  -> Account Scheduler
  -> Provider Adapter / Connector
  -> Asset Store
  -> Billing / Audit / Observability
  -> Admin Console
```

Key implementation directories:

```text
media2api/      FastAPI app, domain models, runtime, services, adapters
scripts/        smoke tests, acceptance audit, deployment helpers
examples/       SDK example and reference HTTP connector
var/            local runtime data; ignored by git
```

## Supported Provider Templates

The platform ships provider templates for:

- `mock`
- `openai_image`
- `gemini`
- `grok`
- `qwen`
- `jimeng`
- `kling`
- `luma`
- `runway`
- `midjourney`
- `pollinations`
- `openrouter_image`
- `fal_replicate`
- `seedream_proxy`
- `amux_qwen`
- `flux_stability`

Production-ready external operation coverage is validated at runtime by:

- `GET /v1/admin/production-go-live-plan`
- `GET /v1/admin/connector-conformance-report`
- `GET /v1/admin/external-connector-preflight`
- `GET /v1/admin/final-acceptance-matrix`

## Finalized Reverse Proxy Kernel Scope

The first production connector phase is based on reverse-proxy, Web session,
CLI OAuth/session, local client credential, and subscription-to-API style
kernels. Official SDK/API-key-only routes are out of scope for this phase.

Runtime boundaries:

1. The platform must not embed and host third-party reverse-proxy projects as
   long-running public services.
2. Selected Go/Node/Python projects may be used as fixed-version,
   fixed-hash, loopback-only binary/subprocess executors for controlled
   validation or adapter operation.
3. The first delivery priority is `/v1/images/*` and `/v1/videos/*`, not text
   chat, embeddings, or generic agent features.

Selected kernel references:

| Selection | Provider target | Repository | First-phase role |
|---|---|---|---|
| `OAI-WEB-01` | `openai_web_session` | `basketikun/chatgpt2api` | ChatGPT Web session image generation/editing |
| `OAI-CODEX-04` | `openai_codex` | `cnlimiter/codex-manager` | Codex account control and GPT Image 2 validation |
| `GEM-CLI-02` | `gemini_cli_oauth` | `router-for-me/CLIProxyAPI` | Gemini CLI OAuth plus image/video validation |
| `GEM-WEB-01` | `gemini_web_session` | `HanaokaYuzu/Gemini-API` | Gemini Web session image/video wrapper |
| `AG-01` | `antigravity` | `ink1ing/anti-api` | Antigravity account, proxy, and health validation |
| `GROK-01` | `grok` | `chenyme/grok2api` | Grok Web/session image and video execution |
| `JM-01` | `jimeng_web_session` | `iptag/jimeng-api` | Jimeng/Dreamina image reverse-proxy path |
| `DOUBAO-WEB-01` | `doubao_web_session` | `wangchuxiaoji-oss/doubao2api` | Doubao image/video path, separate from Jimeng quotas |
| `KLING-WEB-01` | `kling_web_session` | `yihong0618/klingCreator` | Kling Web/session video execution |
| `LUMA-WEB-01` | `luma_web_session` | `yihong0618/LumaDreamCreator` | Luma Web cookie video execution |
| `MID-01` | `midjourney_discord_session` | `trueai-org/midjourney-proxy` | Midjourney Discord/session task channel |
| `QWEN-AI-01` | `qwen_ai_web_session` | `Rfym21/Qwen2API` | `qwen.ai` / `chat.qwen.ai` image/video path |
| `QIANWEN-WEB-01` | `qianwen_web_session` | `kao0312/qianwen2api` | `qianwen.com` / Tongyi Qianwen web path |

Explicit first-phase exclusions:

- `WENXIN`: no selected usable Web/session media kernel in this phase.
- `SELF`: no self-hosted worker/model route in this phase.
- `EX`: official SDK/API-key-only and public aggregator API routes are not
  selected.

Provider split required by the finalized scope:

- `openai_web_session` and `openai_codex` must remain separate.
- `gemini_cli_oauth`, `gemini_web_session`, and `antigravity` must remain
  separate.
- `doubao_web_session` must not share account pools, daily quota accounting, or
  health state with `jimeng_web_session`.
- `qwen_ai_web_session` and `qianwen_web_session` must remain separate because
  `qwen.ai` and `qianwen.com` are different web product entry points.

Detailed selection documents:

- [Reverse proxy kernel selection](docs/反代内核开源仓库选型.md)
- [Finalized reverse proxy kernel selection](docs/反代内核仓库选型定型文档.md)
- [Reverse proxy kernel runtime guide](docs/反代内核运行时接入指南.md)

The admin API exposes the runtime lifecycle through
`/v1/admin/proxy-kernels`: release probing, SHA256-verified installation,
loopback runtime registration, controlled subprocess start/stop, routing-plan
inspection, bulk no-fake-account provider/model mapping application, material
request checklists, runtime delivery plans, release probe matrices, release
checksum candidate matrices, checksum-resolved release candidate installation, loopback
runtime contract matrices, production readiness matrices, loopback contract
self-tests, go-live checklists, process status, and stdout/stderr log inspection. The `/admin` dashboard has a
dedicated "反代内核" workspace for the same workflow, so operators do not need
to hand-write JSON for routine runtime start/stop checks. When release
binaries are not enough, the same workspace can sync allowlisted selected
repositories into `source-repo/` for protocol inspection, local builds, or
adapter rewrite reference.

## Local Development

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe -m uvicorn media2api.main:app --host 0.0.0.0 --port 8080
```

Local defaults are for development only. For production or shared deployments,
set real values through the environment:

```powershell
$env:MEDIA2API_BOOTSTRAP_KEY="<admin-api-key>"
$env:MEDIA2API_ADMIN_PASSWORD="<admin-dashboard-password>"
$env:MEDIA2API_SECRET_ENCRYPTION_KEY="<32-byte-or-longer-secret>"
$env:MEDIA2API_ASSET_SIGNING_SECRET="<asset-url-signing-secret>"
```

Common local checks:

```powershell
$env:MEDIA2API_API_KEY="<admin-api-key>"
curl http://localhost:8080/health
curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" http://localhost:8080/v1/runtime
curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" http://localhost:8080/v1/models
```

Admin console:

```text
http://localhost:8080/admin
```

Default local login is `admin` plus `MEDIA2API_ADMIN_PASSWORD`. If that
variable is not set, the dashboard falls back to `MEDIA2API_BOOTSTRAP_KEY` for
bootstrap deployments. Successful login stores an HttpOnly
`media2api_admin_key` session cookie, so the dashboard can call `/v1/admin/*`
without pasting an API key into the page.

## Docker Compose

```powershell
docker compose up --build
```

The compose file starts the API with PostgreSQL and Redis. Override credentials
through environment variables before running it in a shared environment.

## Deployment

The bare-metal deployment script uploads the app, configures PostgreSQL, Redis,
systemd services, and the worker process on the target host.

Required inputs should be passed as environment variables or CLI arguments.
Do not commit host passwords or API keys.

```powershell
$env:DEPLOY_HOST="<server-ip>"
$env:DEPLOY_USER="<ssh-user>"
$env:DEPLOY_PASSWORD="<ssh-password>"
$env:MEDIA2API_BOOTSTRAP_KEY="<admin-api-key>"

.venv\Scripts\python.exe scripts\deploy_bare.py `
  --host $env:DEPLOY_HOST `
  --user $env:DEPLOY_USER `
  --password $env:DEPLOY_PASSWORD `
  --public-port 18082 `
  --api-key $env:MEDIA2API_BOOTSTRAP_KEY
```

After deployment:

```powershell
.venv\Scripts\python.exe scripts\acceptance_audit.py `
  --base-url http://<server-ip>:18082 `
  --api-key $env:MEDIA2API_BOOTSTRAP_KEY
```

## External Connector Onboarding

Use provider templates to connect authorized account resources. A connector must
provide a compatible HTTP surface such as health, capabilities, quota,
generation submit, task poll, result fetch, and cancel.

Useful reports:

```powershell
curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  "http://localhost:8080/v1/admin/production-go-live-plan"

curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  "http://localhost:8080/v1/admin/connector-conformance-report"

curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  "http://localhost:8080/v1/admin/external-connector-preflight?provider_id=jimeng"
```

Generate a redacted connector manifest template:

```powershell
curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  "http://localhost:8080/v1/admin/external-connector-manifest-template?provider_id=jimeng"
```

Dry-run a multi-account connector manifest:

```powershell
curl -X POST -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  -H "Content-Type: application/json" `
  "http://localhost:8080/v1/admin/external-connector-manifest" `
  -d '{
    "provider_id": "jimeng",
    "base_url": "https://connector.example.com",
    "credential_ref": "env://MEDIA2API_JIMENG_CONNECTOR_TOKEN",
    "dry_run": true,
    "operations": ["text_to_image", "image_edit", "text_to_video", "image_to_video"],
    "accounts": [
      {"account_id": "acct_jimeng_1", "account_label": "Jimeng account 1", "concurrency_limit": 1},
      {"account_id": "acct_jimeng_2", "account_label": "Jimeng account 2", "credential_ref": "env://MEDIA2API_JIMENG_CONNECTOR_TOKEN_2", "concurrency_limit": 1}
    ]
  }'
```

If `credential_value` is supplied during apply, the platform stores it as an
encrypted credential secret and returns only a redacted reference.

## Reference Connector

The repository includes a deterministic reference connector for adapter
development:

```powershell
.venv\Scripts\python.exe scripts\reference_connector_smoke_test.py
```

Files:

- `examples/reference_connector.py`
- `examples/media2api_sdk.py`
- `examples/README.md`

## Acceptance And Delivery Reports

Primary reports:

```powershell
curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  "http://localhost:8080/v1/admin/readiness"

curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  "http://localhost:8080/v1/admin/acceptance-report"

curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  "http://localhost:8080/v1/admin/system-requirements-report"

curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  "http://localhost:8080/v1/admin/final-acceptance-matrix"

curl -H "Authorization: Bearer $env:MEDIA2API_API_KEY" `
  "http://localhost:8080/v1/admin/delivery-package"
```

Expected state without real external account credentials:

- `core_ready: true`
- `production_ready: false`
- final acceptance blocker: `authorized_external_connector_accounts`

## Tests

Run the main local test suite:

```powershell
.venv\Scripts\python.exe -m compileall media2api scripts examples
.venv\Scripts\python.exe scripts\smoke_test.py
```

Targeted checks:

```powershell
.venv\Scripts\python.exe scripts\contract_smoke_test.py
.venv\Scripts\python.exe scripts\connector_smoke_test.py
.venv\Scripts\python.exe scripts\reference_connector_smoke_test.py
.venv\Scripts\python.exe scripts\example_sdk_smoke_test.py
.venv\Scripts\python.exe scripts\routing_smoke_test.py
.venv\Scripts\python.exe scripts\resilience_smoke_test.py
.venv\Scripts\python.exe scripts\webhook_smoke_test.py
.venv\Scripts\python.exe scripts\pollinations_adapter_smoke_test.py
.venv\Scripts\python.exe scripts\stability_audit.py --iterations 1000
```

Remote resilience audit:

```powershell
$env:DEPLOY_PASSWORD="<ssh-password>"
.venv\Scripts\python.exe scripts\remote_resilience_audit.py `
  --base-url http://<server-ip>:18082 `
  --host <server-ip> `
  --user <ssh-user> `
  --password $env:DEPLOY_PASSWORD `
  --api-key $env:MEDIA2API_BOOTSTRAP_KEY
```

## Metrics And Logs

Prometheus:

```text
GET /metrics
```

Important metric aliases:

- `media_jobs_total`
- `media_job_duration_seconds`
- `provider_submit_errors_total`
- `provider_poll_timeout_total`
- `account_lease_active`
- `account_failure_score`
- `asset_ingest_failed_total`
- `billing_holds_total`
- `fallback_attempts_total`

Structured request audit logs include:

- `request_id`
- `job_id`
- `attempt_id`
- `user_id`
- `provider_id`
- `account_id`
- `logical_model`
- `provider_model`
- `provider_task_id`
- `standard_error_code`

## Security Notes

- Do not commit `.env`, runtime databases, generated assets, API keys, SSH
  passwords, connector tokens, or cookie material.
- API keys are stored as hashes.
- Provider credentials must be referenced through `secret://...`, `env://...`,
  or another redacted credential reference.
- Inline `plain://...` and `bearer://...` values are only accepted as operator
  input paths that migrate the value into encrypted credential secret storage.
- Admin/config export/report endpoints redact credential values.
- The platform does not include steps for bypassing login, scraping cookies, or
  evading upstream risk controls. Connector operators are responsible for using
  authorized account resources.

## Repository Hygiene

Generated files are ignored by `.gitignore`, including:

- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `.env`
- local databases
- `var/`
- logs
- downloaded artifacts
