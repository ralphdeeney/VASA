"""API pool recovery must not restart any other VASA service."""

import pytest

from deploy.actions_api_recycle import recycle


class Refusal(RuntimeError):
    pass


@pytest.mark.parametrize("failure", ["none", "precondition", "health", "preservation"])
def test_recycle_targets_only_existing_api_and_preserves_everything_else(capsys, failure):
    names = ("postgres", "redis", "evolution", "vasa", "voice")
    snapshots = {
        name: {"id": name + "-validated-id", "image": "image-" + name, "restarts": 0}
        for name in names
    }
    calls = []
    preserved = []
    hash_calls = []

    def require(condition, message):
        if not condition:
            raise Refusal(message)

    def container(name):
        value = dict(snapshots[name])
        if failure == "precondition":
            value["image"] = "unexpected"
        return value["id"], value

    def health():
        if failure == "health":
            raise RuntimeError("private-provider-response-secret")

    def hashes():
        hash_calls.append(True)
        return {
            "private": "changed" if failure == "preservation" and len(hash_calls) > 1 else "same"
        }

    namespace = {
        "DEPENDENCIES": ("postgres", "redis", "evolution"),
        "SERVICES": ("vasa", "voice"),
        "snapshot_services": lambda requested: snapshots,
        "private_hashes": hashes,
        "git": lambda *args: "unchanged-operator-work",
        "container": container,
        "require": require,
        "state_ok": lambda _: True,
        "run": lambda *args, **kwargs: calls.append((args, kwargs)),
        "health": health,
        "assert_unchanged": lambda value: preserved.append(value),
        "Refusal": Refusal,
    }
    if failure == "none":
        recycle(namespace)
    else:
        with pytest.raises(Refusal, match="raw output withheld"):
            recycle(namespace)
    assert calls == (
        []
        if failure == "precondition"
        else [
            (
                ("docker", "container", "restart", "--time", "15", "vasa-validated-id"),
                {"timeout": 90},
            )
        ]
    )
    output = capsys.readouterr().out
    assert output == (
        "VASA_API_POOL_RECYCLE_OK\n" if failure == "none" else "VASA_API_POOL_RECYCLE_FAILED\n"
    )
    if failure in {"none", "preservation"}:
        assert set(preserved[0]) == {"postgres", "redis", "evolution", "voice"}
