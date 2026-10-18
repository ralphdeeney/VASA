"""The operator-approved first web binding must never exempt provider or voice config."""

import pytest

from deploy import actions_vps as controller


@pytest.fixture
def binding(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, "ROOT", tmp_path)
    private = tmp_path / ".local"
    private.mkdir()
    path = private / "smtp.env"
    path.write_text("test-only-private-configuration")
    path.chmod(0o600)
    return {
        "VASA_SMTP_HOST": "smtp.reloop.sh",
        "VASA_SMTP_PORT": "587",
        "VASA_SMTP_USERNAME": "test-only-reloop-api-key",
        "VASA_SMTP_PASSWORD": "test-only-reloop-api-key",
        "VASA_SMTP_SENDER": "VASA <noreply@send.litatech.xyz>",
        "VASA_SMTP_STARTTLS": "true",
        "VASA_SMTP_DELIVERY_VERIFIED": "false",
    }, path


def test_exact_approved_first_binding_is_web_only_and_does_not_attest(binding):
    values, path = binding
    baseline = {"VASA_TTS_PROVIDER": "deepgram", "VASA_OPENAI_MODEL": "existing-model"}
    before = path.read_bytes()
    controller.compatible_release_environment("vasa", baseline, {**baseline, **values})
    assert path.read_bytes() == before and values["VASA_SMTP_DELIVERY_VERIFIED"] == "false"
    with pytest.raises(controller.Refusal, match="Provider or private"):
        controller.compatible_release_environment("voice", baseline, {**baseline, **values})


@pytest.mark.parametrize(
    "name,value",
    [
        ("VASA_SMTP_HOST", "unapproved.invalid"),
        ("VASA_SMTP_PORT", "25"),
        ("VASA_SMTP_SENDER", "not-approved@example.invalid"),
        ("VASA_SMTP_STARTTLS", "false"),
        ("VASA_SMTP_PASSWORD", "different-private-key"),
        ("VASA_SMTP_USERNAME", ""),
        ("VASA_SMTP_DELIVERY_VERIFIED", "anything"),
    ],
)
def test_wrong_transport_sender_or_key_is_rejected(binding, name, value):
    values, _ = binding
    with pytest.raises(controller.Refusal, match="approved Reloop configuration"):
        controller.compatible_release_environment("vasa", {}, {**values, name: value})


@pytest.mark.parametrize(
    "key",
    [
        "VASA_TTS_PROVIDER",
        "VASA_OPENAI_BASE_URL",
        "DEEPGRAM_API_KEY",
        "OTHER_SECRET",
        "VASA_SMTP_UNKNOWN",
    ],
)
def test_approved_smtp_does_not_mask_other_configuration_changes(binding, key):
    values, _ = binding
    with pytest.raises(controller.Refusal, match="Provider or private"):
        controller.compatible_release_environment("vasa", {key: "old"}, {**values, key: "new"})


def test_existing_smtp_cannot_be_replaced_under_first_binding_scope(binding):
    values, _ = binding
    old = {**values, "VASA_SMTP_SENDER": "existing@example.invalid"}
    with pytest.raises(controller.Refusal, match="separate review"):
        controller.compatible_release_environment("vasa", old, values)


def test_missing_incomplete_or_insecure_private_binding_refused(binding):
    values, path = binding
    with pytest.raises(controller.Refusal, match="separate review"):
        controller.compatible_release_environment("vasa", {}, {"VASA_SMTP_HOST": "smtp.reloop.sh"})
    path.chmod(0o644)
    with pytest.raises(controller.Refusal, match="owned private"):
        controller.compatible_release_environment("vasa", {}, values)
    path.unlink()
    with pytest.raises(controller.Refusal, match="owned private"):
        controller.compatible_release_environment("vasa", {}, values)


def test_existing_identical_configuration_keeps_normal_release_behavior(binding):
    values, _ = binding
    controller.compatible_release_environment("vasa", values, dict(values))
    controller.compatible_release_environment("voice", {}, {})
