# Always Free container deployment

The public Vercel project currently serves the frontend and a temporary Python
API. Real photo OCR needs the separately hosted container. This deployment
runs the API and PaddleOCR together on an Oracle Cloud Always Free Arm VM,
keeps uploads and SQLite on a Docker volume, and uses Caddy for HTTPS. The
frontend stays at `https://univis-v2-prototype.vercel.app`.

Oracle currently allows an Always Free Ampere A1 instance with a total of
2 OCPUs and 12 GB RAM per free tenancy. Creating an account usually requires
a card, but Oracle says it does not charge the card unless the account is
upgraded. Choose only an **Always Free** shape and stay within its quota.

## Prepare the VM

1. Create an Ubuntu 24.04 Ampere A1 VM with **2 OCPUs and 12 GB RAM** in the
   account's home region and an Always Free-eligible boot volume (the default
   50 GB is within the 200 GB total free storage quota). Assign a public IPv4
   address. Capacity can be temporarily unavailable in some regions.
2. Add an SSH public key during instance creation. Keep the private key on
   your own computer.
3. Allow inbound TCP 80 and 443 in the OCI security list or network security
   group. Limit TCP 22 to your own IP. Enable the same ports in the VM firewall.
4. Install Docker Engine and its Compose plugin using the official Ubuntu
   instructions, then confirm `docker compose version` works.
5. Copy this branch's repository to the VM, including the
   `docker-compose.cloud.yml` and `deploy/Caddyfile` files. Keep it out of a
   web-served directory.

The OCR Dockerfile installs PaddlePaddle's official Linux Arm wheel when
building on this VM. No emulation is needed.

## Configure and start

Copy `.env.cloud.example` to `.env.cloud` on the VM. Set:

- `OPENAI_API_KEY` to the server-side key; never commit it or put it in the
  browser.
- `PADDLEOCR_SERVICE_TOKEN` to a fresh random 32-byte or longer secret. Only
  the API container can reach the OCR container; the token is additional
  protection.
- Optionally set `VISNOTICE_ADMIN_TOKEN` to a separate long random secret if
  researcher administration is needed. Keep it server-side; public browsers
  must not receive it. Without it, global notice listing, editing,
  reprocessing, and study CSV export are disabled in public mode.
- `API_HOST` to a hostname resolving to the VM's public IP. An owned DNS name
  is preferred. For a test without a domain, an IP-based hostname such as
  `203-0-113-42.sslip.io` can be used for public IP `203.0.113.42`.

From the repository root on the VM:

```sh
docker compose --env-file .env.cloud -f docker-compose.cloud.yml up -d --build
docker compose --env-file .env.cloud -f docker-compose.cloud.yml ps
curl -fsS "https://$API_HOST/api/health"
```

The health response should show `openai_configured: true` and
`ocr_provider: paddleocr-ppocrv5-korean-container`. The OCR container downloads
and loads the two Korean models before its health check passes. Its model
cache, the API's uploads and SQLite database, and Caddy certificates live on
Docker volumes across container restarts. Back up the `univis_data` volume if
notice and study results must survive VM loss.

## Connect Vercel

Only switch the Vercel rewrites after a real non-demo photo succeeds against
the VM API. Replace the three Python destinations in `vercel.json` with the
HTTPS API hostname, keeping their source paths:

```json
{
  "source": "/api/:path*",
  "destination": "https://api.example.org/api/:path*"
}
```

Apply the same pattern to `/uploads/:path*` and `/demo-images/:path*`, then
deploy this branch to the existing Vercel project. The browser can continue
using same-origin URLs. Vercel's external proxy has a 120-second wait for the
upstream response, so benchmark a real photo through the Vercel URL too.

In the Vercel dashboard, set Project Settings → Environments → Production →
Branch Tracking to `prototype/paddleocr-gpt41mini`. The current linked project
still tracks `main`, so changing this setting is necessary for future pushes
to this prototype branch to deploy automatically.

## Operational limits

- This free VM has only 2 OCPUs. OCR latency will likely differ from the local
  8-thread benchmark; measure before promising an interaction time.
- Oracle may reclaim an Always Free instance that meets its idle criteria for
  seven days. This option cannot guarantee uninterrupted hosting; back up
  the data volume and be prepared to recreate the instance if necessary.
- Anonymous analysis still spends the configured OpenAI key. Set an OpenAI
  project budget and monitor usage before inviting unrestricted traffic.
- Public mode blocks global notice browsing, mutation, and study CSV export
  unless a server-side administrator token is supplied. It is not user-account
  isolation: submitted images and results persist on the VM, and image URLs are
  accessible to anyone who obtains a result URL. Do not process private
  notices until authentication, encryption, and retention controls are added.
- Keep the VM, Docker, and images patched, and back up the data volume if
  saved results matter.

References: [OCI Always Free limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
[Docker on Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
[PaddlePaddle CPU packages](https://www.paddlepaddle.org.cn/packages/stable/cpu/paddlepaddle/),
[Vercel external rewrites](https://vercel.com/docs/routing/rewrites).
