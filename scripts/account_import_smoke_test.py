from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var" / "account_import_smoke.db"
ASSET_DIR = ROOT / "var" / "account-import-smoke-assets"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["ASSET_DIR"] = ASSET_DIR.as_posix()
sys.path.insert(0, str(ROOT))

from media2api import models
from media2api.database import SessionLocal, init_db
from media2api.main import app, dumps
from media2api.security import hash_api_key


HEADERS = {"Authorization": "Bearer dev-admin-key"}


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def request(client: TestClient, method: str, path: str, **kwargs):
    return assert_ok(getattr(client, method)(path, headers=HEADERS, **kwargs))


def seed_admin_and_provider() -> None:
    with SessionLocal() as db:
        db.merge(models.User(id="usr_admin", email="admin@media2api.local", status="active", tier="admin", wallet_balance=100000))
        db.merge(models.ApiKey(id="key_dev_admin", user_id="usr_admin", name="dev admin", key_hash=hash_api_key("dev-admin-key"), status="active"))
        db.merge(
            models.Provider(
                id="gemini",
                name="Gemini",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({"base_url": "http://127.0.0.1:18091"}),
                notes="Account import smoke provider",
            )
        )
        db.merge(
            models.Provider(
                id="midjourney",
                name="Midjourney",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({}),
                notes="Account import smoke provider",
            )
        )
        db.merge(
            models.Provider(
                id="openai_image",
                name="OpenAI Image",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({}),
                notes="Account import smoke provider",
            )
        )
        db.merge(
            models.Provider(
                id="runway",
                name="Runway",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({}),
                notes="Account import smoke provider",
            )
        )
        db.merge(
            models.Provider(
                id="luma",
                name="Luma",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({}),
                notes="Account import smoke provider",
            )
        )
        db.merge(
            models.Provider(
                id="kling",
                name="Kling",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({}),
                notes="Account import smoke provider",
            )
        )
        db.commit()


