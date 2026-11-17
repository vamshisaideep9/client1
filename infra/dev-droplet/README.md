# Development droplet

Status: **development/staging only — never production, customer, or KYC data**

This runs the development stack (`docker-compose.yml` + `docker-compose.dev.yml`)
on one DigitalOcean droplet so the team can review work over HTTPS. The API runs
in `ENV=development`; the web app runs as the production standalone image so
page speed on this host reflects what users will get. The
production topology, images, and launch gates are separate:
`docker-compose.prod.example.yml` and `docs/agent-context/pre-deployment-checklist.md`.

What this directory adds:

| File | Purpose |
| --- | --- |
| `compose.droplet.yml` | Builds the web app's production image, removes datastore ports, replaces MinIO with a dedicated DigitalOcean Space, binds the proxied ports to `127.0.0.1`, injects fresh credentials and public HTTPS origins, and adds restart policies. |
| `Caddyfile` | Host HTTPS proxy with automatic certificates, an IP allowlist, and response compression. |
| `init-env.sh` | Writes the repository-root `.env` with fresh random credentials. |
| `dc.sh` | `docker compose` with the three files in the right order. |

The droplet checks out only the paths the stack needs (sparse checkout); docs,
tests, contracts, and tooling stay off the server.

**Object storage is a DigitalOcean Space, not MinIO.** MinIO no longer
publishes the `minio/minio` and `minio/mc` images, so uploads (KYC and loan
documents, property and campaign media, task documents) and banner images use
a dedicated dev Space instead (step 4b). The Caddy allowlist does not cover the
Space: anything under its `public/` prefix is world-readable and everything
else needs a short-lived signed URL, so keep this environment on synthetic
data only.

## 1. Create the droplet

- Ubuntu 24.04 x64, **4 vCPU / 8 GB** (the dev servers and ClamAV need more
  memory than the compact production build), region BLR1, SSH-key login only.
- Cloud Firewall inbound: TCP 22 from your IP only; TCP 80 and 443 from
  anywhere so Let's Encrypt can validate. Caddy returns 403 to every address
  outside the allowlist. Nothing else is opened.
- One DNS `A` record, `dev.dhanadhara.com`, pointing at the droplet (or its
  reserved IP). The apex `dhanadhara.com` and `www` stay reserved for
  production; never point them at this server.

## 2. Prepare the host (as root, once)

```bash
adduser deploy && usermod -aG sudo deploy
rsync -a ~/.ssh /home/deploy/ && chown -R deploy:deploy /home/deploy/.ssh
# /etc/ssh/sshd_config: PermitRootLogin no, PasswordAuthentication no
systemctl restart ssh
apt-get update && apt-get -y upgrade
apt-get -y install git openssl unattended-upgrades caddy
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Install Docker Engine and the Compose plugin from Docker's official apt
repository (docs.docker.com/engine/install/ubuntu), then:

```bash
usermod -aG docker deploy
cat >/etc/docker/daemon.json <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }
EOF
systemctl restart docker
docker compose version   # v2.24 or newer
```

## 3. Check out only what the stack needs (as `deploy`)

Use a read-only deploy key for the private repository.

```bash
sudo install -d -o deploy -g deploy /opt/dhanadhara
git clone --filter=blob:none --sparse --branch main <repo-ssh-url> /opt/dhanadhara
cd /opt/dhanadhara
git sparse-checkout init --cone
git sparse-checkout set apps/api apps/web apps/media-runtime infra/dev-droplet packages/contracts
git config core.sparseCheckoutCone && ls   # expect "true" and docker-compose*.yml
```

Cone mode also keeps the root files, which include the two compose files.
Run `init --cone` first: Git 2.34 (Ubuntu 22.04) left non-cone patterns in
place even with `set --cone` and dropped the root compose files.

## 4. Generate fresh configuration

```bash
cd /opt/dhanadhara
infra/dev-droplet/init-env.sh \
  --domain dev.dhanadhara.com \
  --allow-ip 203.0.113.10 --allow-ip 198.51.100.0/24
```

This writes `.env` (mode 600) with a new database password and JWT secret,
and creates an empty `apps/api/.env.local` for optional API settings
such as `EMAIL_ENABLED=true` with the `SMTP_*` values.

`ENV=development` returns one-time codes in API responses by design, so testers
can sign in without SMS or email delivery. Anyone who can reach the API can do
the same, which is why the Caddy IP allowlist is this server's access boundary:
never remove it, and never point real users at this host.

## 4b. Create the dev Space and add its key

In the DigitalOcean console (once per environment; production gets its own
Space and key, see `infra/production-environment/README.md`):

1. **Spaces Object Storage → Create**: region **BLR1**, a dev-only name such
   as `dhanadhara-dev`, **Restrict File Listing**, CDN **off**. Assets are
   served from the regional origin, which is the single origin the web CSP
   and image allowlist trust.
2. **Spaces Keys → Create**: **Limited access**, read/write to this Space
   only. Never reuse the production key here.
3. Append the values to the repository-root `.env` on the droplet by hand.
   `init-env.sh` never writes them, and they must never be committed, pasted
   into chat, or copied elsewhere:

   ```bash
   cat >>.env <<'EOF'
   SPACES_ENDPOINT_URL=https://blr1.digitaloceanspaces.com
   SPACES_REGION=blr1
   SPACES_BUCKET=dhanadhara-dev
   SPACES_ACCESS_KEY=<access key>
   SPACES_SECRET_KEY=<secret key>
   EOF
   ```

`dc.sh config --quiet` fails until all five are set. Spaces refuses bucket
policies, so the overlay sets `SPACES_PUBLIC_OBJECT_ACL=true`: the app gives
each object under `public/` a `public-read` ACL and leaves everything else
private. After the stack starts (step 6), apply the bucket's CORS rule and
verify the whole posture:

```bash
infra/dev-droplet/dc.sh exec -T api uv run python -m app.scripts.configure_storage --apply --verify
```

It allows uploads only from `https://dev.dhanadhara.com`. Every check must
print `true`: anonymous listing and private objects are denied, `public/`
objects are readable, and an untrusted origin gets no CORS grant. Rerun it
with `--verify` alone whenever you want to recheck.

