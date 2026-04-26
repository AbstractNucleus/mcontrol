# Pattern — custom-domain HTTPS over Tailscale (tailnet-only access) via Cloudflare DNS-01

Reference sheet for Claude. Reusable across any project where a self-hosted service on a Tailscale tailnet needs a pretty custom-domain URL with a real TLS certificate, and access must be restricted to tailnet members only.

## Goal

- Public-looking URL: `service.example.com`
- Valid Let's Encrypt cert (not self-signed, no browser warnings)
- Reachable **only** from devices on the user's Tailscale tailnet
- No public ingress on the host (port 80/443 not exposed to the internet)
- No app-level auth required — tailnet membership is the auth

## How it works

1. **Tailscale** assigns each host a private IP in the CGNAT range `100.64.0.0/10` (e.g. `100.x.y.z`). That IP is only routable between devices on the same tailnet.
2. **DNS** (Cloudflare) holds an `A` record `service.example.com → 100.x.y.z`, **orange cloud OFF** (DNS only, not proxied). Public DNS resolvers return the tailnet IP, but only tailnet devices can route packets to it.
3. **Caddy** on the host terminates TLS for `service.example.com`. It cannot use the default HTTP-01 ACME challenge (the host is not publicly reachable on port 80), so it uses **DNS-01** via the Cloudflare API to prove domain ownership and obtain the cert.
4. Off-tailnet clients: DNS lookup succeeds, packet routing fails — connection times out. On-tailnet clients: everything works.

## Prerequisites

- Domain's DNS is managed by Cloudflare (or any DNS provider with a Caddy DNS-01 plugin — pattern is identical, only the plugin and env vars change).
- Cloudflare API token scoped to `Zone:DNS:Edit` for the target zone. Nothing broader.
- Tailscale installed and running on the host. The host's tailnet IP is known (`tailscale ip -4`).
- Docker or a way to run Caddy with the Cloudflare DNS plugin baked in. The stock `caddy` Docker image does not include DNS plugins; use a custom build or a pre-built community image.

## DNS setup (Cloudflare)

- Create an `A` record: `service.example.com` → tailnet IP.
- **Proxy status: DNS only (gray cloud).** Proxied mode routes through Cloudflare edge, which cannot reach a `100.x.y.z` address and will return 521. Gray cloud is mandatory.
- TTL: Auto is fine.

## Caddyfile

```caddy
service.example.com {
  tls {
    dns cloudflare {env.CF_API_TOKEN}
  }
  reverse_proxy app:3000
}
```

## Docker Compose snippet

Caddy must have the Cloudflare DNS plugin. Either build a custom image with `xcaddy` or use `caddy:builder` / a community image such as `slothcroissant/caddy-cloudflaredns`.

```yaml
services:
  caddy:
    image: slothcroissant/caddy-cloudflaredns:latest
    restart: unless-stopped
    ports:
      - "443:443"
      - "80:80"   # optional; kept for local HTTP→HTTPS redirect
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    environment:
      CF_API_TOKEN: ${CF_API_TOKEN}
    networks:
      - internal

volumes:
  caddy_data:
  caddy_config:
```

Caddy binds to `0.0.0.0:443` on the host. Because the only route to `service.example.com`'s IP is via Tailscale, binding to all interfaces does not expose the service publicly — the public internet cannot reach the tailnet IP.

## Information disclosure caveat

The tailnet IP is visible to anyone who queries public DNS for the hostname. It is not actionable without tailnet membership, but it is not secret. If the user requires the IP be hidden, use split-horizon DNS (MagicDNS on the tailnet, nothing on public DNS) instead — which means giving up the custom domain.

## Failure modes and diagnoses

- **521 error, works over direct `tailscale IP` but not the hostname** → Cloudflare proxy (orange cloud) is on. Turn it off.
- **Caddy fails to issue cert, logs mention `no valid solvers`** → Cloudflare plugin not present in the Caddy binary, or `CF_API_TOKEN` env var not set / wrong scope.
- **Caddy times out on DNS challenge** → API token missing `Zone:DNS:Edit`, or the token's zone scope doesn't include the target zone.
- **Works from one laptop but not another** → the other device isn't on the tailnet or has Tailscale paused.
- **Works locally but external tailnet devices can't reach it** → host firewall (`ufw`, `firewalld`) blocking 443. Allow 443 on the tailscale interface: `sudo ufw allow in on tailscale0 to any port 443`.

## Variants

- **Other DNS providers:** swap the Caddy plugin and env var. Pattern is identical. Common: Route 53 (`caddy-dns/route53`, `AWS_*` env), DigitalOcean (`caddy-dns/digitalocean`, `DO_AUTH_TOKEN`), Namecheap via API, etc.
- **No custom domain wanted:** drop Cloudflare entirely. Use Tailscale MagicDNS + `tailscale cert` to get a cert for `hostname.<tailnet>.ts.net`. Zero DNS setup, but the URL is the MagicDNS one.
- **Occasional public sharing:** add Tailscale Funnel for specific paths, or put a separate public-facing service on a different subdomain with app-level auth. Keep the tailnet-only service on this pattern.

## When to prefer this pattern

- Single-user or small-team self-hosted apps (dashboards, wikis, pastebins, internal tools).
- The user already runs Tailscale.
- No need for public discoverability or public sharing.
- Pretty URL matters enough to justify the Cloudflare token + plugin.

## When to use something else

- The service must be reachable without a VPN (use Cloudflare Tunnel + Access, or public ingress + real auth).
- The user doesn't run Tailscale and doesn't want to start (use WireGuard directly or public ingress).
- The URL doesn't matter (use Tailscale MagicDNS + `tailscale cert`).