def main() -> None:
    init_db()
    seed_admin_and_provider()
    client = TestClient(app)

    sub2api_like_payload = {
        "accounts": {
            "gemini_sub2api_01": {
                "provider": "gemini",
                "name": "Gemini Agent from sub2api export",
                "connectorBaseUrl": "http://127.0.0.1:18091",
                "auth": {"type": "agent", "ref": "agent://providers/gemini/sub2api_01"},
                "models": [
                    {"id": "nano-banana-pro", "operations": ["t2i", "edit"]},
                    {"id": "veo-3.1", "capabilities": ["t2v", "i2v"]},
                ],
                "quota": {"type": "credits", "remaining": 120, "confidence": 0.8},
                "maxConcurrency": 2,
                "region": "global",
                "tier": "pro",
            },
            "openai_web_01": {
                "platform": "openai_image",
                "displayName": "ChatGPT Web Session",
                "webSessionRef": "websession://providers/openai_image/web_01",
                "authType": "web_session",
                "supportedOperations": "text_to_image,image_edit",
                "supportedProviderModels": "gpt-image-2",
                "remainingCredits": 42,
            },
        }
    }
    body = {
        "provider_id": "gemini",
        "auth_method": "agent_provider_credential",
        "content": json.dumps(sub2api_like_payload),
        "sync_capabilities": False,
        "run_health_check": False,
    }

    preview = request(client, "post", "/v1/admin/account-subscriptions/preview", json=body)
    assert preview["planned"] == 2 and preview["failed"] == 0, preview
    first = preview["data"][0]["onboarding_request"]
    second = preview["data"][1]["onboarding_request"]
    assert first["auth_method"] == "agent_provider_credential", first
    assert first["credential_ref"] == "agent://providers/gemini/sub2api_01", first
    assert set(first["supported_operations"]) == {"text_to_image", "image_edit", "text_to_video", "image_to_video"}, first
    assert first["supported_provider_models"] == ["nano-banana-pro", "veo-3.1"], first
    assert first["resource_profile"]["agent_runtime_endpoint"] == "http://127.0.0.1:18091", first
    assert "connector_base_url" not in first["resource_profile"], first
    assert first["quota_buckets"][0]["remaining_estimate"] == 120, first
    assert first["concurrency_limit"] == 2 and first["plan"] == "pro", first
    assert second["provider_id"] == "openai_image", second
    assert second["auth_method"] == "cookie_secret", second
    assert second["credential_ref"] == "websession://providers/openai_image/web_01", second

    gemini_structured_body = {
        "provider_id": "gemini",
        "auth_method": "agent_provider_credential",
        "content": json.dumps(
            {
                "accounts": [
                    {
                        "account_id": "gemini_structured_oauth_material",
                        "label": "Gemini structured OAuth material",
                        "auth": {
                            "type": "agent",
                            "GEMINI_CREDENTIALS": {"client_id": "smoke-client", "refresh_token": "smoke-refresh"},
                            "GEMINI_PROJECT_ID": "smoke-project",
                        },
                        "models": [{"id": "nano-banana-pro", "operations": ["t2i"]}],
                    }
                ]
            }
        ),
    }
    gemini_structured_preview = request(client, "post", "/v1/admin/account-subscriptions/preview", json=gemini_structured_body)
    gemini_structured_payload = gemini_structured_preview["data"][0]["onboarding_request"]
    assert gemini_structured_preview["planned"] == 1 and gemini_structured_preview["failed"] == 0, gemini_structured_preview
    assert gemini_structured_payload["credential_kind"] == "agent_provider", gemini_structured_payload
    assert gemini_structured_payload["resource_profile"]["opensource_input_field"] == "structured_credential", gemini_structured_payload

    midjourney_bad_body = {
        "provider_id": "midjourney",
        "auth_method": "cookie_secret",
        "content": json.dumps(
            {
                "accounts": [
                    {
                        "account_id": "mj_bad_profile_base_url",
                        "auth": {"type": "cookie_secret", "cookie_header": "discord-session=bad"},
                        "resource_profile": {
                            "connector_base_url": "http://127.0.0.1:18091",
                            "guild_id": "guild_smoke",
                            "channel_id": "channel_smoke",
                        },
                        "models": [{"id": "mj-v7", "operations": ["t2i"]}],
                    }
                ]
            }
        ),
    }
    bad_preview = client.post("/v1/admin/account-subscriptions/preview", headers=HEADERS, json=midjourney_bad_body)
    assert bad_preview.status_code == 400 and "resource_profile.connector_base_url" in bad_preview.text, bad_preview.text

    midjourney_good_body = {
        "provider_id": "midjourney",
        "auth_method": "cookie_secret",
        "content": json.dumps(
            {
                "accounts": [
                    {
                        "account_id": "mj_cookie_profile",
                        "auth": {"type": "cookie_secret", "cookie_header": "discord-session=ok"},
                        "resource_profile": {
                            "guild_id": "guild_smoke",
                            "channel_id": "channel_smoke",
                            "discord_server": "discord.com",
                        },
                        "models": [{"id": "mj-v7", "operations": ["t2i"]}],
                    }
                ]
            }
        ),
    }
    midjourney_preview = request(client, "post", "/v1/admin/account-subscriptions/preview", json=midjourney_good_body)
    assert midjourney_preview["planned"] == 1 and midjourney_preview["failed"] == 0, midjourney_preview
    profile = midjourney_preview["data"][0]["onboarding_request"]["resource_profile"]
    assert profile["guild_id"] == "guild_smoke" and profile["channel_id"] == "channel_smoke", profile
    assert "connector_base_url" not in profile, profile

    runway_agent_body = {
        "provider_id": "runway",
        "auth_method": "agent_provider_credential",
        "content": json.dumps(
            {
                "accounts": [
                    {
                        "account_id": "runway_agent_profile",
                        "auth": {"type": "agent", "ref": "agent://providers/runway/useapi_01"},
                        "models": [{"id": "runway-gen4", "operations": ["t2v", "i2v"]}],
                    }
                ]
            }
        ),
    }
    runway_preview = request(client, "post", "/v1/admin/account-subscriptions/preview", json=runway_agent_body)
    runway_payload = runway_preview["data"][0]["onboarding_request"]
    assert runway_payload["resource_type"] == "agent_provider", runway_payload
    assert runway_payload["resource_profile"]["resource_type"] == "agent_provider", runway_payload
    assert runway_payload["credential_ref"] == "agent://providers/runway/useapi_01", runway_payload

    luma_named_key_body = {
        "provider_id": "luma",
        "auth_method": "agent_provider_credential",
        "content": json.dumps(
            {
                "accounts": [
                    {
                        "account_id": "luma_named_key_profile",
                        "auth": {"type": "agent", "LUMA_API_KEY": "luma-key"},
                        "models": [{"id": "luma-dream-machine", "operations": ["t2v", "i2v"]}],
                    }
                ]
            }
        ),
    }
    luma_preview = request(client, "post", "/v1/admin/account-subscriptions/preview", json=luma_named_key_body)
    luma_payload = luma_preview["data"][0]["onboarding_request"]
    assert luma_preview["planned"] == 1 and luma_preview["failed"] == 0, luma_preview
    assert luma_payload["credential_kind"] == "agent_provider", luma_payload
    assert luma_payload["resource_profile"]["opensource_input_field"] == "structured_credential", luma_payload

    kling_api_key_body = {
        "provider_id": "kling",
        "auth_method": "agent_provider_credential",
        "content": json.dumps(
            {
                "accounts": [
                    {
                        "account_id": "kling_open_source_key_profile",
                        "label": "Kling open-source key profile",
                        "auth": {"type": "api_key", "KLING_ACCESS_KEY": "kling-access-key", "KLING_SECRET_KEY": "kling-secret-key"},
                        "credential_kind": "api_key",
                        "models": [{"id": "kling-i2v-hq", "operations": ["t2v", "i2v", "extend"]}],
                    }
                ]
            }
        ),
    }
    kling_preview = request(client, "post", "/v1/admin/account-subscriptions/preview", json=kling_api_key_body)
    kling_payload = kling_preview["data"][0]["onboarding_request"]
    assert kling_preview["planned"] == 1 and kling_preview["failed"] == 0, kling_preview
    assert kling_payload["auth_method"] == "agent_provider_credential", kling_payload
    assert kling_payload["resource_type"] == "agent_provider", kling_payload
    assert kling_payload["credential_kind"] == "agent_provider", kling_payload
    assert kling_payload["resource_profile"]["opensource_input_field"] == "structured_credential", kling_payload
    assert kling_payload["resource_profile"]["input_material_policy"] == "imported_as_agent_provider_material", kling_payload
    kling_imported = request(client, "post", "/v1/admin/account-subscriptions/import", json=kling_api_key_body)
    assert kling_imported["created"] == 1 and kling_imported["failed"] == 0, kling_imported
    kling_result = kling_imported["data"][0]
    assert kling_result["account"]["resource_type"] == "agent_provider", kling_result
    assert kling_result["secret"]["kind"] == "agent_provider", kling_result

    openai_bad_ref_body = {
        "provider_id": "openai_image",
        "auth_method": "cookie_secret",
        "content": json.dumps(
            {
                "accounts": [
                    {
                        "account_id": "openai_bad_agent_ref_cookie",
                        "resource_type": "web_cookie_provider",
                        "auth": {"type": "cookie_secret", "ref": "agent://providers/openai_image/bad_cookie"},
                        "models": [{"id": "gpt-image-2", "operations": ["t2i"]}],
                    }
                ]
            }
        ),
    }
    openai_bad_ref_preview = client.post("/v1/admin/account-subscriptions/preview", headers=HEADERS, json=openai_bad_ref_body)
    assert openai_bad_ref_preview.status_code == 400 and "ACCOUNT_CREDENTIAL_REF_RESOURCE_MISMATCH" in openai_bad_ref_preview.text, openai_bad_ref_preview.text

    bad_source = client.post(
        "/v1/admin/account-subscription-sources",
        headers=HEADERS,
        json={
            "provider_id": "midjourney",
            "name": "Bad Midjourney Source",
            "auth_method": "cookie_secret",
            "content": midjourney_good_body["content"],
            "persist_content": True,
            "provider_config": {"base_url": "http://127.0.0.1:18091"},
        },
    )
    assert bad_source.status_code == 400 and "provider_config.base_url" in bad_source.text, bad_source.text
    print("PASS midjourney import runtime/base_url guard")

    imported = request(client, "post", "/v1/admin/account-subscriptions/import", json=body)
    assert imported["created"] == 2 and imported["failed"] == 0, imported
    accounts = request(client, "get", "/v1/accounts")
    account_by_id = {item["id"]: item for item in accounts["data"]}
    assert "gemini_sub2api_01" in account_by_id, account_by_id
    assert account_by_id["gemini_sub2api_01"]["concurrency_limit"] == 2, account_by_id["gemini_sub2api_01"]
    assert account_by_id["openai_web_01"]["credential_ref"] == "secret://secret_openai_web_01", account_by_id["openai_web_01"]
    assert account_by_id["openai_web_01"]["credential_ref_type"] == "secret", account_by_id["openai_web_01"]
    mappings = request(client, "get", "/v1/model-mappings")
    mapping_pairs = {(item["logical_model"], item["provider_model"]) for item in mappings["data"] if item["provider_id"] == "gemini"}
    assert ("t2i-fast", "nano-banana-pro") in mapping_pairs, mapping_pairs
    assert ("image-edit", "nano-banana-pro") in mapping_pairs, mapping_pairs
    assert ("t2v-general", "veo-3.1") in mapping_pairs, mapping_pairs
    assert ("i2v-fast", "veo-3.1") in mapping_pairs, mapping_pairs

    print("PASS account import preview: 2")
    print("PASS account import created: 2")
    print("PASS account import auto mappings: 4")
    print("account import smoke ok")


if __name__ == "__main__":
    main()
