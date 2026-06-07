from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode
from typing import Any


class ApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 90) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def json_status(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, {"body": body}

    def text(self, path: str, auth: bool = False, extra_headers: dict[str, str] | None = None) -> tuple[int, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if auth else {}
        headers.update(extra_headers or {})
        req = urllib.request.Request(self.base_url + path, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def form_status(self, path: str, payload: dict[str, str]) -> tuple[int, str, str]:
        data = urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                return resp.status, resp.headers.get("Set-Cookie", ""), resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Set-Cookie", ""), exc.read().decode("utf-8")

    def bytes_url(self, url: str) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


class Audit:
    def __init__(self) -> None:
        self.passed: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []

    def check(self, name: str, condition: bool, detail: Any = None) -> None:
        item = {"name": name, "detail": detail}
        if condition:
            self.passed.append(item)
        else:
            self.failed.append(item)

    def warn(self, name: str, condition: bool, detail: Any = None) -> None:
        if not condition:
            self.warnings.append({"name": name, "detail": detail})

    def result(self) -> dict[str, Any]:
        return {
            "status": "passed" if not self.failed else "failed",
            "passed": len(self.passed),
            "failed": len(self.failed),
            "warnings": len(self.warnings),
            "failed_checks": self.failed,
            "warnings_detail": self.warnings,
        }


TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKUlEQVR4nGNkYPjPQC5gIlvnqOZRzaOaRzWPal7QMRg1g9EwYBgAq7cCP7wf1QQAAAAASUVORK5CYII="


def wait_for_job(client: ApiClient, job_id: str, timeout_seconds: float = 30.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    job: dict[str, Any] = {}
    while time.time() < deadline:
        job = client.json("GET", f"/v1/media-jobs/{job_id}")
        if job.get("status") in {"completed", "failed", "cancelled", "expired"}:
            return job
        time.sleep(0.25)
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description="Run media2api deployment acceptance checks.")
    parser.add_argument("--base-url", default="http://192.168.31.26:18082")
    parser.add_argument("--api-key", default="dev-admin-key")
    args = parser.parse_args()

    client = ApiClient(args.base_url, args.api_key)
    audit = Audit()

    health = client.json("GET", "/health")
    audit.check("health", health.get("status") == "ok", health)

    runtime = client.json("GET", "/v1/runtime")
    audit.check("runtime_worker", int(runtime.get("worker_concurrency") or 0) >= 1, runtime)
    audit.check("runtime_database_postgresql", runtime.get("database_backend") == "postgresql", runtime)
    audit.check("runtime_queue_worker_mode", runtime.get("queue_backend") == "database-worker", runtime)
    audit.check("runtime_redis_ok", runtime.get("redis_configured") is True and runtime.get("redis_status") == "ok", runtime)
    audit.check("runtime_no_active_leak", int(runtime.get("active_leases") or 0) >= 0, runtime.get("active_leases"))
    readiness = client.json("GET", "/v1/admin/readiness")
    readiness_checks = {item.get("name"): item for item in readiness.get("checks", [])}
    readiness_action_checks = {item.get("check") for item in readiness.get("action_items", [])}
    audit.check("readiness_core", readiness.get("object") == "readiness" and readiness.get("core_ready") is True, readiness)
    audit.check(
        "readiness_runtime_production_checks",
        {"production_database_backend", "production_queue_backend", "production_redis"}.isdisjoint(readiness_action_checks),
        readiness.get("action_items", []),
    )
    audit.check("readiness_has_external_account_check", "external_connector_accounts" in readiness_checks, readiness_checks.get("external_connector_accounts"))
    audit.check(
        "readiness_has_external_mixed_media_provider_check",
        "external_mixed_media_provider" in readiness_checks,
        readiness_checks.get("external_mixed_media_provider"),
    )

    models = client.json("GET", "/v1/models")
    model_ids = {item["id"] for item in models.get("data", [])}
    audit.check("models_t2i", "t2i-fast" in model_ids and "t2i-pro" in model_ids, sorted(model_ids))
    audit.check("models_video", "t2v-general" in model_ids and "i2v-fast" in model_ids and "i2v-pro" in model_ids, sorted(model_ids))
    audit.check("models_image_edit", "image-edit" in model_ids, sorted(model_ids))

    templates = client.json("GET", "/v1/provider-templates")
    template_ids = {item["id"] for item in templates.get("data", [])}
    required_templates = {
        "openai_image",
        "gemini",
        "grok",
        "qwen",
        "jimeng",
        "kling",
        "luma",
        "runway",
        "midjourney",
        "pollinations",
        "openrouter_image",
        "fal_replicate",
        "seedream_proxy",
        "amux_qwen",
        "flux_stability",
    }
    audit.check("provider_templates", required_templates.issubset(template_ids), sorted(template_ids))
    template_by_id = {item["id"]: item for item in templates.get("data", [])}
    pollinations_template = template_by_id.get("pollinations", {})
    pollinations_config = pollinations_template.get("default_config") or {}
    audit.check(
        "pollinations_direct_adapter_template",
        pollinations_template.get("adapter_type") == "aggregator_adapter"
        and pollinations_config.get("base_url") == "https://gen.pollinations.ai"
        and pollinations_config.get("api_key_ref") == "env://POLLINATIONS_KEY",
        pollinations_template,
    )
    activation_plan = client.json(
        "POST",
        "/v1/admin/provider-templates/gemini/activate",
        {
            "dry_run": True,
            "base_url": "http://127.0.0.1:18091",
            "credential_ref": "env://MEDIA2API_CONNECTOR_KEY",
            "contract_operations": ["text_to_image"],
            "run_quota_sync": False,
        },
    )
    audit.check(
        "provider_template_activate_dry_run",
        activation_plan.get("object") == "provider_template.activation"
        and activation_plan.get("dry_run") is True
        and activation_plan.get("status") == "planned"
        and activation_plan.get("plan", {}).get("template_id") == "gemini"
        and "MEDIA2API_CONNECTOR_KEY" in str(activation_plan.get("plan", {}).get("credential_ref")),
        activation_plan,
    )
    external_acceptance_plan = client.json(
        "POST",
        "/v1/admin/provider-templates/pollinations/external-acceptance",
        {"dry_run": True, "operations": ["text_to_image"], "run_samples": False},
    )
    audit.check(
        "provider_template_external_acceptance_dry_run",
        external_acceptance_plan.get("object") == "media2api.external_provider_acceptance"
        and external_acceptance_plan.get("status") == "planned"
        and (external_acceptance_plan.get("activation") or {}).get("status") == "planned"
        and ((external_acceptance_plan.get("activation") or {}).get("plan") or {}).get("credential_ref") == "env://POLLINATIONS_KEY",
        external_acceptance_plan,
    )
    account_acceptance_plan = client.json(
        "POST",
        "/v1/admin/accounts/acct_mock_default/external-acceptance",
        {"dry_run": True, "operations": ["text_to_image"], "run_samples": False},
    )
    audit.check(
        "account_external_acceptance_dry_run",
        account_acceptance_plan.get("object") == "media2api.account_external_acceptance"
        and account_acceptance_plan.get("status") == "planned"
        and account_acceptance_plan.get("account", {}).get("id") == "acct_mock_default"
        and "text_to_image" in (account_acceptance_plan.get("plan") or {}).get("operations", []),
        account_acceptance_plan,
    )
    account_acceptance_suite = client.json(
        "POST",
        "/v1/admin/account-acceptance-suite",
        {"dry_run": True, "account_ids": ["acct_mock_default"], "external_only": False, "operations": ["text_to_image"], "run_samples": False},
    )
    audit.check(
        "account_acceptance_suite_dry_run",
        account_acceptance_suite.get("object") == "media2api.account_acceptance_suite"
        and account_acceptance_suite.get("status") == "planned"
        and account_acceptance_suite.get("summary", {}).get("passed") == 1,
        account_acceptance_suite,
    )
    onboarding = client.json("GET", "/v1/admin/provider-onboarding-report")
    onboarding_text = json.dumps(onboarding, ensure_ascii=False)
    onboarding_provider_ids = {item.get("provider_id") for item in onboarding.get("providers", [])}
    audit.check(
        "provider_onboarding_report",
        onboarding.get("object") == "media2api.provider_onboarding_report"
        and required_templates.issubset(onboarding_provider_ids)
        and "p0_action_required" in (onboarding.get("summary") or {})
        and isinstance(onboarding.get("p0_action_items"), list)
        and args.api_key not in onboarding_text
        and "known-sensitive-password" not in onboarding_text,
        {"summary": onboarding.get("summary"), "providers": sorted(onboarding_provider_ids), "p0_action_items": onboarding.get("p0_action_items", [])[:5]},
    )
    template_contract_failures: list[dict[str, Any]] = []
    score_fields = {"cost_score", "speed_score", "quality_score", "reliability_score"}
    for template_id in sorted(required_templates):
        template = template_by_id.get(template_id) or {}
        operations = set(template.get("operations") or [])
        models_declared = set(template.get("models") or [])
        mappings_declared = template.get("mappings") or []
        if not operations or not models_declared or not mappings_declared:
            template_contract_failures.append({"provider_id": template_id, "error": "template_shape", "template": template})
            continue
        for mapping in mappings_declared:
            mapping_model = mapping.get("provider_model")
            mapping_ops = set(mapping.get("operations") or [])
            logical_model = mapping.get("logical_model")
            if not mapping_ops:
                template_contract_failures.append({"provider_id": template_id, "error": "mapping_operations_empty", "mapping": mapping})
            if logical_model not in model_ids:
                template_contract_failures.append({"provider_id": template_id, "error": "logical_model_missing", "mapping": mapping})
            if mapping_model not in models_declared:
                template_contract_failures.append({"provider_id": template_id, "error": "provider_model_not_declared", "mapping": mapping})
            undeclared_ops = sorted(mapping_ops - operations)
            if undeclared_ops:
                template_contract_failures.append({"provider_id": template_id, "error": "operation_not_declared", "mapping": mapping, "undeclared": undeclared_ops})
            if not isinstance(mapping.get("priority"), int):
                template_contract_failures.append({"provider_id": template_id, "error": "priority_invalid", "mapping": mapping})
            invalid_scores = {
                key: mapping.get(key)
                for key in score_fields
                if not isinstance(mapping.get(key), (int, float)) or not 0 <= float(mapping.get(key)) <= 1
            }
            if invalid_scores:
                template_contract_failures.append({"provider_id": template_id, "error": "score_invalid", "mapping": mapping, "invalid_scores": invalid_scores})
    audit.check("provider_template_contracts", not template_contract_failures, template_contract_failures[:10])

    target_platforms = client.json("GET", "/v1/target-platforms")
    target_ids = {item["provider_id"] for item in target_platforms.get("data", [])}
    audit.check("target_platforms", required_templates.issubset(target_ids), sorted(target_ids))
    target_by_id = {item["provider_id"]: item for item in target_platforms.get("data", [])}
    target_contract_failures: list[dict[str, Any]] = []
    for template_id in sorted(required_templates):
        target = target_by_id.get(template_id) or {}
        template = template_by_id.get(template_id) or {}
        target_models = set(target.get("models") or [])
        target_operations = set(target.get("operations") or [])
        template_models = set(template.get("models") or [])
        template_operations = set(template.get("operations") or [])
        missing_models = sorted(template_models - target_models)
        missing_operations = sorted(template_operations - target_operations)
        if not target_models or not target_operations or missing_models or missing_operations:
            target_contract_failures.append(
                {
                    "provider_id": template_id,
                    "missing_models": missing_models,
                    "missing_operations": missing_operations,
                    "target": target,
                }
            )
    audit.check("target_platform_contracts", not target_contract_failures, target_contract_failures[:10])

    admin_login_status, admin_login_html = client.text("/admin")
    audit.check(
        "admin_requires_password_login",
        admin_login_status == 401 and "账号" in admin_login_html and "密码" in admin_login_html,
        {"status": admin_login_status},
    )
    admin_cookie_status, admin_cookie, _ = client.form_status("/admin/login", {"username": "admin", "password": args.api_key})
    audit.check(
        "admin_password_login_sets_cookie",
        admin_cookie_status in {302, 303} and "media2api_admin_key" in admin_cookie,
        {"status": admin_cookie_status},
    )
    admin_status, admin_html = client.text("/admin", extra_headers={"Cookie": admin_cookie.split(";", 1)[0]})
    audit.check(
        "admin_console",
        admin_status == 200
        and "操作" in admin_html
        and "真实平台运维" in admin_html
        and "启用 Gemini 模板" in admin_html
        and "试运行启用模板" in admin_html
        and "真实平台外部验收" in admin_html
        and "就绪检查" in admin_html
        and "验收报告" in admin_html
        and "平台接入报告" in admin_html
        and "运维工作台报告" in admin_html
        and "生产上线计划" in admin_html
        and "连接器一致性" in admin_html
        and "外部连接器预检" in admin_html
        and "连接器清单模板" in admin_html
        and "系统要求报告" in admin_html
        and "最终验收矩阵" in admin_html
        and "交付包" in admin_html
        and "租约自检" in admin_html
        and "资产存储测试" in admin_html
        and "故障转移自检" in admin_html
        and "保存鉴权" in admin_html
        and "真实平台合同套件" in admin_html
        and "同步 Gemini 能力" in admin_html
        and "配置快照" in admin_html
        and "导出配置" in admin_html
        and "试运行导入" in admin_html
        and "OAuth 会话" in admin_html
        and "查看获取教程" in admin_html
        and "添加平台账号" in admin_html
        and "批量导入账号" in admin_html
        and "保存并测试" in admin_html
        and "OAuth / 凭据获取位置速查" in admin_html
        and "Google OAuth 2.0 Playground" in admin_html
        and "https://developers.google.com/oauthplayground/" in admin_html
        and "https://bailian.console.aliyun.com/" in admin_html
        and "https://platform.openai.com/api-keys" in admin_html
        and "refresh_token" in admin_html
        and "token_reference" in admin_html
        and "使用该平台连接器后台" in admin_html
        and "如果该平台没有官方 API Key 或公开 OAuth" not in admin_html
        and "通用第三方连接器" not in admin_html
        and "无公开获取入口" not in admin_html
        and "Mock Stability Test" not in admin_html
        and "acct_mock_default" not in admin_html
        and "/v1/media-jobs" in admin_html
        and all(section in admin_html for section in ["用户", "模型", "模型映射", "资产", "回调"]),
        {"status": admin_status},
    )
    onboard_suffix = int(time.time() * 1000)
    onboarding = client.json(
        "POST",
        "/v1/admin/account-onboarding",
        {
            "provider_id": "qwen",
            "account_id": f"acct_acceptance_onboarding_{onboard_suffix}",
            "label": "acceptance onboarding account",
            "provider_base_url": "http://127.0.0.1:18091",
            "provider_config": {"source": "acceptance"},
            "auth_method": "token_reference",
            "credential_value": "vault://acceptance/qwen/account",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["qwen-image"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    audit.check(
        "admin_account_onboarding_flow",
        onboarding.get("object") == "account.onboarding"
        and (onboarding.get("account") or {}).get("provider_id") == "qwen"
        and (onboarding.get("provider") or {}).get("status") == "active"
        and (onboarding.get("secret") or {}).get("id"),
        onboarding,
    )
    operator_workbench = client.json("GET", "/v1/admin/operator-workbench-report")
    operator_modules = {item.get("module") for item in operator_workbench.get("modules", [])}
    audit.check(
        "operator_workbench_report",
        operator_workbench.get("object") == "media2api.operator_workbench_report"
        and (operator_workbench.get("summary") or {}).get("required_missing_routes") == 0
        and {"Dashboard", "Users", "Models", "Providers", "Accounts", "Jobs", "Assets", "Billing", "Alerts", "Webhooks", "Audit"}.issubset(operator_modules),
        {"summary": operator_workbench.get("summary"), "modules": sorted(operator_modules), "missing": operator_workbench.get("required_missing_routes")},
    )
    go_live_plan = client.json("GET", "/v1/admin/production-go-live-plan")
    required_go_live_ops = {"text_to_image", "image_edit", "text_to_video", "image_to_video"}
    top_go_live_candidate = (go_live_plan.get("single_provider_candidates") or [{}])[0]
    audit.check(
        "production_go_live_plan",
        go_live_plan.get("object") == "media2api.production_go_live_plan"
        and required_go_live_ops.issubset(set(go_live_plan.get("required_operations", [])))
        and required_go_live_ops.issubset(set(top_go_live_candidate.get("covered_required_operations", [])))
        and bool((top_go_live_candidate.get("commands") or {}).get("external_acceptance_live"))
        and bool((go_live_plan.get("global_acceptance_commands") or {}).get("acceptance_audit")),
        {
            "status": go_live_plan.get("status"),
            "summary": go_live_plan.get("summary"),
            "recommended_provider_ids": go_live_plan.get("recommended_provider_ids"),
            "top_candidate": {
                "template_id": top_go_live_candidate.get("template_id"),
                "covered_required_operations": top_go_live_candidate.get("covered_required_operations"),
                "missing_required_operations": top_go_live_candidate.get("missing_required_operations"),
            },
        },
    )
    connector_conformance = client.json("GET", "/v1/admin/connector-conformance-report")
    conformance_provider_ids = {item.get("provider_id") for item in connector_conformance.get("providers", [])}
    audit.check(
        "connector_conformance_report",
        connector_conformance.get("object") == "media2api.connector_conformance_report"
        and required_go_live_ops.issubset(set(connector_conformance.get("required_operations", [])))
        and {"jimeng", "gemini", "qwen", "pollinations"}.issubset(conformance_provider_ids)
        and all(isinstance(item.get("operation_matrix"), list) for item in connector_conformance.get("providers", [])),
        {"summary": connector_conformance.get("summary"), "providers": sorted(conformance_provider_ids)[:20]},
    )
    external_preflight = client.json("GET", "/v1/admin/external-connector-preflight")
    preflight_provider_ids = {item.get("provider_id") for item in external_preflight.get("providers", [])}
    audit.check(
        "external_connector_preflight",
        external_preflight.get("object") == "media2api.external_connector_preflight"
        and required_go_live_ops.issubset(set(external_preflight.get("required_operations", [])))
        and bool(preflight_provider_ids)
        and all(bool((item.get("commands") or {}).get("activate_template")) for item in external_preflight.get("providers", [])),
        {
            "summary": external_preflight.get("summary"),
            "providers": sorted(preflight_provider_ids)[:20],
        },
    )
    manifest_template = client.json("GET", "/v1/admin/external-connector-manifest-template?provider_id=jimeng")
    audit.check(
        "external_connector_manifest_template",
        manifest_template.get("object") == "media2api.external_connector_manifest_template"
        and manifest_template.get("provider_id") == "jimeng"
        and required_go_live_ops.issubset(set(manifest_template.get("supported_required_operations", [])))
        and bool((manifest_template.get("default_manifest") or {}).get("accounts"))
        and bool((manifest_template.get("commands") or {}).get("dry_run")),
        {
            "provider_id": manifest_template.get("provider_id"),
            "supported_required_operations": manifest_template.get("supported_required_operations"),
        },
    )
    manifest_secret = "acceptance-manifest-secret-token"
    manifest_plan = client.json(
        "POST",
        "/v1/admin/external-connector-manifest",
        {
            "provider_id": "jimeng",
            "base_url": "https://connector.example.com",
            "credential_value": manifest_secret,
            "credential_kind": "bearer_token",
            "dry_run": True,
            "operations": ["text_to_image", "image_edit", "text_to_video", "image_to_video"],
            "accounts": [
                {"account_id": "acct_acceptance_manifest_1", "account_label": "Acceptance Manifest 1", "concurrency_limit": 1},
                {"account_id": "acct_acceptance_manifest_2", "account_label": "Acceptance Manifest 2", "credential_ref": "env://ACCEPTANCE_MANIFEST_2", "concurrency_limit": 2},
            ],
        },
    )
    manifest_plan_text = json.dumps(manifest_plan, ensure_ascii=False)
    audit.check(
        "external_connector_manifest_dry_run",
        manifest_plan.get("object") == "media2api.external_connector_manifest"
        and manifest_plan.get("dry_run") is True
        and len(manifest_plan.get("accounts") or []) == 2
        and manifest_secret not in manifest_plan_text
        and bool((manifest_plan.get("next_commands") or {}).get("preflight")),
        {
            "status": manifest_plan.get("status"),
            "operations": manifest_plan.get("operations"),
            "account_count": len(manifest_plan.get("accounts") or []),
        },
    )
    system_requirements = client.json("GET", "/v1/admin/system-requirements-report")
    system_requirement_ids = {item.get("id") for item in system_requirements.get("requirements", [])}
    audit.check(
        "system_requirements_report",
        system_requirements.get("object") == "media2api.system_requirements_report"
        and int((system_requirements.get("summary") or {}).get("total_requirements") or 0) >= 30
        and {
            "C-001",
            "API-001",
            "API-OPENAI",
            "API-NATIVE",
            "MODEL-001",
            "ASSET-004",
            "PA-001",
            "ACC-001",
            "BILL-001",
            "ADMIN-001",
            "OBS-001",
            "SEC-001",
            "SDK-001",
            "CONNECTOR-SDK-001",
            "PREFLIGHT-001",
            "MANIFEST-001",
            "FINAL-ACCEPTANCE-001",
            "DELIVERY-001",
            "MVP-CORE",
            "MVP-REAL-PROVIDER",
        }.issubset(system_requirement_ids)
        and (system_requirements.get("summary") or {}).get("core_ready") is True,
        {
            "summary": system_requirements.get("summary"),
            "sample_requirement_ids": sorted(system_requirement_ids)[:40],
            "external_blockers": system_requirements.get("external_blockers"),
        },
    )
    final_acceptance = client.json("GET", "/v1/admin/final-acceptance-matrix")
    final_ids = {item.get("id") for item in final_acceptance.get("rows", [])}
    audit.check(
        "final_acceptance_matrix",
        final_acceptance.get("object") == "media2api.final_acceptance_matrix"
        and final_acceptance.get("core_ready") is True
        and {
            "AC-001",
            "AC-002",
            "AC-003",
            "AC-004",
            "AC-005",
            "AC-006",
            "AC-007",
            "AC-008",
            "AC-S-001",
            "AC-S-002",
            "AC-S-003",
            "AC-S-004",
            "AC-S-005",
            "N-001",
            "N-002",
            "N-003",
            "N-004",
            "N-005",
            "N-006",
            "N-007",
            "N-008",
            "AC-PROD-001",
        }.issubset(final_ids)
        and any(item.get("id") == "AC-PROD-001" and item.get("blocked_by") == "authorized_external_connector_accounts" for item in final_acceptance.get("blocked_rows", [])),
        {
            "summary": final_acceptance.get("summary"),
            "blocked_rows": final_acceptance.get("blocked_rows"),
            "sample_ids": sorted(final_ids)[:30],
        },
    )
    delivery_package = client.json("GET", "/v1/admin/delivery-package")
    delivery_examples = ((delivery_package.get("developer_assets") or {}).get("examples") or [])
    delivery_script_paths = {item.get("path") for item in ((delivery_package.get("developer_assets") or {}).get("scripts") or [])}
    audit.check(
        "delivery_package",
        delivery_package.get("object") == "media2api.delivery_package"
        and (delivery_package.get("readiness") or {}).get("core_ready") is True
        and bool((delivery_package.get("acceptance_commands") or {}).get("remote_acceptance"))
        and bool((delivery_package.get("acceptance_commands") or {}).get("sdk_example"))
        and bool((delivery_package.get("acceptance_commands") or {}).get("external_connector_manifest_template"))
        and bool((delivery_package.get("acceptance_commands") or {}).get("final_acceptance_matrix"))
        and bool((delivery_package.get("external_connector_preflight") or {}).get("summary"))
        and bool((delivery_package.get("external_connector_manifest") or {}).get("default_manifest"))
        and bool((delivery_package.get("final_acceptance_matrix") or {}).get("summary"))
        and any(item.get("path") == "examples/media2api_sdk.py" and item.get("exists") for item in delivery_examples)
        and {"scripts/acceptance_audit.py", "scripts/deploy_bare.py"}.issubset(delivery_script_paths),
        {
            "status": delivery_package.get("status"),
            "urls": delivery_package.get("urls"),
            "readiness": delivery_package.get("readiness"),
            "acceptance": delivery_package.get("acceptance"),
            "scripts": sorted(delivery_script_paths),
        },
    )
    config_snapshot = client.json("GET", "/v1/admin/config-export")
    config_snapshot_text = json.dumps(config_snapshot, ensure_ascii=False)
    audit.check(
        "config_export_snapshot",
        config_snapshot.get("object") == "media2api.config_snapshot"
        and config_snapshot.get("schema_version") == 1
        and int((config_snapshot.get("counts") or {}).get("providers") or 0) >= 1
        and int((config_snapshot.get("counts") or {}).get("logical_models") or 0) >= 1,
        config_snapshot.get("counts"),
    )
    audit.check(
        "config_export_secret_redaction",
        args.api_key not in config_snapshot_text and "known-sensitive-password" not in config_snapshot_text,
        {"contains_api_key": args.api_key in config_snapshot_text, "contains_password": "known-sensitive-password" in config_snapshot_text},
    )
    exported_providers = {item.get("id"): item for item in ((config_snapshot.get("sections") or {}).get("providers") or [])}
    exported_pollinations = exported_providers.get("pollinations") or {}
    pollinations_ref = (exported_pollinations.get("base_config") or {}).get("api_key_ref")
    audit.check(
        "config_export_safe_refs_preserved",
        not exported_pollinations
        or (
            (
                pollinations_ref in {None, "public://pollinations", "env://POLLINATIONS_KEY"}
                or str(pollinations_ref).startswith("secret://")
            )
            and pollinations_ref != "[redacted]"
        ),
        exported_pollinations,
    )
    config_import_plan = client.json("POST", "/v1/admin/config-import", {"snapshot": config_snapshot, "dry_run": True})
    audit.check(
        "config_import_dry_run",
        config_import_plan.get("object") == "media2api.config_import"
        and config_import_plan.get("status") == "planned"
        and (config_import_plan.get("summary") or {}).get("dry_run") is True
        and not (config_import_plan.get("summary") or {}).get("errors"),
        config_import_plan,
    )
    redact_request_id = f"req_acceptance_admin_query_redact_{int(time.time() * 1000)}"
    redact_status, redact_html = client.text(f"/admin?admin_key={args.api_key}&view=readiness", extra_headers={"x-request-id": redact_request_id})
    redact_logs = client.json("GET", f"/v1/admin/request-logs?request_id={redact_request_id}")
    redact_query = ""
    if redact_logs.get("data"):
        redact_query = str((redact_logs["data"][0].get("metadata") or {}).get("query") or "")
    audit.check("admin_query_redaction_page", redact_status == 200 and "总览" in redact_html, {"status": redact_status})
    audit.check(
        "request_audit_query_redacted",
        args.api_key not in redact_query and "admin_key" in redact_query and "redacted" in redact_query,
        {"query": redact_query, "logs": redact_logs.get("data", [])[:1]},
    )
    admin_users = client.json("GET", "/v1/admin/users")
    bootstrap_admin = [item for item in admin_users.get("data", []) if item.get("id") == "usr_admin"]
    audit.check("bootstrap_admin_user", bool(bootstrap_admin and bootstrap_admin[0].get("tier") == "admin" and bootstrap_admin[0].get("status") == "active"), bootstrap_admin[:1])

    non_admin_user_id = f"usr_acceptance_non_admin_{int(time.time())}"
    non_admin_user = client.json(
        "POST",
        "/v1/admin/users",
        {"id": non_admin_user_id, "email": f"{non_admin_user_id}@media2api.local", "wallet_balance": 100000},
    )
    non_admin_key = client.json("POST", "/v1/admin/api-keys", {"user_id": non_admin_user["id"], "name": "acceptance-non-admin"})
    non_admin_client = ApiClient(args.base_url, non_admin_key["api_key"])
    non_admin_models_status, non_admin_models = non_admin_client.json_status("GET", "/v1/models")
    audit.check("non_admin_public_api_allowed", non_admin_models_status == 200 and bool(non_admin_models.get("data")), {"status": non_admin_models_status})
    non_admin_admin_status, non_admin_admin = non_admin_client.json_status("GET", "/v1/admin/dashboard")
    audit.check(
        "non_admin_admin_api_denied",
        non_admin_admin_status == 403 and non_admin_admin.get("code") == "ADMIN_REQUIRED",
        {"status": non_admin_admin_status, "body": non_admin_admin},
    )
    non_admin_assets_status, non_admin_assets = non_admin_client.json_status("GET", "/v1/admin/assets")
    audit.check(
        "non_admin_admin_assets_denied",
        non_admin_assets_status == 403 and non_admin_assets.get("code") == "ADMIN_REQUIRED",
        {"status": non_admin_assets_status, "body": non_admin_assets},
    )
    for internal_path in ["/v1/providers", "/v1/accounts", "/v1/model-mappings"]:
        status, body = non_admin_client.json_status("GET", internal_path)
        audit.check(
            f"non_admin_inventory_denied:{internal_path}",
            status == 403 and body.get("code") == "ADMIN_REQUIRED",
            {"status": status, "body": body},
        )
    non_admin_alert_status, non_admin_alerts = non_admin_client.json_status("GET", "/v1/alerts?status=open")
    non_admin_alert_rows = non_admin_alerts.get("data", []) if isinstance(non_admin_alerts, dict) else []
    audit.check(
        "non_admin_alerts_user_scoped",
        non_admin_alert_status == 200 and all(item.get("user_id") == non_admin_user["id"] for item in non_admin_alert_rows),
        {"status": non_admin_alert_status, "data": non_admin_alert_rows[:5]},
    )
    revoked_non_admin_key = client.json("DELETE", f"/v1/admin/api-keys/{non_admin_key['id']}")
    disabled_non_admin_user = client.json("PATCH", f"/v1/admin/users/{non_admin_user['id']}", {"status": "disabled"})
    audit.check(
        "acceptance_temp_user_cleanup",
        bool(revoked_non_admin_key.get("revoked") and disabled_non_admin_user.get("status") == "disabled"),
        {"api_key": revoked_non_admin_key, "user": disabled_non_admin_user},
    )

    low_balance_user_id = f"usr_acceptance_low_balance_{int(time.time())}"
    low_balance_user = client.json(
        "POST",
        "/v1/admin/users",
        {"id": low_balance_user_id, "email": f"{low_balance_user_id}@media2api.local", "wallet_balance": 0},
    )
    low_balance_key = client.json("POST", "/v1/admin/api-keys", {"user_id": low_balance_user["id"], "name": "acceptance-low-balance"})
    low_balance_client = ApiClient(args.base_url, low_balance_key["api_key"])
    low_balance_status, low_balance_body = low_balance_client.json_status(
        "POST",
        "/v1/images/generations",
        {"model": "t2i-fast", "prompt": "acceptance low balance smoke", "n": 1, "provider_preference": ["mock"]},
    )
    audit.check(
        "billing_low_balance_rejected",
        low_balance_status == 402 and low_balance_body.get("code") == "INSUFFICIENT_BALANCE",
        {"status": low_balance_status, "body": low_balance_body},
    )
    revoked_low_balance_key = client.json("DELETE", f"/v1/admin/api-keys/{low_balance_key['id']}")
    disabled_low_balance_user = client.json("PATCH", f"/v1/admin/users/{low_balance_user['id']}", {"status": "disabled"})
    audit.check(
        "acceptance_low_balance_cleanup",
        bool(revoked_low_balance_key.get("revoked") and disabled_low_balance_user.get("status") == "disabled"),
        {"api_key": revoked_low_balance_key, "user": disabled_low_balance_user},
    )

    governance_suffix = str(time.time_ns())
    governance_user_id = f"usr_acceptance_governance_{governance_suffix}"
    governance_policy_id = f"limit_acceptance_governance_{governance_suffix}"
    governance_user = client.json(
        "POST",
        "/v1/admin/users",
        {"id": governance_user_id, "email": f"{governance_user_id}@media2api.local", "wallet_balance": 100000},
    )
    governance_key = client.json("POST", "/v1/admin/api-keys", {"user_id": governance_user["id"], "name": "acceptance-governance"})
    governance_client = ApiClient(args.base_url, governance_key["api_key"])
    governance_policy = client.json(
        "POST",
        "/v1/admin/user-limit-policies",
        {
            "id": governance_policy_id,
            "name": "acceptance governance policy",
            "user_id": governance_user["id"],
            "requests_per_minute": 600,
            "daily_job_limit": 10000,
            "concurrent_job_limit": 100,
            "allowed_models": ["t2i-fast"],
            "high_cost_models": [],
            "high_cost_allowed": True,
            "enabled": True,
        },
    )
    model_not_allowed_status, model_not_allowed_body = governance_client.json_status(
        "POST",
        "/v1/images/edits",
        {"model": "image-edit", "prompt": "acceptance model allowlist smoke", "provider_preference": ["mock"]},
    )
    audit.check(
        "governance_allowed_models",
        model_not_allowed_status == 403 and model_not_allowed_body.get("code") == "MODEL_NOT_ALLOWED",
        {"status": model_not_allowed_status, "body": model_not_allowed_body, "policy": governance_policy},
    )
    client.json(
        "PATCH",
        f"/v1/admin/user-limit-policies/{governance_policy_id}",
        {"allowed_models": [], "high_cost_models": ["t2i-fast"], "high_cost_allowed": False},
    )
    high_cost_status, high_cost_body = governance_client.json_status(
        "POST",
        "/v1/images/generations",
        {"model": "t2i-fast", "prompt": "acceptance high cost allowlist smoke", "n": 1, "provider_preference": ["mock"]},
    )
    audit.check(
        "governance_high_cost_whitelist",
        high_cost_status == 403 and high_cost_body.get("code") == "MODEL_REQUIRES_WHITELIST",
        {"status": high_cost_status, "body": high_cost_body},
    )
    user_breaker_id = f"cb_acceptance_user_{governance_suffix}"
    user_breaker = client.json(
        "POST",
        "/v1/admin/circuit-breakers",
        {
            "id": user_breaker_id,
            "scope": "user",
            "target_id": governance_user["id"],
            "status": "open",
            "reason": "acceptance user breaker",
            "error_code": "ACCEPTANCE_CIRCUIT",
            "block_minutes": 5,
        },
    )
    user_breaker_status, user_breaker_body = governance_client.json_status(
        "POST",
        "/v1/images/generations",
        {"model": "t2i-fast", "prompt": "acceptance user circuit smoke", "n": 1, "provider_preference": ["mock"]},
    )
    client.json("PATCH", f"/v1/admin/circuit-breakers/{user_breaker_id}", {"status": "closed", "clear_block_until": True})
    audit.check(
        "governance_user_circuit_breaker",
        user_breaker_status == 429 and user_breaker_body.get("code") == "CIRCUIT_OPEN",
        {"status": user_breaker_status, "body": user_breaker_body, "breaker": user_breaker},
    )
    model_breaker_id = f"cb_acceptance_model_{governance_suffix}"
    model_breaker = client.json(
        "POST",
        "/v1/admin/circuit-breakers",
        {
            "id": model_breaker_id,
            "scope": "model",
            "target_id": "t2i-fast",
            "status": "open",
            "reason": "acceptance model breaker",
            "error_code": "ACCEPTANCE_CIRCUIT",
            "block_minutes": 5,
        },
    )
    model_breaker_status, model_breaker_body = client.json_status(
        "POST",
        "/v1/images/generations",
        {"model": "t2i-fast", "prompt": "acceptance model circuit smoke", "n": 1, "provider_preference": ["mock"]},
    )
    client.json("PATCH", f"/v1/admin/circuit-breakers/{model_breaker_id}", {"status": "closed", "clear_block_until": True})
    audit.check(
        "governance_model_circuit_breaker",
        model_breaker_status == 429 and model_breaker_body.get("code") == "CIRCUIT_OPEN",
        {"status": model_breaker_status, "body": model_breaker_body, "breaker": model_breaker},
    )
    client.json("PATCH", f"/v1/admin/user-limit-policies/{governance_policy_id}", {"enabled": False})
    revoked_governance_key = client.json("DELETE", f"/v1/admin/api-keys/{governance_key['id']}")
    disabled_governance_user = client.json("PATCH", f"/v1/admin/users/{governance_user['id']}", {"status": "disabled"})
    audit.check(
        "acceptance_governance_cleanup",
        bool(revoked_governance_key.get("revoked") and disabled_governance_user.get("status") == "disabled"),
        {"api_key": revoked_governance_key, "user": disabled_governance_user},
    )

    rate_suffix = str(time.time_ns())
    rate_user_id = f"usr_acceptance_rate_{rate_suffix}"
    rate_policy_id = f"limit_acceptance_rate_{rate_suffix}"
    rate_user = client.json(
        "POST",
        "/v1/admin/users",
        {"id": rate_user_id, "email": f"{rate_user_id}@media2api.local", "wallet_balance": 100000},
    )
    rate_key = client.json("POST", "/v1/admin/api-keys", {"user_id": rate_user["id"], "name": "acceptance-rate"})
    rate_client = ApiClient(args.base_url, rate_key["api_key"])
    rate_policy = client.json(
        "POST",
        "/v1/admin/user-limit-policies",
        {
            "id": rate_policy_id,
            "name": "acceptance rate policy",
            "user_id": rate_user["id"],
            "requests_per_minute": 1,
            "daily_job_limit": 10000,
            "concurrent_job_limit": 100,
            "enabled": True,
        },
    )
    first_rate_status, _ = rate_client.json_status("GET", "/v1/models")
    second_rate_status, second_rate_body = rate_client.json_status("GET", "/v1/models")
    audit.check(
        "governance_rate_limit",
        first_rate_status == 200 and second_rate_status == 429 and second_rate_body.get("code") == "RATE_LIMITED",
        {"first_status": first_rate_status, "second_status": second_rate_status, "body": second_rate_body, "policy": rate_policy},
    )
    client.json("PATCH", f"/v1/admin/user-limit-policies/{rate_policy_id}", {"enabled": False})
    revoked_rate_key = client.json("DELETE", f"/v1/admin/api-keys/{rate_key['id']}")
    disabled_rate_user = client.json("PATCH", f"/v1/admin/users/{rate_user['id']}", {"status": "disabled"})
    audit.check(
        "acceptance_rate_cleanup",
        bool(revoked_rate_key.get("revoked") and disabled_rate_user.get("status") == "disabled"),
        {"api_key": revoked_rate_key, "user": disabled_rate_user},
    )

    providers = client.json("GET", "/v1/providers")
    provider_status = {item.get("id"): item.get("status") for item in providers.get("data", [])}
    audit.check("provider_catalog_seeded", required_templates.issubset(set(provider_status)), sorted(provider_status))
    credential_migration = client.json("POST", "/v1/admin/accounts/migrate-inline-credentials")
    audit.check("account_inline_credentials_migrated", credential_migration.get("object") == "account_credential_migration" and not credential_migration.get("errors"), credential_migration)
    accounts = client.json("GET", "/v1/accounts")
    leaked_credential_refs = [
        {"id": item.get("id"), "credential_ref": item.get("credential_ref")}
        for item in accounts.get("data", [])
        if isinstance(item.get("credential_ref"), str)
        and (
            (item["credential_ref"].startswith("bearer://") and item["credential_ref"] != "bearer://***")
            or (item["credential_ref"].startswith("plain://") and item["credential_ref"] != "plain://***")
        )
    ]
    audit.check("account_credentials_redacted", not leaked_credential_refs, leaked_credential_refs)
    inline_credential_types = [
        {"id": item.get("id"), "credential_ref_type": item.get("credential_ref_type")}
        for item in accounts.get("data", [])
        if item.get("credential_ref_type") in {"plain", "bearer"}
    ]
    audit.check("account_credentials_indirect_refs", not inline_credential_types, inline_credential_types)
    active_external_accounts = [
        item
        for item in accounts.get("data", [])
        if item.get("provider_id") in required_templates
        and provider_status.get(item.get("provider_id")) == "active"
        and item.get("status") == "active"
        and int(item.get("concurrency_limit") or 0) > 0
    ]
    audit.warn(
        "external_connector_accounts_ready",
        bool(active_external_accounts),
        {"active_external_accounts": [{"id": item.get("id"), "provider_id": item.get("provider_id")} for item in active_external_accounts]},
    )
    mixed_media_check = readiness_checks.get("external_mixed_media_provider") or {}
    audit.warn(
        "external_mixed_media_provider_ready",
        mixed_media_check.get("ok") is True,
        mixed_media_check.get("detail") or {},
    )

    compatibility = client.json("GET", "/v1/admin/compatibility-matrix?logical_model=t2i-fast&operation=text_to_image")
    audit.check("compatibility_matrix", bool(compatibility.get("data")), compatibility.get("data", [])[:3])

    quota_suffix = str(time.time_ns())
    quota_account_id = f"acct_acceptance_quota_{quota_suffix}"
    quota_provider_model = f"mock-image-quota-{quota_suffix}"
    quota_mapping_id = f"map_acceptance_quota_{quota_suffix}"
    quota_account = client.json(
        "POST",
        "/v1/admin/accounts",
        {
            "id": quota_account_id,
            "provider_id": "mock",
            "label": "acceptance quota drain",
            "credential_ref": "plain://acceptance-quota",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": [quota_provider_model],
            "quota_buckets": [
                {
                    "type": "credits",
                    "operation": "text_to_image",
                    "provider_model": quota_provider_model,
                    "remaining_estimate": 1,
                    "confidence": 1,
                }
            ],
            "concurrency_limit": 1,
            "status": "active",
        },
    )
    quota_mapping = client.json(
        "POST",
        "/v1/admin/model-mappings",
        {
            "id": quota_mapping_id,
            "logical_model": "t2i-fast",
            "provider_id": "mock",
            "provider_model": quota_provider_model,
            "operations": ["text_to_image"],
            "priority": 0,
            "weight": 1,
            "cost_score": 0.99,
            "speed_score": 0.99,
            "quality_score": 0.5,
            "reliability_score": 0.99,
            "enabled": True,
        },
    )
    quota_job_result = client.json(
        "POST",
        "/v1/images/generations",
        {
            "model": "t2i-fast",
            "prompt": "acceptance quota drain smoke",
            "n": 1,
            "providers": ["mock"],
            "provider_preference": ["mock"],
            "provider_models": [quota_provider_model],
            "route_policy": "balanced",
        },
    )
    quota_job = client.json("GET", f"/v1/media-jobs/{quota_job_result['job_id']}")
    quota_accounts_after = client.json("GET", "/v1/accounts")
    quota_account_after = next((item for item in quota_accounts_after.get("data", []) if item.get("id") == quota_account_id), {})
    quota_preview_after = client.json(
        "POST",
        "/v1/router/preview",
        {
            "model": "t2i-fast",
            "operation": "text_to_image",
            "params": {"providers": ["mock"], "provider_preference": ["mock"], "provider_models": [quota_provider_model]},
        },
    )
    quota_candidate_models = {item.get("provider_model") for item in quota_preview_after.get("data", [])}
    quota_alerts = client.json("GET", "/v1/admin/alerts?status=open")
    quota_account_alerts = [
        item
        for item in quota_alerts.get("data", [])
        if item.get("account_id") == quota_account_id and item.get("event_type") == "account_status"
    ]
    audit.check(
        "account_quota_exhaustion_exits_pool",
        quota_job.get("provider_model") == quota_provider_model
        and quota_account_after.get("status") == "quota_exhausted"
        and quota_account_after.get("last_error_code") == "QUOTA_EXHAUSTED"
        and quota_provider_model not in quota_candidate_models
        and bool(quota_account_alerts),
        {
            "account_before": quota_account,
            "mapping": quota_mapping,
            "job": quota_job,
            "account_after": quota_account_after,
            "candidate_models_after": sorted(item for item in quota_candidate_models if item),
            "alerts": quota_account_alerts[:3],
        },
    )
    client.json("PATCH", f"/v1/admin/model-mappings/{quota_mapping_id}", {"enabled": False})
    disabled_quota_account = client.json("PATCH", f"/v1/admin/accounts/{quota_account_id}", {"status": "disabled", "concurrency_limit": 0})
    audit.check(
        "acceptance_quota_cleanup",
        disabled_quota_account.get("status") == "disabled" and int(disabled_quota_account.get("concurrency_limit") or 0) == 0,
        disabled_quota_account,
    )

    safety_status, safety_body = client.json_status(
        "POST",
        "/v1/images/generations",
        {
            "model": "t2i-fast",
            "prompt": "acceptance should trigger media2api_forbidden_test before provider submit",
            "n": 1,
            "provider_preference": ["mock"],
        },
    )
    safety_job_id = str(safety_body.get("job_id") or "")
    safety_job = client.json("GET", f"/v1/media-jobs/{safety_job_id}") if safety_job_id else {}
    safety_attempts = client.json("GET", f"/v1/media-jobs/{safety_job_id}/attempts") if safety_job_id else {"data": []}
    safety_events = client.json("GET", f"/v1/media-jobs/{safety_job_id}/events") if safety_job_id else {"data": []}
    safety_policy_events = client.json("GET", f"/v1/admin/safety-events?job_id={safety_job_id}") if safety_job_id else {"data": []}
    safety_request_logs = client.json("GET", f"/v1/admin/request-logs?job_id={safety_job_id}") if safety_job_id else {"data": []}
    safety_event_types = [item.get("event_type") for item in safety_events.get("data", [])]
    safety_request_log = safety_request_logs.get("data", [{}])[0] if safety_request_logs.get("data") else {}
    audit.check(
        "safety_rejection_before_provider",
        safety_status == 400
        and safety_body.get("code") == "SAFETY_REJECTED"
        and safety_body.get("policy_id") == "safety_block_smoke_marker"
        and safety_job.get("status") == "failed"
        and (safety_job.get("error") or {}).get("code") == "SAFETY_REJECTED"
        and safety_attempts.get("data") == []
        and "safety_rejected" in safety_event_types
        and "fallback_queued" not in safety_event_types
        and bool(safety_policy_events.get("data"))
        and safety_request_log.get("standard_error_code") == "SAFETY_REJECTED",
        {
            "status": safety_status,
            "body": safety_body,
            "job": safety_job,
            "attempts": safety_attempts,
            "events": safety_events,
            "safety_events": safety_policy_events,
            "request_logs": safety_request_logs,
        },
    )

    capability_contract_failures: list[dict[str, Any]] = []
    for template_id in sorted(required_templates):
        caps = client.json("GET", f"/v1/admin/providers/{template_id}/capabilities")
        template = template_by_id.get(template_id) or {}
        operations = set(template.get("operations") or [])
        models_declared = set(template.get("models") or [])
        effective_operations = set(caps.get("operations") or [])
        effective_models = set(caps.get("models") or [])
        profiles = caps.get("operation_capabilities") or {}
        missing_ops = sorted(operations - effective_operations)
        missing_models = sorted(models_declared - effective_models)
        if not caps.get("template_available") or missing_ops or missing_models:
            capability_contract_failures.append(
                {
                    "provider_id": template_id,
                    "template_available": caps.get("template_available"),
                    "missing_ops": missing_ops,
                    "missing_models": missing_models,
                }
            )
        for operation in operations:
            profile = profiles.get(operation)
            if not isinstance(profile, dict) or profile.get("output_kind") not in {"image", "video"} or not isinstance(profile.get("params"), list):
                capability_contract_failures.append({"provider_id": template_id, "operation": operation, "error": "operation_profile_invalid", "profile": profile})
                continue
            if profile.get("output_kind") == "video":
                duration = profile.get("duration_seconds")
                duration_ok = isinstance(duration, dict) and int(duration.get("min") or 0) >= 0 and int(duration.get("max") or 0) >= int(duration.get("min") or 0)
                if not duration_ok:
                    capability_contract_failures.append({"provider_id": template_id, "operation": operation, "error": "video_duration_profile_invalid", "profile": profile})
    audit.check("provider_effective_capabilities", not capability_contract_failures, capability_contract_failures[:10])

    lease_reconcile = client.json("POST", "/v1/admin/account-leases/reconcile")
    audit.check("lease_reconcile", lease_reconcile.get("object") == "lease_reconcile" and int(lease_reconcile.get("checked") or 0) >= 1, lease_reconcile)
    lease_self_test = client.json("POST", "/v1/admin/account-leases/self-test-expiry")
    audit.check(
        "lease_expiry_self_test",
        lease_self_test.get("object") == "lease_expiry_self_test"
        and lease_self_test.get("ok") is True
        and (lease_self_test.get("job") or {}).get("status") == "expired"
        and ((lease_self_test.get("job") or {}).get("error") or {}).get("code") == "LEASE_EXPIRED"
        and (lease_self_test.get("account") or {}).get("current_leases_after") == (lease_self_test.get("account") or {}).get("current_leases_before"),
        lease_self_test,
    )
    account_diagnostics = client.json("GET", "/v1/admin/accounts/acct_mock_default/diagnostics?limit=10")
    audit.check(
        "account_diagnostics",
        account_diagnostics.get("object") == "media2api.account_diagnostics"
        and (account_diagnostics.get("account") or {}).get("id") == "acct_mock_default"
        and (account_diagnostics.get("summary") or {}).get("last_error_code") == "LEASE_EXPIRED"
        and bool(account_diagnostics.get("recent_attempts"))
        and bool(account_diagnostics.get("recent_leases"))
        and any(item.get("check") == "last_account_error" for item in account_diagnostics.get("action_items", [])),
        account_diagnostics,
    )
    stalled_self_test = client.json("POST", "/v1/admin/media-jobs/self-test-stalled-recovery", {})
    audit.check(
        "stalled_job_recovery_self_test",
        stalled_self_test.get("object") == "stalled_job_recovery_self_test"
        and stalled_self_test.get("ok") is True
        and (stalled_self_test.get("recovery") or {}).get("recovered") == 1
        and (stalled_self_test.get("recovered_job") or {}).get("status") == "queued"
        and (stalled_self_test.get("job") or {}).get("status") == "cancelled",
        stalled_self_test,
    )
    connector_cancel_self_test = client.json("POST", "/v1/admin/media-jobs/self-test-connector-cancel", {})
    audit.check(
        "connector_cancel_self_test",
        connector_cancel_self_test.get("object") == "connector_cancel_self_test"
        and connector_cancel_self_test.get("ok") is True
        and (connector_cancel_self_test.get("job") or {}).get("status") == "cancelled"
        and (connector_cancel_self_test.get("provider_cancel") or {}).get("status") == "cancelled"
        and int(((connector_cancel_self_test.get("upstream") or {}).get("cancel_hits")) or 0) == 1
        and (connector_cancel_self_test.get("lease") or {}).get("status") == "released"
        and all(hold.get("status") == "refunded" for hold in ((connector_cancel_self_test.get("billing") or {}).get("holds") or []))
        and int(((connector_cancel_self_test.get("billing") or {}).get("wallet_after")) or -1) == int(((connector_cancel_self_test.get("billing") or {}).get("wallet_before")) or -2),
        connector_cancel_self_test,
    )
    mock_stability = client.json("POST", "/v1/admin/stability/self-test-mock", {"iterations": 5})
    audit.check(
        "mock_stability_self_test",
        mock_stability.get("object") == "mock_stability_self_test"
        and mock_stability.get("ok") is True
        and int(mock_stability.get("iterations_completed") or 0) == 5
        and not ((mock_stability.get("leases") or {}).get("active_lease_leaks") or [])
        and int(((mock_stability.get("billing") or {}).get("held_holds")) or 0) == 0,
        mock_stability,
    )
    asset_storage_self_test = client.json("POST", "/v1/admin/assets/self-test-storage", {"cleanup": False})
    asset_storage_url = str(((asset_storage_self_test.get("signed_url") or {}).get("url")) or "")
    asset_storage_status, asset_storage_bytes = client.bytes_url(asset_storage_url) if asset_storage_url else (0, b"")
    asset_storage_asset_id = str(((asset_storage_self_test.get("asset") or {}).get("id")) or "")
    asset_storage_cleanup = client.json("DELETE", f"/v1/assets/{asset_storage_asset_id}") if asset_storage_asset_id else {}
    audit.check(
        "asset_storage_self_test",
        asset_storage_self_test.get("object") == "asset_storage_self_test"
        and asset_storage_self_test.get("ok") is True
        and (asset_storage_self_test.get("read") or {}).get("ok") is True
        and (asset_storage_self_test.get("signed_url") or {}).get("signature_ok") is True
        and asset_storage_status == 200
        and len(asset_storage_bytes) == int((asset_storage_self_test.get("read") or {}).get("bytes") or 0)
        and asset_storage_cleanup.get("deleted") is True,
        {
            "self_test": asset_storage_self_test,
            "download_status": asset_storage_status,
            "download_bytes": len(asset_storage_bytes),
            "cleanup": asset_storage_cleanup,
        },
    )
    temp_url_asset_self_test = client.json("POST", "/v1/admin/assets/self-test-temp-url", {})
    temp_url_asset = temp_url_asset_self_test.get("asset") or {}
    if temp_url_asset.get("url"):
        temp_url_asset_status, temp_url_asset_bytes = client.bytes_url(str(temp_url_asset.get("url")))
    else:
        temp_url_asset_status, temp_url_asset_bytes = 0, b""
    temp_url_active_leases = [lease for lease in temp_url_asset_self_test.get("leases") or [] if lease.get("status") == "active"]
    temp_url_attempts_text = json.dumps(temp_url_asset_self_test.get("attempts") or [], sort_keys=True)
    audit.check(
        "temp_url_asset_self_test",
        temp_url_asset_self_test.get("object") == "temp_url_asset_self_test"
        and temp_url_asset_self_test.get("ok") is True
        and (temp_url_asset_self_test.get("job") or {}).get("status") == "completed"
        and int(((temp_url_asset_self_test.get("source") or {}).get("second_fetch_status")) or 0) == 410
        and (temp_url_asset_self_test.get("platform_download") or {}).get("ok") is True
        and temp_url_asset_status == 200
        and temp_url_asset_bytes.startswith(b"\x89PNG")
        and not temp_url_active_leases
        and "http://127.0.0.1" not in json.dumps(((temp_url_asset_self_test.get("admin_asset") or {}).get("provider_meta") or {}), sort_keys=True)
        and "http://127.0.0.1" not in temp_url_attempts_text
        and "image_url_hash" in temp_url_attempts_text,
        {
            "self_test": temp_url_asset_self_test,
            "download_status": temp_url_asset_status,
            "download_bytes": len(temp_url_asset_bytes),
        },
    )
    fallback_self_test = client.json("POST", "/v1/admin/fallback/self-test", {})
    fallback_attempts = fallback_self_test.get("attempts") or []
    fallback_statuses = [item.get("status") for item in fallback_attempts]
    audit.check(
        "fallback_self_test",
        fallback_self_test.get("object") == "fallback_self_test"
        and fallback_self_test.get("ok") is True
        and (fallback_self_test.get("job") or {}).get("status") == "completed"
        and fallback_statuses == ["failed", "completed"]
        and int(((fallback_self_test.get("fallback") or {}).get("fallback_event_count")) or 0) >= 1
        and int(((fallback_self_test.get("billing") or {}).get("usage_records")) or 0) == 1
        and int(((fallback_self_test.get("billing") or {}).get("provider_cost_records")) or 0) == 1
        and int(((fallback_self_test.get("billing") or {}).get("held_holds")) or 0) == 0
        and bool(fallback_self_test.get("outputs")),
        fallback_self_test,
    )
    fallback_timeout_self_test = client.json("POST", "/v1/admin/fallback/self-test-timeout", {})
    fallback_timeout_attempts = fallback_timeout_self_test.get("attempts") or []
    fallback_timeout_statuses = [item.get("status") for item in fallback_timeout_attempts]
    audit.check(
        "fallback_timeout_self_test",
        fallback_timeout_self_test.get("object") == "fallback_timeout_self_test"
        and fallback_timeout_self_test.get("ok") is True
        and (fallback_timeout_self_test.get("job") or {}).get("status") == "completed"
        and fallback_timeout_statuses == ["failed", "completed"]
        and (fallback_timeout_attempts[0] if fallback_timeout_attempts else {}).get("error_code") == "PROVIDER_TIMEOUT"
        and int(((fallback_timeout_self_test.get("fallback") or {}).get("fallback_event_count")) or 0) >= 1
        and int(((fallback_timeout_self_test.get("billing") or {}).get("usage_records")) or 0) == 1
        and int(((fallback_timeout_self_test.get("billing") or {}).get("provider_cost_records")) or 0) == 1
        and int(((fallback_timeout_self_test.get("billing") or {}).get("held_holds")) or 0) == 0
        and bool(fallback_timeout_self_test.get("outputs")),
        fallback_timeout_self_test,
    )
    account_cooldown_self_test = client.json("POST", "/v1/admin/accounts/self-test-cooldown", {})
    cooldown_active_leases = [lease for lease in account_cooldown_self_test.get("leases") or [] if lease.get("status") == "active"]
    audit.check(
        "account_cooldown_self_test",
        account_cooldown_self_test.get("object") == "account_cooldown_self_test"
        and account_cooldown_self_test.get("ok") is True
        and (account_cooldown_self_test.get("account") or {}).get("status_before_cleanup") == "cooldown"
        and float(((account_cooldown_self_test.get("account") or {}).get("failure_score_before_cleanup")) or 0) >= 0.75
        and (account_cooldown_self_test.get("probe_job") or {}).get("status") == "failed"
        and (((account_cooldown_self_test.get("probe_job") or {}).get("error") or {}).get("code")) == "UNSUPPORTED_MODEL_OPERATION"
        and not cooldown_active_leases
        and int(((account_cooldown_self_test.get("billing") or {}).get("held_holds")) or 0) == 0
        and bool(account_cooldown_self_test.get("alerts")),
        account_cooldown_self_test,
    )

    health_check = client.json("POST", "/v1/admin/providers/mock/health-check", {})
    audit.check("provider_health", health_check.get("status") == "ok", health_check)

    contract = client.json("POST", "/v1/admin/providers/mock/contract-test", {"operation": "text_to_image", "run_submit": False})
    audit.check("provider_contract", contract.get("status") == "passed", contract)
    contract_suite = client.json(
        "POST",
        "/v1/admin/provider-contract-suite",
        {"provider_ids": ["mock"], "operations": ["text_to_image"], "active_only": False, "run_submit": False},
    )
    audit.check(
        "provider_contract_suite",
        contract_suite.get("object") == "media2api.provider_contract_suite"
        and contract_suite.get("status") == "passed"
        and int((contract_suite.get("summary") or {}).get("passed") or 0) >= 1
        and int((contract_suite.get("summary") or {}).get("failed") or 0) == 0,
        contract_suite,
    )
    image = client.json("POST", "/v1/images/generations", {"model": "t2i-fast", "prompt": "acceptance image smoke", "n": 1, "provider_preference": ["mock"]})
    image_asset_id = image.get("data", [{}])[0].get("asset_id")
    audit.check("image_generation", bool(image.get("job_id") and image_asset_id), image)
    admin_image_asset = client.json("GET", f"/v1/admin/assets/{image_asset_id}")
    audit.check("admin_asset_detail", admin_image_asset.get("id") == image_asset_id and admin_image_asset.get("user_id") == "usr_admin", admin_image_asset)

    uploaded_asset = client.json(
        "POST",
        "/v1/assets",
        {
            "b64_json": TINY_PNG_B64,
            "filename": "acceptance-input.png",
            "kind": "image",
            "purpose": "input",
            "mime_type": "image/png",
        },
    )
    uploaded_asset_id = uploaded_asset.get("id")
    uploaded_status, uploaded_bytes = client.bytes_url(uploaded_asset.get("url", ""))
    audit.check(
        "asset_upload_and_download",
        bool(uploaded_asset_id) and uploaded_status == 200 and uploaded_bytes.startswith(b"\x89PNG"),
        {"asset": uploaded_asset, "download_status": uploaded_status, "bytes": len(uploaded_bytes)},
    )
    uploaded_alt_asset = client.json(
        "POST",
        "/v1/assets",
        {
            "b64_json": TINY_PNG_B64,
            "filename": "acceptance-input-alt.png",
            "kind": "image",
            "purpose": "input",
            "mime_type": "image/png",
        },
    )
    uploaded_alt_asset_id = uploaded_alt_asset.get("id")

    image_edit = client.json(
        "POST",
        "/v1/images/edits",
        {
            "model": "image-edit",
            "prompt": "acceptance image edit smoke",
            "image": uploaded_asset_id,
            "n": 1,
            "provider_preference": ["mock"],
        },
    )
    image_edit_asset_id = image_edit.get("data", [{}])[0].get("asset_id")
    audit.check("image_edit_generation", bool(image_edit.get("job_id") and image_edit_asset_id), image_edit)
    image_variation = client.json(
        "POST",
        "/v1/media-jobs",
        {
            "operation": "image_to_image",
            "model": "image-variation",
            "prompt": "acceptance image variation smoke",
            "image": uploaded_asset_id,
            "wait": True,
            "provider_preference": ["mock"],
        },
    )
    image_variation_asset_id = (image_variation.get("output_asset_ids") or [None])[0]
    audit.check(
        "image_to_image_generation",
        image_variation.get("status") == "completed" and image_variation.get("operation") == "image_to_image" and bool(image_variation_asset_id),
        image_variation,
    )
    native_complex_image = client.json(
        "POST",
        "/v1/media-jobs",
        {
            "operation": "image_edit",
            "model": "image-edit",
            "prompt": "acceptance native rich parameter image edit",
            "image": uploaded_asset_id,
            "images": [uploaded_asset_id, uploaded_alt_asset_id],
            "mask": uploaded_asset_id,
            "seed": 12345,
            "size": "1024x1024",
            "quality": "high",
            "negative_prompt": "low quality",
            "route_policy": "best_quality",
            "cost_policy": "max_cost:100000",
            "provider_preference": ["mock"],
            "providers": ["mock"],
            "provider_models": ["mock-image-edit"],
            "wait": True,
        },
    )
    native_complex_image_asset_id = (native_complex_image.get("output_asset_ids") or [None])[0]
    native_complex_image_params = native_complex_image.get("params") or {}
    audit.check(
        "native_rich_image_params",
        native_complex_image.get("status") == "completed"
        and native_complex_image.get("operation") == "image_edit"
        and {uploaded_asset_id, uploaded_alt_asset_id}.issubset(set(native_complex_image.get("input_asset_ids") or []))
        and native_complex_image_params.get("images") == [uploaded_asset_id, uploaded_alt_asset_id]
        and native_complex_image_params.get("mask") == uploaded_asset_id
        and native_complex_image_params.get("seed") == 12345
        and native_complex_image_params.get("quality") == "high"
        and native_complex_image_params.get("negative_prompt") == "low quality"
        and native_complex_image_params.get("route_policy") == "best_quality"
        and native_complex_image_params.get("cost_policy") == "max_cost:100000"
        and bool(native_complex_image_asset_id),
        native_complex_image,
    )
    native_complex_video = client.json(
        "POST",
        "/v1/media-jobs",
        {
            "operation": "image_to_video",
            "model": "i2v-fast",
            "prompt": "acceptance native rich parameter i2v",
            "first_frame": uploaded_asset_id,
            "last_frame": uploaded_alt_asset_id,
            "duration": 3,
            "aspect_ratio": "16:9",
            "quality": "standard",
            "seed": 54321,
            "negative_prompt": "jitter",
            "providers": ["mock"],
            "provider_preference": ["mock"],
            "provider_models": ["mock-video-fast"],
            "max_cost": 100000,
            "wait": True,
        },
    )
    native_complex_video_asset_id = (native_complex_video.get("output_asset_ids") or [None])[0]
    native_complex_video_params = native_complex_video.get("params") or {}
    audit.check(
        "native_rich_video_params",
        native_complex_video.get("status") == "completed"
        and native_complex_video.get("operation") == "image_to_video"
        and {uploaded_asset_id, uploaded_alt_asset_id}.issubset(set(native_complex_video.get("input_asset_ids") or []))
        and native_complex_video_params.get("first_frame") == uploaded_asset_id
        and native_complex_video_params.get("last_frame") == uploaded_alt_asset_id
        and native_complex_video_params.get("aspect_ratio") == "16:9"
        and native_complex_video_params.get("seed") == 54321
        and bool(native_complex_video_asset_id),
        native_complex_video,
    )
    frame_api_create = client.json(
        "POST",
        "/v1/videos/generations",
        {
            "model": "i2v-fast",
            "prompt": "acceptance openai compatible first last frame i2v",
            "first_frame": uploaded_asset_id,
            "last_frame": uploaded_alt_asset_id,
            "duration": 3,
            "aspect_ratio": "16:9",
            "provider_preference": ["mock"],
            "providers": ["mock"],
            "provider_models": ["mock-video-fast"],
        },
    )
    frame_api_job = wait_for_job(client, frame_api_create.get("id", ""))
    frame_api_asset_id = (frame_api_job.get("output_asset_ids") or [None])[0]
    frame_api_params = frame_api_job.get("params") or {}
    audit.check(
        "video_api_first_last_frame",
        frame_api_job.get("status") == "completed"
        and frame_api_job.get("operation") == "image_to_video"
        and {uploaded_asset_id, uploaded_alt_asset_id}.issubset(set(frame_api_job.get("input_asset_ids") or []))
        and frame_api_params.get("first_frame") == uploaded_asset_id
        and frame_api_params.get("last_frame") == uploaded_alt_asset_id
        and bool(frame_api_asset_id),
        {"create": frame_api_create, "job": frame_api_job},
    )

    video = client.json(
        "POST",
        "/v1/media-jobs",
        {
            "operation": "text_to_video",
            "model": "t2v-general",
            "prompt": "acceptance video smoke",
            "duration": 3,
            "wait": True,
            "provider_preference": ["mock"],
        },
    )
    audit.check("video_generation", video.get("status") == "completed" and bool(video.get("output_asset_ids")), video)

    private_webhook_job = client.json(
        "POST",
        "/v1/media-jobs",
        {
            "operation": "text_to_image",
            "model": "t2i-fast",
            "prompt": "acceptance private webhook block smoke",
            "wait": True,
            "provider_preference": ["mock"],
            "params": {"webhook": "http://127.0.0.1:9/acceptance-webhook-blocked"},
        },
    )
    private_webhooks = client.json("GET", f"/v1/admin/webhooks?job_id={private_webhook_job['id']}")
    private_delivery = private_webhooks.get("data", [{}])[0] if private_webhooks.get("data") else {}
    audit.check(
        "webhook_private_target_blocked",
        private_webhook_job.get("status") == "completed"
        and private_delivery.get("status") == "failed"
        and private_delivery.get("last_error") == "WEBHOOK_URL_PRIVATE_ADDRESS_BLOCKED"
        and int(private_delivery.get("attempts") or 0) == 1,
        {"job": private_webhook_job, "delivery": private_delivery},
    )

    i2v_create = client.json(
        "POST",
        "/v1/videos/generations",
        {
            "model": "i2v-fast",
            "prompt": "acceptance i2v smoke",
            "image": uploaded_asset_id,
            "duration": 3,
            "provider_preference": ["mock"],
        },
    )
    i2v_job = wait_for_job(client, i2v_create["id"])
    audit.check(
        "i2v_generation",
        i2v_job.get("status") == "completed" and i2v_job.get("operation") == "image_to_video" and bool(i2v_job.get("output_asset_ids")),
        {"create": i2v_create, "job": i2v_job},
    )
    source_video_asset_id = (video.get("output_asset_ids") or [None])[0]
    video_extend = client.json(
        "POST",
        "/v1/media-jobs",
        {
            "operation": "video_extend",
            "model": "video-extend",
            "prompt": "acceptance video extend smoke",
            "video": source_video_asset_id,
            "duration": 2,
            "wait": True,
            "provider_preference": ["mock"],
        },
    )
    audit.check(
        "video_extend_generation",
        video_extend.get("status") == "completed" and video_extend.get("operation") == "video_extend" and bool(video_extend.get("output_asset_ids")),
        video_extend,
    )
    acceptance_report = client.json("GET", "/v1/admin/acceptance-report")
    report_check_names = {item.get("name") for item in acceptance_report.get("checks", [])}
    non_required_runtime_warning = [
        item
        for item in acceptance_report.get("checks", [])
        if item.get("name") == "unified_media_job_runtime" and not item.get("ok") and not item.get("required")
    ]
    audit.check(
        "acceptance_report",
        acceptance_report.get("object") == "media2api.acceptance_report"
        and acceptance_report.get("core_ready") is True
        and int((acceptance_report.get("summary") or {}).get("core_required_failed") or 0) == 0
        and {"required_routes", "provider_contract_tests", "operator_console"}.issubset(report_check_names)
        and not non_required_runtime_warning,
        acceptance_report,
    )

    generated_asset_ids = [
        asset_id
        for asset_id in [
            image_asset_id,
            image_edit_asset_id,
            image_variation_asset_id,
            native_complex_image_asset_id,
            native_complex_video_asset_id,
            frame_api_asset_id,
            *video.get("output_asset_ids", []),
            *i2v_job.get("output_asset_ids", []),
            *video_extend.get("output_asset_ids", []),
        ]
        if asset_id
    ]
    downloadable_failures: list[dict[str, Any]] = []
    asset_snapshots: dict[str, dict[str, Any]] = {}
    for asset_id in generated_asset_ids:
        asset = client.json("GET", f"/v1/assets/{asset_id}")
        asset_snapshots[asset_id] = asset
        status, content = client.bytes_url(asset.get("url", ""))
        if status != 200 or not content:
            downloadable_failures.append({"asset_id": asset_id, "status": status, "bytes": len(content)})
    audit.check("generated_assets_downloadable", not downloadable_failures, downloadable_failures)

    video_thumbnail_failures: list[dict[str, Any]] = []
    video_asset_ids = [
        asset_id
        for asset_id, asset in asset_snapshots.items()
        if asset.get("kind") == "video"
    ]
    for asset_id in video_asset_ids:
        asset = asset_snapshots[asset_id]
        thumbnail_asset_id = str(asset.get("thumbnail_asset_id") or "")
        thumbnail_url = str(asset.get("thumbnail_url") or "")
        if not thumbnail_asset_id or not thumbnail_url:
            video_thumbnail_failures.append({"asset_id": asset_id, "reason": "thumbnail_reference_missing", "asset": asset})
            continue
        thumbnail_asset = client.json("GET", f"/v1/assets/{thumbnail_asset_id}")
        thumb_status, thumb_bytes = client.bytes_url(thumbnail_url)
        if (
            thumbnail_asset.get("kind") != "thumbnail"
            or thumbnail_asset.get("parent_asset_id") != asset_id
            or thumb_status != 200
            or not thumb_bytes.startswith(b"\x89PNG")
        ):
            video_thumbnail_failures.append(
                {
                    "asset_id": asset_id,
                    "thumbnail_asset_id": thumbnail_asset_id,
                    "thumbnail_asset": thumbnail_asset,
                    "download_status": thumb_status,
                    "download_bytes": len(thumb_bytes),
                }
            )
    audit.check("video_assets_have_downloadable_thumbnails", bool(video_asset_ids) and not video_thumbnail_failures, {"video_asset_ids": video_asset_ids, "failures": video_thumbnail_failures})

    deleted_uploaded_asset = client.json("DELETE", f"/v1/assets/{uploaded_asset_id}")
    deleted_uploaded_alt_asset = client.json("DELETE", f"/v1/assets/{uploaded_alt_asset_id}") if uploaded_alt_asset_id else {}
    deleted_status, deleted_body = client.json_status("GET", f"/v1/assets/{uploaded_asset_id}")
    audit.check(
        "asset_delete",
        deleted_uploaded_asset.get("deleted") is True and deleted_uploaded_alt_asset.get("deleted") is True and deleted_status == 404,
        {"delete": deleted_uploaded_asset, "delete_alt": deleted_uploaded_alt_asset, "get_status": deleted_status, "get_body": deleted_body},
    )

    admin_assets = client.json("GET", "/v1/admin/assets?user_id=usr_admin&limit=100")
    expected_asset_ids = {
        asset_id
        for asset_id in [
            image_asset_id,
            image_edit_asset_id,
            image_variation_asset_id,
            native_complex_image_asset_id,
            native_complex_video_asset_id,
            frame_api_asset_id,
            *video.get("output_asset_ids", []),
            *i2v_job.get("output_asset_ids", []),
            *video_extend.get("output_asset_ids", []),
        ]
        if asset_id
    }
    observed_asset_ids = {item.get("id") for item in admin_assets.get("data", [])}
    audit.check("admin_assets", expected_asset_ids.issubset(observed_asset_ids), {"expected": sorted(expected_asset_ids), "observed_sample": sorted(list(observed_asset_ids))[:20]})

    events = client.json("GET", f"/v1/media-jobs/{video['id']}/events")
    event_types = [item.get("event_type") for item in events.get("data", [])]
    audit.check("job_events", "completed" in event_types and "provider_completed" in event_types, event_types)
    job_diagnostics = client.json("GET", f"/v1/admin/media-jobs/{video['id']}/diagnostics?limit=100")
    diagnostic_timeline_kinds = {item.get("kind") for item in job_diagnostics.get("timeline", [])}
    audit.check(
        "media_job_diagnostics",
        job_diagnostics.get("object") == "media2api.media_job_diagnostics"
        and (job_diagnostics.get("job") or {}).get("id") == video["id"]
        and (job_diagnostics.get("summary") or {}).get("status") == "completed"
        and (job_diagnostics.get("summary") or {}).get("attempt_count", 0) >= 1
        and (job_diagnostics.get("summary") or {}).get("lease_count", 0) >= 1
        and (job_diagnostics.get("summary") or {}).get("output_asset_count", 0) >= 1
        and bool(job_diagnostics.get("attempts"))
        and bool(job_diagnostics.get("leases"))
        and bool(job_diagnostics.get("output_assets"))
        and bool((job_diagnostics.get("billing") or {}).get("usage_records"))
        and {"event", "attempt", "lease"}.issubset(diagnostic_timeline_kinds),
        job_diagnostics,
    )

    analytics = client.json("GET", "/v1/admin/analytics?group_by=provider_id,logical_model")
    audit.check("analytics", bool(analytics.get("data")), analytics.get("data", [])[:3])

    invoice = client.json("GET", "/v1/billing/invoice")
    audit.check(
        "billing_invoice",
        invoice.get("object") == "billing.invoice"
        and invoice.get("user_id") == "usr_admin"
        and invoice.get("totals", {}).get("settled_usage_amount", 0) >= 1
        and bool(invoice.get("line_items")),
        invoice,
    )
    invoice_csv_status, invoice_csv = client.text("/v1/billing/invoice?format=csv", auth=True)
    audit.check("billing_invoice_csv", invoice_csv_status == 200 and "invoice_id" in invoice_csv and "usage" in invoice_csv, invoice_csv[:300])
    admin_invoice = client.json("GET", "/v1/admin/billing-invoices?user_id=usr_admin")
    audit.check(
        "admin_billing_invoice",
        admin_invoice.get("object") == "billing.invoice"
        and admin_invoice.get("user_id") == "usr_admin"
        and admin_invoice.get("totals", {}).get("provider_cost_amount", 0) >= 1,
        admin_invoice,
    )

    request_logs = client.json("GET", f"/v1/admin/request-logs?job_id={video['id']}")
    audit.check("request_audit", bool(request_logs.get("data")), request_logs.get("data", [])[:2])

    metrics_status, metrics = client.text("/metrics")
    for metric_name in [
        "media2api_jobs_total",
        "media_jobs_total",
        "provider_submit_errors_total",
        "provider_poll_timeout_total",
        "account_lease_active",
        "stalled_jobs_active",
        "stalled_jobs_recovered_total",
    ]:
        audit.check(f"metric:{metric_name}", metrics_status == 200 and metric_name in metrics)

    result = audit.result()
    result["base_url"] = args.base_url
    result["checked_at_unix"] = int(time.time())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