If `--apply` reports `AccessDenied`, the limited key may not be allowed to
change bucket settings. Rerun only `--apply` once with a temporary
full-access key, passed as `-e SPACES_ACCESS_KEY=… -e SPACES_SECRET_KEY=…` on
that one `dc.sh exec`, and delete that key in the console straight away. Then
run `--verify` with the normal limited key. Never store the full-access key in
`.env`.

## 5. Configure Caddy

```bash
sudo install -m 0644 infra/dev-droplet/Caddyfile /etc/caddy/Caddyfile
grep -E '^DEV_(DOMAIN|ALLOWED_IPS)=' .env \
  | sudo tee /etc/caddy/dev-droplet.env >/dev/null
sudo chown root:caddy /etc/caddy/dev-droplet.env && sudo chmod 0640 /etc/caddy/dev-droplet.env
sudo install -d /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironmentFile=/etc/caddy/dev-droplet.env\n' \
  | sudo tee /etc/systemd/system/caddy.service.d/dev-droplet.conf >/dev/null
sudo systemctl daemon-reload && sudo systemctl restart caddy
sudo systemctl status caddy --no-pager
```

## 6. Start the stack

```bash
infra/dev-droplet/dc.sh config --quiet   # fails if .env is missing a value, including SPACES_*
infra/dev-droplet/dc.sh up -d --build
infra/dev-droplet/dc.sh ps               # wait until every service is healthy
infra/dev-droplet/dc.sh logs -f web      # wait for "Ready in"
```

The API applies `alembic upgrade head` before serving, so a fresh database is
fully migrated. ClamAV downloads signatures on first start and the API waits
for it, so allow a few minutes.

## 7. Verify the boundary

```bash
sudo ss -tlnp | grep -E ':(5432|5433|6379|8000|3001|9000|9001)\b'
```

Only `127.0.0.1:8000` and `127.0.0.1:3001` should appear.
From an allowlisted machine, `https://dev.dhanadhara.com` loads; from any other
network it returns 403.

## 8. Create the first users

The database starts empty. Create one Admin, who must reset the temporary
password at first login:

```bash
infra/dev-droplet/dc.sh exec api uv run python -m app.scripts.seed_admin +91XXXXXXXXXX admin@example.com
```

Optionally load the synthetic demo dataset (`docs/demo-data.md`). Its accounts
use published passwords, so only do this while the allowlist is enforced:

```bash
infra/dev-droplet/dc.sh exec -T api uv run python -m app.scripts.seed_demo --verify
```

Demo media is written to the dev Space, so run `configure_storage` (step 4b)
first.

For volume testing, the bulk dataset adds 251 more accounts (5 Sub Admin
managers with teams, 15 each of Telecallers, Employees and Agents, 195 Clients),
110 listings and records in every workflow state, plus about 30 MB of synthetic
media. It uses the same published password, so the same allowlist rule applies:

```bash
infra/dev-droplet/dc.sh exec -T api uv run python -m app.scripts.seed_bulk --verify
```

## Updating

```bash
cd /opt/dhanadhara && git pull --ff-only
infra/dev-droplet/dc.sh restart api scheduler   # applies new migrations; the scheduler has no hot reload
```

The web app is a production build with no hot reload, so rebuild it after
every pull (the `next build` takes a few minutes; the old container keeps
serving until the new one starts):

```bash
infra/dev-droplet/dc.sh up -d --build web
```

After `uv.lock` changes, also run `infra/dev-droplet/dc.sh up -d --build api scheduler`.

### Moving an existing droplet from `next dev` to the production web build

Once, as `deploy`, then reinstall the Caddyfile (step 5's first command plus
`sudo systemctl reload caddy`) so responses are compressed:

```bash
cd /opt/dhanadhara && git pull --ff-only
git sparse-checkout add packages/contracts
infra/dev-droplet/dc.sh up -d --build web
```

## Starting fresh again

`infra/dev-droplet/dc.sh down -v` deletes every volume (database and ClamAV
signatures). Then `rm .env` and repeat step 4 onward. Re-copy Caddy's
environment file in step 5 if a host value changed.

## Payout test mode

Payouts run in mock mode here (no Razorpay keys), and `compose.droplet.yml`
sets `PAYOUT_GATEWAY_SIMULATOR=true`. Approving a UPI or bank payout therefore
stops at "Initiated" and opens a "Razorpay test payout" dialog where an Admin
picks what the gateway reports (success, failure, bank rejection, or later a
reversal). No real money moves. The API refuses the flag outside
`ENV=development`, and it does nothing once real Razorpay keys are set. The
flag is an environment change, so apply it with
`infra/dev-droplet/dc.sh up -d api scheduler` (recreate), not `restart`.
