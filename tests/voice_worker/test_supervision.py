import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

import vasa.voice_worker as worker
from vasa.contracts.models import IncomingCall, TenantContext


class Events:
    def __init__(self) -> None:
        self.queues: dict[str, asyncio.Queue[IncomingCall]] = {}
        self.closed: set[str] = set()
        self.rejected = asyncio.Event()
        self.rejects: list[tuple[str, str]] = []

    async def events(self, instance: str) -> AsyncIterator[IncomingCall]:
        queue = self.queues.setdefault(instance, asyncio.Queue())
        try:
            while True:
                yield await queue.get()
        finally:
            self.closed.add(instance)

    async def reject(self, instance: str, call: str, caller: str) -> None:
        self.rejects.append((instance, call))
        self.rejected.set()


def target(instance: str) -> worker.WorkerTarget:
    return worker.WorkerTarget(TenantContext(uuid4(), uuid4()), uuid4(), instance, object())


async def test_global_admission_and_duplicate_ids_are_scoped_to_trusted_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = Events()
    targets = [target("tenant-a"), target("tenant-b")]
    started: list[TenantContext] = []
    ended: list[TenantContext] = []
    ready = asyncio.Event()

    async def handle(*args: object, **kwargs: object) -> dict[str, object]:
        context = args[2]
        started.append(context)
        if len(started) == 2:
            ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            ended.append(context)
        return {}

    monkeypatch.setattr(worker, "handle_call", handle)
    task = asyncio.create_task(
        worker.supervise_calls(
            transport,
            object(),
            object(),
            object(),
            targets,
            max_active_calls=2,
        )
    )
    try:
        await asyncio.sleep(0)
        for instance in ("tenant-a", "tenant-b"):
            await transport.queues.setdefault(instance, asyncio.Queue()).put(
                IncomingCall(instance, "same-id", "caller")
            )
        await asyncio.wait_for(ready.wait(), 1)
        await transport.queues["tenant-a"].put(IncomingCall("tenant-a", "same-id", "caller"))
        await transport.queues["tenant-b"].put(IncomingCall("tenant-b", "excess", "caller"))
        await asyncio.wait_for(transport.rejected.wait(), 1)
        assert started == [target.context for target in targets]
        assert transport.rejects == [("tenant-b", "excess")]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert set(ended) == set(started) and transport.closed == {"tenant-a", "tenant-b"}


async def test_reconcile_accepts_new_pairing_and_removal_drains_active_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = Events()
    owned = target("new-paired")
    ready, finished, remove = asyncio.Event(), asyncio.Event(), asyncio.Event()
    resource_closed = asyncio.Event()
    from contextlib import AsyncExitStack

    resources = AsyncExitStack()
    resources.callback(resource_closed.set)
    owned = worker.WorkerTarget(
        owned.context, owned.instance, owned.external_id, owned.runtime, resources=resources
    )

    async def handle(*args: object, **kwargs: object) -> dict[str, object]:
        assert args[2] == owned.context
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
        return {}

    async def reconcile() -> list[worker.WorkerTarget]:
        return [] if remove.is_set() else [owned]

    monkeypatch.setattr(worker, "handle_call", handle)
    task = asyncio.create_task(
        worker.supervise_calls(
            transport,
            object(),
            object(),
            object(),
            [],
            reconcile=reconcile,
            reconcile_seconds=0.01,
        )
    )
    try:
        for _ in range(100):
            if owned.external_id in transport.queues:
                break
            await asyncio.sleep(0.01)
        await transport.queues[owned.external_id].put(
            IncomingCall(owned.external_id, "active", "caller")
        )
        await asyncio.wait_for(ready.wait(), 1)
        remove.set()
        await asyncio.wait_for(resource_closed.wait(), 1)
        assert finished.is_set() and owned.external_id in transport.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_listener_cannot_route_foreign_offer_into_target_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = Events()
    invoked = False

    async def handle(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal invoked
        invoked = True
        return {}

    monkeypatch.setattr(worker, "handle_call", handle)
    task = asyncio.create_task(
        worker.supervise_calls(
            transport,
            object(),
            object(),
            object(),
            [target("owned")],
        )
    )
    await asyncio.sleep(0)
    await transport.queues.setdefault("owned", asyncio.Queue()).put(
        IncomingCall("foreign", "call", "caller")
    )
    with pytest.raises(RuntimeError, match="listener failed"):
        await asyncio.wait_for(task, 1)
    assert not invoked and transport.closed == {"owned"}
