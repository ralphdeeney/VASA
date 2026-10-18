"""The documented manifest must satisfy the real strict runtime contract."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from vasa.contracts.models import TenantContext
from vasa.tools.webhooks_config import load_webhooks


async def test_n8n_guide_manifest_validates_real_input_and_raw_response(tmp_path, monkeypatch):
    sample = Path("docs/integrations/n8n-action.example.json")
    private = tmp_path / "actions.json"
    content = await asyncio.to_thread(sample.read_text)
    await asyncio.to_thread(private.write_text, content)
    private.chmod(0o600)
    assert private.stat().st_uid == os.getuid()
    monkeypatch.setenv("VASA_WEBHOOK_AVAILABILITY_TOKEN", "fixture-token-not-real")
    tenant = UUID("11111111-1111-4111-8111-111111111111")
    tool, specs = load_webhooks(private, TenantContext(tenant_id=tenant, user_id=UUID(int=2)))
    assert tool is not None
    try:
        assert specs[0]["parameters"]["properties"]["action"]["enum"] == ["check_availability"]
        manifest = json.loads(content)
        from vasa.tools.webhooks_config import _model

        action = manifest["tenants"][str(tenant)]["actions"]["check_availability"]
        inputs = _model(action["input_schema"], "GuideInput")
        outputs = _model(action["output_schema"], "GuideOutput")
        assert inputs.model_validate({"service": "consultation", "date": "2026-11-02"})
        assert outputs.model_validate({"available": False, "slots": [], "message": "No slots."})
        with pytest.raises(ValidationError):
            inputs.model_validate(
                {"service": "consultation", "date": "2026-11-02", "tenant_id": "override"}
            )
        with pytest.raises(ValidationError):
            outputs.model_validate(
                {"result": {"available": True, "slots": [], "message": "wrong wrapper"}}
            )
    finally:
        await tool.aclose()
