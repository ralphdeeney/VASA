# One-use Evolution pool maintenance authorization

The operator explicitly approved Authorization A (the identifying-client patch)
and separately Authorization B (one new conditional staging pool-fix attempt).
The repository's trusted authority is its reviewed coded policy plus independently
verified owner actor, repository permission, protected operation scope, exact
branch/source/request identities and successful CI. There is no separate external
grant issuer configured. A request JSON's own approval flag is never authority.

Read-only request `08d887be-1626-481e-8a83-7093dbc94f5b` succeeded in Actions
[39013001527](https://github.com/ralphdeeney/VASA/actions/runs/39013001527), using
source `1fa6d90b79caa52f7b17be0e023c212fa9b6d7a3` and request envelope
`7b2bb0ddd354794d176f6e219f7f258fcb852a3f`. Both exact-SHA Verify runs passed
1,425 tests. The real independent-runner and VPS identified health checks passed;
VPS emitted `EVOLUTION_PUBLIC_HEALTH_OK`. Private login/readiness/dashboard were
200/200/401. Anonymous identity, instance and platform-admin APIs returned401 on
runner public and VPS public/private probes. All five service identities and
private/operator file hashes were unchanged. Connections: Evolution1, API1,
voice1, other0,total3,max100. Durable/Redis calls and media sockets were zero.

The new policy binds a distinct request UUID, single-use grant ID, absolute
six-hour expiry, successful private prerequisite receipt and exact source/build/
controller/safety-input hashes. It is checked again while holding the existing
controller lock immediately before the claim and voice-admission pause. Fresh
public health is rechecked before claim. Fresh backup/restore, ownership, no-call,
rollback and identity gates remain mandatory. The consumed historical grant is
preserved and cannot be reused. A failed replacement consumes the new attempt;
no automatic second replacement is authorized.

No application release activation, migration, provider change, Cloudflare/tunnel
change or operator-file change is part of this grant. The app/voice release stays
858b5f853957d719a34ea96f28b5ea726100d402. Registered offline/logged-out WhatsApp
state is preserved separately from container health; no automatic pairing or real
call is authorized. SMTP remains deferred. Rollout outcome will be recorded after
actual execution rather than inferred from this authorization.
