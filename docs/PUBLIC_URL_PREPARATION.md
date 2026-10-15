# Host-private reverse-proxy access

Operator-confirmed public ingress: root-owned n8n-docker-caddy-1 on
n8n-docker_default, subnet 172.16.2.0/24, host gateway 172.16.2.1.
VASA rootless Docker publishes exactly **172.16.2.1:18081 → 8080/tcp**.
It does not publish VASA on wildcard addresses, the public VPS address or host
loopback. This private bridge endpoint is intended for reverse-proxy access.
An interface bind is not a source-IP firewall rule: host processes and other
namespaces with a route to that private interface may also reach it. No host
routing/firewall/security configuration is changed by VASA deployment.

Evolution remains **127.0.0.1:18080 → 4000/tcp**; its admin interface is not exposed
to the Caddy bridge or public Internet by this change.

Intended public URL: https://vasa.2.25.172.155.sslip.io

For the confirmed Caddy owner, the intended upstream is:

```caddyfile
vasa.2.25.172.155.sslip.io {
    reverse_proxy 172.16.2.1:18081
}
```

This is an operator example only. VASA Actions must never modify root-owned
n8n/Caddy containers, networks or config, or restart Docker. It does not join
VASA to the root-owned network. The ingress owner remains responsible for its
own config validation/reload, DNS and TLS. Public HTTPS is not marked READY
solely because the private upstream responds. The optional Evolution public
admin site is not activated or routed here.

Normal Actions deployment validates target Compose and actual Docker bindings
against the exact addresses/ports, rejecting wildcards and extra publications.
Host postchecks disable proxies/redirects and require private /login=200,
assets=200 and unauthenticated /dashboard=401. Existing API readiness/internal
Evolution checks remain unchanged. No HTML, cookies or credentials are printed.
