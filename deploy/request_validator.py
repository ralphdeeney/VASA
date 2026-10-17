"""Strict, secret-safe validation of request data against trusted Actions facts."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from deploy.deployment_policy import (
    BRANCH,
    OPERATIONS,
    REPOSITORY,
    TRUSTED_ACTOR,
    active_evolution_grant,
)


class RequestRejected(ValueError):
    """Only a fixed diagnostic code escapes validation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RequestRejected("invalid_json")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise RequestRejected("invalid_json")


def load_request(path: str | Path) -> dict[str, Any]:
    try:
        source = Path(path)
        if source.is_symlink() or source.stat().st_size > 16384:
            raise RequestRejected("invalid_json")
        value = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_object,
            parse_constant=_constant,
        )
        if not isinstance(value, dict):
            raise RequestRejected("invalid_json")
        return value
    except (OSError, UnicodeError, ValueError):
        raise RequestRejected("invalid_json") from None


def validate_request(
    request: dict[str, Any], context: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    schema = json.loads(Path(__file__).with_name("request_schema.json").read_text())
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(request):
        raise RequestRejected("invalid_schema")
    if context.get("version", 1) != 1:
        raise RequestRejected("incompatible_version")
    if context.get("repository") != REPOSITORY or context.get("branch") != BRANCH:
        raise RequestRejected("untrusted_repository_or_branch")
    if context.get("actor") != TRUSTED_ACTOR or context.get("actor_permission") not in {
        "write",
        "maintain",
        "admin",
    }:
        raise RequestRejected("unauthorized_actor")
    operation = OPERATIONS[request["operation"]]
    if operation["authorization"] is None:
        raise RequestRejected("authorization_required")
    if request["operation"] == "evolution_pool_rollout":
        operation = dict(operation, authorization=active_evolution_grant()["grant_id"])
    for field in ("scope", "policy", "expected_markers", "authorization"):
        if request[field] != operation[field]:
            raise RequestRejected("policy_mismatch")
    if request["operation"] == "evolution_pool_rollout":
        if request["request_id"] != active_evolution_grant()["request_id"]:
            raise RequestRejected("authorization_required")
    expected_path = f"deploy/requests/{request['request_id']}.json"
    if context.get("changed_paths") != [expected_path]:
        raise RequestRejected("invalid_request_commit")
    sha = re.compile(r"[0-9a-f]{40}\Z")
    trigger = context.get("trigger_sha")
    parent = context.get("parent_sha")
    if not isinstance(trigger, str) or not sha.fullmatch(trigger):
        raise RequestRejected("invalid_commit")
    if not isinstance(parent, str) or not sha.fullmatch(parent) or parent == trigger:
        raise RequestRejected("invalid_commit")
    if request["target_commit"] != parent:
        raise RequestRejected("target_mismatch")
    if context.get("head_sha") != trigger:
        raise RequestRejected("superseded_request")
    if request["request_id"] in context.get("completed_ids", []):
        raise RequestRejected("replayed_request")
    if context.get("source_ci") != "success" or context.get("trigger_ci") != "success":
        raise RequestRejected("ci_required")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise RequestRejected("invalid_time")
    created = datetime.fromisoformat(request["created_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(request["expires_at"].replace("Z", "+00:00"))
    if created > current or expires <= current or expires <= created:
        raise RequestRejected("stale_request")
    if expires - created > timedelta(hours=24) or current - created > timedelta(hours=24):
        raise RequestRejected("stale_request")
    if request["operation"] == "evolution_pool_rollout":
        grant_expiry = active_evolution_grant().get("expires_at")
        if grant_expiry is not None:
            try:
                deadline = datetime.fromisoformat(str(grant_expiry).replace("Z", "+00:00"))
                if deadline.tzinfo is None or current >= deadline or expires > deadline:
                    raise RequestRejected("stale_request")
            except (ValueError, TypeError):
                raise RequestRejected("stale_request") from None
    return dict(request)
