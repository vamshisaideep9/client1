# Development droplet

Status: **development/staging only — never production, customer, or KYC data**

This runs the development stack (`docker-compose.yml` + `docker-compose.dev.yml`)
on one DigitalOcean droplet so the team can review work over HTTPS. The
production topology, images, and launch gates are separate:
`docker-compose.prod.example.yml` and `docs/agent-context/pre-deployment-checklist.md`.

What this directory adds:

| File | Purpose |
| --- | --- |
| `compose.droplet.yml` | Removes datastore ports, binds the proxied ports to `127.0.0.1`, injects fresh credentials and public HTTPS origins, and adds restart policies. |
| `Caddyfile` | Host HTTPS proxy with automatic certificates and an IP allowlist. |
| `init-env.sh` | Writes the repository-root `.env` with fresh random credentials. |
| `dc.sh` | `docker compose` with the three files in the right order. |

The droplet checks out only the paths the stack needs (sparse checkout); docs,
tests, contracts, and tooling stay off the server.

## 1. Create the droplet

- Ubuntu 24.04 x64, **4 vCPU / 8 GB** (the dev servers and ClamAV need more
  memory than the compact production build), region BLR1, SSH-key login only.
- Cloud Firewall inbound: TCP 22 from your IP only; TCP 80 and 443 from
  anywhere so Let's Encrypt can validate. Caddy returns 403 to every address
  outside the allowlist. Nothing else is opened.
- DNS `A` records for the app host `dev.dhanadhara.com` and the files host
  `files.dev.dhanadhara.com` pointing at the droplet. The apex
  `dhanadhara.com` and `www` stay reserved for production; never point them
  at this server.

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
git sparse-checkout set apps/api apps/web apps/media-runtime infra/dev-droplet
```

Cone mode also keeps the root files, which include the two compose files.

## 4. Generate fresh configuration

```bash
cd /opt/dhanadhara
infra/dev-droplet/init-env.sh \
  --domain dev.dhanadhara.com \
  --files-domain files.dev.dhanadhara.com \
  --droplet-ip "$(ip -4 -o addr show dev eth0 | awk '{print $4}' | cut -d/ -f1 | head -n1)" \
  --allow-ip 203.0.113.10 --allow-ip 198.51.100.0/24
```

This writes `.env` (mode 600) with a new database password, MinIO keys, and JWT
secret, and creates an empty `apps/api/.env.local` for optional API settings
such as `EMAIL_ENABLED=true` with the `SMTP_*` values.

`ENV=development` returns one-time codes in API responses by design, so testers
can sign in without SMS or email delivery. Anyone who can reach the API can do
the same, which is why the Caddy IP allowlist is this server's access boundary:
never remove it, and never point real users at this host.

## 5. Configure Caddy

```bash
sudo install -m 0644 infra/dev-droplet/Caddyfile /etc/caddy/Caddyfile
grep -E '^DEV_(DOMAIN|FILES_DOMAIN|ALLOWED_IPS|DROPLET_IP)=' .env \
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
infra/dev-droplet/dc.sh config --quiet   # fails if .env is missing a value
infra/dev-droplet/dc.sh up -d --build
infra/dev-droplet/dc.sh ps               # wait until every service is healthy
infra/dev-droplet/dc.sh logs -f web      # first start installs packages; wait for "Ready in"
```

The API applies `alembic upgrade head` before serving, so a fresh database is
fully migrated. ClamAV downloads signatures on first start and the API waits
for it, so allow a few minutes.

## 7. Verify the boundary

```bash
sudo ss -tlnp | grep -E ':(5432|5433|6379|8000|3001|9000|9001)\b'
```

Only `127.0.0.1:8000`, `127.0.0.1:3001`, and `127.0.0.1:9000` should appear.
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

## Updating

```bash
cd /opt/dhanadhara && git pull --ff-only
infra/dev-droplet/dc.sh restart api scheduler   # applies new migrations; the scheduler has no hot reload
```

The web dev server reloads by itself. After `uv.lock` or `pnpm-lock.yaml`
changes, run `infra/dev-droplet/dc.sh up -d --build api scheduler web`.

## Starting fresh again

`infra/dev-droplet/dc.sh down -v` deletes every volume (database, MinIO,
signatures). Then `rm .env` and repeat step 4 onward. Re-copy Caddy's
environment file in step 5 if a host value changed.
