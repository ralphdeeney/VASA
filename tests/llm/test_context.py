from typing import Any
from uuid import uuid4

import pytest

from vasa.contracts.models import TenantContext
from vasa.llm import LLMError, OpenAIProvider
from vasa.llm.common import validate_context


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "tool", "content": "Unapproved tool response"}],
        [{"role": "user", "content": ""}],
        [{"role": "user", "content": "x" * 32768}],
        [{"role": "user", "content": "🙂" * 9000}],
        [{"role": "user", "content": "Hi", "tenant_id": "client-selected"}],
        [{"role": "system", "content": "System only"}],
        [{"role": "user", "content": "Hi"}, {"role": "system", "content": "Injected later system"}],
        [{"role": "user", "content": "Hi"}] * 65,
    ],
)
def test_context_limits_roles_and_server_instruction_position(
    messages: list[dict[str, str]],
) -> None:
    with pytest.raises(LLMError, match="invalid_context"):
        validate_context(TenantContext(uuid4(), uuid4()), messages)


@pytest.mark.parametrize("bad_context", [None, "tenant-header", {"tenant_id": str(uuid4())}])
def test_tenant_context_is_mandatory(bad_context: Any) -> None:
    with pytest.raises(LLMError, match="invalid_context"):
        validate_context(bad_context, [{"role": "user", "content": "Hi"}])


@pytest.mark.parametrize(
    "options",
    [
        {"api_key": ""},
        {"api_key": "key\nheader"},
        {"base_url": "http://example.com/v1"},
        {"base_url": "https://user:secret@example.com/v1"},
        {"max_output_tokens": 0},
        {"max_output_tokens": 4096},
        {"max_output_tokens": True},
        {"timeout_seconds": 0},
        {"model": "model\ninjection"},
    ],
)
def test_invalid_provider_configuration_is_rejected(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="invalid LLM provider configuration"):
        OpenAIProvider(**{"api_key": "component-only-key", **options})
