# Optional HTTPS access from a trusted LAN (synthetic lab only)

This overlay provides a TLS entry point on an explicitly chosen **Windows Docker host IPv4** address, e.g. `https://192.168.1.100:8443`. The existing frontend remains published **only to the host loopback** for compatibility with existing browser smoke tests. PostgreSQL, the worker and the media ingest are never published to the host by this overlay. This is not a production or Internet deployment and does not authorize real-camera access.

The reverse proxy is Caddy using its local certificate authority (`tls internal`). Its root CA must be installed on each authorized test client's trust store, after verifying its provenance. Do not share the CA private key. Do not use insecure certificate verification or bypass browser warnings for credential entry.

## Prepare

1. Use a disposable Docker Desktop Linux-container context and a **trusted isolated LAN**. Confirm `192.168.1.100` is actually an address assigned to the **Windows host** (use `Get-NetIPAddress -AddressFamily IPv4`). Give the host a stable DHCP reservation if this is a shared lab. The IP below is an example, not a discovered address.
2. Ensure Windows Defender Firewall/network profile and upstream LAN ACL permit only selected testers; do not expose TCP 8443 to WAN, public Wi-Fi or untrusted VLANs. If you cannot isolate the LAN, do **not** enable this overlay.
3. From the `backend-v2` directory, generate `.env.synthetic-stack` only if missing, as described in [SYNTHETIC_COMPOSE.md](SYNTHETIC_COMPOSE.md). Keep this file private and out of Git. Fetch/pull the intended feature branch before startup.

```powershell
Set-Location D:\wyha\PPE_Construction\PPE_Construction_V2_Clean\backend-v2
if (-not (Test-Path .env.synthetic-stack)) {
    python scripts/create_synthetic_environment.py .env.synthetic-stack
}
$env:PPE_LAB_LAN_IP = '192.168.1.100' # REPLACE with the host's actual LAN IP
$lab = @('--env-file', '.env.synthetic-stack',
         '-f', 'compose.synthetic.yaml',
         '-f', 'compose.synthetic.media.yaml',
         '-f', 'compose.synthetic.ai.yaml',
         '-f', 'compose.synthetic.lan-https.yaml')
docker compose @lab config --quiet
docker compose @lab up --build --wait --wait-timeout 120
docker compose @lab ps
```

The Caddy process listens inside Docker on port 8443 and Docker publishes it on the selected **host** LAN address. The host must actually own that address; otherwise Docker port publishing fails. Note that Docker Desktop / Windows firewall or VPN rules may restrict IP-specific port publishing differently: diagnose bindings with `docker compose @lab ps`, `Get-NetTCPConnection -LocalPort 8443`, and `Test-NetConnection 192.168.1.100 -Port 8443`.

## Trust the TLS certificate

Once the container is started, export the public root CA certificate to the current directory (do **not** export the private CA key):

```powershell
docker compose @lab cp lan-https:/data/caddy/pki/authorities/local/root.crt ./ppe-lab-lan-root.crt
certutil -dump .\ppe-lab-lan-root.crt
```

Verify the certificate fingerprint and transfer the certificate over a trusted channel to each test device. On **managed/authorized Windows test machines**, an administrator may import the verified root CA:

```powershell
# Run in an elevated PowerShell on an authorized Windows test machine
certutil -addstore -f Root .\ppe-lab-lan-root.crt
```

For Firefox, import the verified root into its Authorities trust store if it does not use the OS roots. Mobile devices need OS-specific CA installation and explicit certificate trust. Trusting a private CA is a powerful decision: remove it when the lab is retired, and never import it on devices you do not administer. Keep `lan_caddy_data` intact to retain the same CA across restarts. A `down --volumes` destroys the CA; if recreated, old clients must trust the new public root.

Open **`https://192.168.1.100:8443`** on an authorized LAN client. Use the existing synthetic operator account and its private `PPE_LAB_LOGIN_PASSWORD` from the environment file. The browser should display a valid certificate for the actual IP after CA trust is installed.

## Limit Windows Firewall ingress

If Windows Defender Firewall requires a specific inbound rule, use an elevated PowerShell session, replacing the test subnet with the actual authorized subnet. Only enable this rule on the expected **Private** network profile:

```powershell
New-NetFirewallRule -DisplayName 'PPE Synthetic HTTPS LAN 8443' `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8443 `
    -LocalAddress 192.168.1.100 -RemoteAddress 192.168.1.0/24 `
    -Profile Private
```

Adjust remote addresses to specific approved tester IPs for stronger restrictions. Firewall and segmentation must remain the enforcement boundary; this Compose overlay does not authenticate devices, only users through the existing app.

## Acceptance and limitations

- From **another authorized LAN machine**, `Test-NetConnection 192.168.1.100 -Port 8443` should succeed; `https://192.168.1.100:8443` should load without TLS warnings **after** root trust is configured.
- Sign in, view the North synthetic camera preview, inspect model assignment, update the test incident, and confirm South tenant isolation. Verify a wrong password, session expiry, and unauthorized API requests still fail.
- Verify `http://192.168.1.100:8443` cannot serve the app and `http://192.168.1.100:<frontend-random-port>` is not reachable from a different LAN client. Existing `127.0.0.1` smoke test binding is expected to remain reachable locally.
- Do not forward router port 8443 to the Internet; do not reuse disposable passwords/CA in production.
- Confirm exact request origin and CORS/session behavior in the browser; use relative same-origin `/api/v1` calls. If the address or subnet changes, update `PPE_LAB_LAN_IP`, recreate the proxy and re-validate the issued IP certificate.
- TLS terminates at Caddy; it is HTTP over the private Docker web network from Caddy to the frontend proxy. This is suitable only for the described trusted lab topology.

## Stop and remove

```powershell
docker compose @lab down
Remove-NetFirewallRule -DisplayName 'PPE Synthetic HTTPS LAN 8443' # elevated; only if rule was created
```

`down` preserves lab volumes and the local CA. Removing the CA trust from each authorized test device is a separate step when the lab is retired. Only use `down --volumes` after confirming this is a disposable lab and you intentionally want to erase its database, generated model volumes and TLS CA.

If certificate trust is not acceptable on test devices, use a stable LAN hostname with an organization-managed certificate authority instead. Public CAs generally will not issue a normal certificate for a private RFC1918 address.
