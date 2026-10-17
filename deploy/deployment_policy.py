"""Reviewed deployment grants; request documents cannot confer authority."""

REPOSITORY = "ralphdeeney/VASA"
BRANCH = "build/vasa-foundation"
TRUSTED_ACTOR = "ralphdeeney"
ROUTINE_GRANT = "routine-staging-v1"
EVOLUTION_GRANT = "evolution-pool-2026-10-17"
EVOLUTION_REQUEST_ID = "6e1328c2-3554-4c2d-8153-5639304a6b18"
EVOLUTION_UPSTREAM = "e21ce0dd7634f3047410c893b5e4d1c082034b84"
EVOLUTION_PATCH_SHA256 = "daba5ba8222345396ce5934e8a7ef07c353a4ed73fedcbeb785c75a6fb0b5361"

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
