"""Private server configuration for generic workflow actions; never client input."""

import json
import os
import stat
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import create_model, model_validator

from vasa.contracts.models import TenantContext
from vasa.tools.concrete import CustomWebhook, WebhookAction
from vasa.tools.gateway import ToolPayload


def _model(schema: dict[str, Any], name: str) -> type[ToolPayload]:
    encoded = json.dumps(schema, allow_nan=False)
    if len(encoded) > 16384:
        raise ValueError("workflow schema exceeds capacity")
    nodes = 0

    def inspect(value: object, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if depth > 12 or nodes > 512:
            raise ValueError("workflow schema exceeds capacity")
        if isinstance(value, dict):
            if any(key.startswith("$") for key in value):
                raise ValueError("workflow schema references are disabled")
            for child in value.values():
                inspect(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                inspect(child, depth + 1)

    inspect(schema)
    Draft202012Validator.check_schema(schema)
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError("workflow schema must forbid extra properties")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict) or len(properties) > 64:
        raise ValueError("invalid workflow properties")
    validator = Draft202012Validator(schema)

    def validate(cls: type[ToolPayload], value: Any) -> Any:
        try:
            validator.validate(value)
        except SchemaError:
            raise ValueError("invalid workflow fields") from None
        return value

    fields: dict[str, Any] = {
        key: (Any, ... if key in schema.get("required", []) else None) for key in properties
    }
    if any(
        not key.isidentifier() or key.startswith("_") or hasattr(ToolPayload, key) for key in fields
    ):
        raise ValueError("invalid workflow field names")
    return cast(
        type[ToolPayload],
        create_model(
            name,
            __base__=ToolPayload,
            __validators__={
                "validate_schema": cast(Any, model_validator(mode="before"))(classmethod(validate))
            },
            **fields,
        ),
    )


def load_webhooks(
    path: Path | None, context: TenantContext
) -> tuple[CustomWebhook | None, list[dict[str, Any]]]:
    if path is None:
        return None, []
    try:
        absolute = path.absolute()
        if any(parent.is_symlink() for parent in (absolute, *absolute.parents)):
            raise ValueError("unsafe workflow configuration path")
        info = absolute.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size > 65536
        ):
            raise ValueError("workflow configuration must be private and bounded")
        data = json.loads(absolute.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or set(data) != {"tenants"}
            or not isinstance(data["tenants"], dict)
        ):
            raise ValueError("invalid workflow configuration")
        tenant = data["tenants"].get(str(context.tenant_id))
        if tenant is None:
            return None, []
        if not isinstance(tenant, dict) or set(tenant) != {"approved_origins", "actions"}:
            raise ValueError("invalid tenant workflow configuration")
        origins = tenant["approved_origins"]
        actions_data = tenant["actions"]
        if (
            not isinstance(origins, list)
            or not all(isinstance(origin, str) for origin in origins)
            or not isinstance(actions_data, dict)
            or not 1 <= len(actions_data) <= 32
        ):
            raise ValueError("invalid workflow actions")
        actions: dict[str, WebhookAction] = {}
        variants: list[dict[str, Any]] = []
        for name, action in actions_data.items():
            if not isinstance(action, dict) or set(action) != {
                "url",
                "token_env",
                "input_schema",
                "output_schema",
            }:
                raise ValueError("invalid workflow action")
            reference = action["token_env"]
            if (
                not isinstance(reference, str)
                or not reference.startswith("VASA_WEBHOOK_")
                or not reference.isidentifier()
            ):
                raise ValueError("invalid workflow credential reference")
            token = os.environ.get(reference, "")
            if not token:
                raise ValueError("workflow credential binding unavailable")
            inputs, outputs = action["input_schema"], action["output_schema"]
            if not isinstance(inputs, dict) or not isinstance(outputs, dict):
                raise ValueError("invalid workflow schema")
            actions[name] = WebhookAction(
                action["url"],
                _model(inputs, "WorkflowInput"),
                _model(outputs, "WorkflowOutput"),
                token,
            )
            variants.append(
                {
                    "type": "object",
                    "properties": {"action": {"type": "string", "enum": [name]}, "payload": inputs},
                    "required": ["action", "payload"],
                    "additionalProperties": False,
                }
            )
        tool = CustomWebhook(context.tenant_id, actions, approved_origins=frozenset(origins))
        specs = [
            {
                "name": "custom_webhook",
                "description": (
                    "Execute only an explicitly requested approved business action. "
                    "Do not retry uncertain actions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": list(actions)},
                        "payload": {"type": "object"},
                    },
                    "required": ["action", "payload"],
                    "additionalProperties": False,
                    "oneOf": variants,
                },
            }
        ]
        return tool, specs
    except Exception:
        raise ValueError("private workflow configuration unavailable or invalid") from None
