# Public URL preparation (not activated)

Intended URLs:

- VASA: https://vasa.2.25.172.155.sslip.io
- Optional restricted Evolution admin: https://evolution.2.25.172.155.sslip.io

Status: BLOCKED by unverified external/root-owned public proxy ownership and
network path. A working loopback service does not establish public reachability.
No root-owned proxy, firewall, public binding or unrelated service is changed by
VASA Actions. Ports 18081 and 18080 must remain loopback-only.

An operator who owns the public ingress must first identify the actual 80/443
listener, its container/network namespace and mounted configuration through their
existing admin channel. Do not assume second-brain-ui-caddy-1 owns public ingress:
the reported port is 8443. Do not edit /root/second-brain-ui/Caddyfile or the n8n
proxy based on name alone. vasa-builder must not manipulate root Docker.

Required route: the verified TLS ingress must be able to reach the VPS **host's**
127.0.0.1:18081 for VASA, and optionally 127.0.0.1:18080 for Evolution. A proxy
container's 127.0.0.1 is normally its own namespace. A host-gateway address does
not automatically make a host-loopback-only listener reachable. The ingress owner
must confirm a supported route/namespace path while preserving loopback bindings.
Do not publish either service on 0.0.0.0 or join unrelated networks automatically.

Conditional Caddy example, **only if the confirmed public proxy shares the host
network namespace or otherwise has a verified equivalent loopback route**:

```caddyfile
vasa.2.25.172.155.sslip.io {
    reverse_proxy 127.0.0.1:18081
}
```

The optional Evolution admin site additionally needs ingress-owner access policy
(VPN/IP policy/authentication as appropriate); it is not needed for live WhatsApp
calls. Do not publish its admin routes or key in a URL. Do not add it until the
owner confirms that policy and the equivalent 18080 route.

Before activation, the ingress owner should review the actual config, validate it
with that installed Caddy version, preserve a rollback copy, and use that proxy's
approved reload procedure. VASA deployment must not perform those actions. After
activation, verify DNS, trusted TLS, /login, login assets, and unauthenticated
/dashboard=401 from an external client. Only then mark the public VASA URL READY.
An actual user login remains a human credential gate; do not create/reset an
account or password as part of deployment validation.
