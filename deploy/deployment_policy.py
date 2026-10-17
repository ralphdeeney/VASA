"""Reviewed deployment grants; request documents cannot confer authority."""

REPOSITORY = "ralphdeeney/VASA"
BRANCH = "build/vasa-foundation"
TRUSTED_ACTOR = "ralphdeeney"
ROUTINE_GRANT = "routine-staging-v1"
EVOLUTION_GRANT = "evolution-pool-2026-10-17"
EVOLUTION_REQUEST_ID = "6e1328c2-3554-4c2d-8153-5639304a6b18"
EVOLUTION_UPSTREAM = "e21ce0dd7634f3047410c893b5e4d1c082034b84"
EVOLUTION_PATCH_SHA256 = "daba5ba8222345396ce5934e8a7ef07c353a4ed73fedcbeb785c75a6fb0b5361"

# Operator Authorization B: one staging attempt after successful read-only run
# 39013001527. The historical grant remains consumed and unchanged.
RENEWED_EVOLUTION_GRANT: dict[str, object] | None = {
    "grant_id": "evolution-pool-2026-10-17-renewed-health-1",
    "request_id": "1d64d376-3568-4510-8f51-38560fc402e9",
    "expires_at": "2026-10-17T13:20:19Z",
    "prerequisite_request_id": "08d887be-1626-481e-8a83-7093dbc94f5b",
    "prerequisite_trigger_sha": "7b2bb0ddd354794d176f6e219f7f258fcb852a3f",
    "source_manifest": {
        "docker/evolution.Dockerfile": (
            "45732379a97d94b26a09229b1b4fd9e131dce6313cf29e867f25bd8611f95e47"
        ),
        "docker/evolution-db-pool.patch": (
            "daba5ba8222345396ce5934e8a7ef07c353a4ed73fedcbeb785c75a6fb0b5361"
        ),
        "docker/evolution-log-redaction.patch": (
            "f73b15b2dce8572e91ee923faa27e9a30d3624eab244517fd412459a1cb5b91f"
        ),
        "scripts/prepare_evolution.py": (
            "037304092d6d94991ca8c91d61c52e1b0b647a6b5d5528fe95c45a50ae3d1fc3"
        ),
        "deploy/actions_evolution_pool.py": (
            "1913d24777373d120a6d7fc620a9d2f7b1a2a9638a550855fe814f82d682c78c"
        ),
        "deploy/actions_vps.py": (
            "92a7f3c51955d86725df14487d027e2d00ead8c7897d6bf12ddf07e2bd42f76d"
        ),
        "scripts/evolution_call_gate.py": (
            "330622540a5a0ef0d146bba55426b71c05831085f87fa4f4258f6440d44daa4e"
        ),
        "scripts/evolution_instance_check.py": (
            "a6903c1bbd35d702073cf6ddbad1d2b9b5087103aebf8357c66404500e857df8"
        ),
        "deploy/evolution_backups.py": (
            "2e7e5b63612799d0b26becd918e49cc7267d308323278d21f96359e0b6f44fa5"
        ),
        "deploy/actions_db_capacity.py": (
            "d27d22b77fa47cc6da1129586fc2fb70fb5ebe64a40cbcc407898a8153fa8c97"
        ),
        "deploy/health_diagnostics.py": (
            "21950807d7a886905a559045ede0c1aa622e7d5251ce705eab7c111b9befa22b"
        ),
        "deploy/request_remote.py": (
            "2a90a7232f3d11b73bba860f7d49c70981e2fdfc6cb76942d9f1e16a4c26f45d"
        ),
        "deploy/request_payload.py": (
            "777c21198dd3416f4ebabee2a4237473b131dd0b4e7584bad9d2aae7569326f4"
        ),
        "deploy/deployment_orchestrator.py": (
            "89bfd8d934cebca16fb97341cfe88b64420a42258cabf05a3531609651d7893a"
        ),
    },
}


def active_evolution_grant() -> dict[str, object]:
    if RENEWED_EVOLUTION_GRANT is not None:
        return dict(RENEWED_EVOLUTION_GRANT)
    return {"grant_id": EVOLUTION_GRANT, "request_id": EVOLUTION_REQUEST_ID}


OPERATIONS: dict[str, dict[str, object]] = {
    "application_deploy": {
        "scope": "vasa-application-only",
        "policy": "application-safe-v1",
        "expected_markers": ["VASA_DEPLOYMENT_OK"],
        "authorization": ROUTINE_GRANT,
        "mutating": True,
    },
    "application_check": {
        "scope": "vasa-readonly",
        "policy": "readonly-v1",
        "expected_markers": ["VASA_VPS_CONNECTIVITY_OK"],
        "authorization": ROUTINE_GRANT,
        "mutating": False,
    },
    "evolution_check": {
        "scope": "evolution-readonly",
        "policy": "evolution-readonly-v1",
        "expected_markers": ["EVOLUTION_POOL_PREFLIGHT_OK"],
        "authorization": ROUTINE_GRANT,
        "mutating": False,
    },
    "evolution_pool_rollout": {
        "scope": "evolution-pool-only",
        "policy": "evolution-no-call-backup-v1",
        "expected_markers": ["VASA_EVOLUTION_POOL_DEPLOYMENT_OK"],
        "authorization": EVOLUTION_GRANT,
        "mutating": True,
    },
    "provider_smoke": {
        "scope": "providers-smoke-only",
        "policy": "provider-smoke-v1",
        "expected_markers": ["LLM_SMOKE_OK", "DEEPGRAM_SMOKE_OK"],
        "authorization": None,
        "mutating": False,
    },
}
