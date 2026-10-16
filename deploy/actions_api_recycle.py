"""Explicit, targeted API connection-pool recycle; never restart dependencies."""


def recycle(namespace):
    """Restart only the validated existing API container and verify preservation."""
    try:
        services = namespace["DEPENDENCIES"] + namespace["SERVICES"]
        before = namespace["snapshot_services"](services)
        hashes = namespace["private_hashes"]()
        head = namespace["git"]("rev-parse", "HEAD")
        status = namespace["git"]("status", "--porcelain=v1", "--untracked-files=all")
        cid, current = namespace["container"]("vasa")
        namespace["require"](
            cid == before["vasa"]["id"]
            and current["image"] == before["vasa"]["image"]
            and namespace["state_ok"](current),
            "API recycle precondition failed.",
        )
        namespace["run"]("docker", "container", "restart", "--time", "15", cid, timeout=90)
        namespace["health"]()
        untouched = {name: value for name, value in before.items() if name != "vasa"}
        namespace["assert_unchanged"](untouched)
        after_id, after = namespace["container"]("vasa")
        namespace["require"](
            after_id == cid
            and after["image"] == before["vasa"]["image"]
            and namespace["state_ok"](after)
            and after["restarts"] == before["vasa"]["restarts"],
            "API recycle health invariant failed.",
        )
        namespace["require"](
            namespace["private_hashes"]() == hashes
            and namespace["git"]("rev-parse", "HEAD") == head
            and namespace["git"]("status", "--porcelain=v1", "--untracked-files=all") == status,
            "API recycle preservation invariant failed.",
        )
    except Exception:
        print("VASA_API_POOL_RECYCLE_FAILED", flush=True)
        raise namespace["Refusal"]("API-only pool recycle failed; raw output withheld.") from None
    print("VASA_API_POOL_RECYCLE_OK", flush=True)
