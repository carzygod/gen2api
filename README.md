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

The deployed platform is core-ready after fake/demo data is cleared. Core-ready
means the API gateway, route catalog, model mappings, runtime, asset storage,
admin workbench, billing, governance, and proxy-kernel onboarding flow are
available. Production readiness still requires at least one authorized non-mock
mixed-media connector/account plus a loopback runtime and live sample evidence
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

Finalized proxy-kernel provider templates explicitly map image operations to
`/v1/images/*` and video operations, including extension, to
`/v1/videos/generations`.
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
checksum candidate matrices, checksum-resolved release candidate installation,
bulk release candidate install planning, hash-verified release archive extraction,
bulk source-repo fallback planning/sync for repositories without installable
release assets,
live workspace dry-run preflight, self-recording runtime health checks,
provider-level live acceptance dry-runs, operator handoff packages, safe
operator handoff dry-run runners, activation workflow guides, production gap
reports, loopback runtime contract matrices, production readiness matrices,
loopback contract self-tests, go-live checklists, process status, and
stdout/stderr log inspection. The `/admin` dashboard has a
dedicated "反代内核" workspace for the same workflow, so operators do not need
to hand-write JSON for routine runtime start/stop checks. The first user-facing
entry is the go-live package:
`GET /v1/admin/proxy-kernels/{provider_id}/go-live-package`. It compresses
account material, release/source runtime, health evidence, live sample
acceptance, downstream user API Key, and `/v1/images/*` / `/v1/videos/*`
samples into one operator-readable page. The activation workflow remains the
detailed stage view: route, real account material, release/source runtime,
health check, live sample acceptance, then downstream user API Key. The
dashboard renders both paths as stage cards instead of requiring operators to
read raw JSON first, and those cards can jump to the matching account, runtime,
or user-key workspace or run safe platform-side checks.
For runtime acquisition, use
`GET /v1/admin/proxy-kernels/{provider_id}/runtime-acquisition-plan`. It
answers the operator question directly: keep using the preferred Release
binary path, install a checksum-resolved asset, manually supply SHA256, or only
then fall back to `source-repo/` for protocol inspection/build/rewrite. The
endpoint is read-only: even with `resolve_release=true` it only reads Release
metadata, GitHub Release asset `digest` values, and small checksum files; it
never downloads binaries or clones source. Automatic install candidates are
limited to preferred Linux/x64 assets for the current server; Windows/macOS,
winget, Docker, and ARM assets remain visible for audit but are not selected.
The production gap report is the stricter "can users actually use this now?"
view: real account material, loopback runtime, health evidence, live sample
acceptance, and a downstream user API key must all be present before a provider
is marked ready to use.
`GET/POST /v1/admin/proxy-kernels/{provider_id}/downstream-call-package`
is the final customer-call handoff. It separates ordinary downstream API keys
from the admin bootstrap key, reports the remaining blockers, and returns
ready-to-run `/v1/images/*` and `/v1/videos/*` curl samples. It only creates a
normal user/API key when `dry_run=false`, `create_user=true`, and
`create_user_api_key=true` are explicitly supplied.
For a single provider, `POST /v1/admin/proxy-kernels/{provider_id}/activation-run`
turns the same checklist into a dry-run-first activation session, then returns
the refreshed production gap report and the next required material.
`GET/POST /v1/admin/proxy-kernels/{provider_id}/account-materials` gives the
operator an exact account-material template and dry-run validation before a
real cookie/session/profile is imported. The admin proxy-kernel workspace also
renders that package as a form, rejects unchanged `<...>` placeholders, and lets
the operator preflight before importing the account pool entry.
The form separates sensitive `credential_value` from non-secret
`resource_profile` fields, so inputs such as Midjourney `guild_id`/`channel_id`
or Gemini `project_id` are not mixed into cookie/token material.
For managed runtimes that need local credential files, the import response also
contains `runtime_credential_sync`. `POST
/v1/admin/proxy-kernels/{provider_id}/runtime-credentials/sync` can replay that
step later, for example after restarting GEM-CLI-02. Gemini CLI OAuth material
is normalized into CLIProxyAPI-compatible `auth-dir/*.json` files under
`MEDIA2API_PROXY_KERNEL_DIR`; the platform records the path, size, and SHA256
but never echoes the token body.
Runtime onboarding
prefers fixed release binaries with explicit SHA256 verification. Full source
repositories are synced into `source-repo/` only when release assets are
missing, protocol details must be inspected, local builds are unavoidable, or
an adapter rewrite needs reference code. Synced source repositories can be
inspected for Node/Go/Python/Docker runtime commands, then wrapped in a
SHA256-recorded launcher artifact under the persistent
`MEDIA2API_PROXY_KERNEL_DIR` runtime directory; the launcher still runs through
the same loopback-only `start-runtime` gate. A bulk source-runtime-plan matrix
summarizes synced repositories, detected project types, setup commands, start
candidates, and next actions without executing third-party code. Source
dependency/build setup is also exposed as a planned command runner and only
executes commands discovered by `source-runtime-plan` with `shell=false`.
Operator handoff packages include
the same source setup and launcher payloads, so release and source fallback
paths can be advanced through one dry-run-first workflow.
After a release asset is installed and SHA256-verified, operators should run
`POST /v1/admin/proxy-kernels/{provider_id}/runtime-preflight` before
`start-runtime`. The preflight executes the selected artifact with a short
`--help` timeout to catch server-local failures such as missing GLIBC versions,
wrong architecture, missing dynamic libraries, or permission problems. If it
fails, runtime acquisition moves to the `source-repo/` build/reference fallback
instead of presenting the release as start-ready. When the source checkout is
not present yet, the next action is `source_repo_reference` first; after sync it
becomes `source_runtime_plan`.
Some binaries also need a local config file before they can stay running. The
`start-runtime` payload supports `config_files`, written only under that
provider's `MEDIA2API_PROXY_KERNEL_DIR` subtree before launch. GEM-CLI-02 uses
this to generate CLIProxyAPI's loopback-only `config.yaml` and health-checks it
through `/v1/models`.

In the proxy-kernel dashboard, "可直接用" is intentionally strict: route
mappings, a loopback runtime, real account material, runtime health, and live
image/video acceptance samples must all have evidence. Providers that have the
first prerequisites but no live sample evidence are shown as "待验收", not
production-usable.

`MEDIA2API_PROXY_KERNEL_BOOTSTRAP_ROUTES=true` is enabled by default and by the
bare-metal deploy script. It initializes only finalized proxy-kernel providers
and model mappings, so a freshly cleared platform still knows how to route
OAI/Gemini/Grok/Doubao/Qwen/etc. requests after real accounts and runtimes are
added. It does not create mock accounts, fake upstream credentials, or sample
jobs; `MEDIA2API_SEED_DEFAULTS` remains the separate switch for demo defaults.

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
$env:MEDIA2API_GITHUB_TOKEN="<optional-github-token-for-release-metadata>"
```

`MEDIA2API_GITHUB_TOKEN` is optional and is used only for GitHub Release
metadata, asset digest, and checksum-file reads. It is not an upstream AI
provider API key and is never forwarded to proxy runtimes.

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
$env:MEDIA2API_GITHUB_TOKEN="<optional-github-token-for-release-metadata>"

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
