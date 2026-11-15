"""Contract tests for the internet-facing development droplet overlay."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DROPLET = ROOT / "infra/dev-droplet"

SERVICE_RE = re.compile(r"^  ([a-z0-9-]+):\s*$")
# Resolve through PATH explicitly: on Windows, CreateProcess("bash") would pick
# System32's WSL launcher ahead of Git Bash.
BASH = shutil.which("bash")


def service_blocks(text: str) -> dict[str, list[str]]:
    """Split the top-level ``services:`` mapping into per-service line lists."""

    blocks: dict[str, list[str]] = {}
    current: str | None = None
    in_services = False
    for line in text.splitlines():
        if line.startswith("services:"):
            in_services = True
            continue
        if in_services and line and not line.startswith((" ", "#")):
            in_services = False
            current = None
        if not in_services:
            continue
        match = SERVICE_RE.match(line)
        if match:
            current = match.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return blocks


def port_entries(lines: list[str]) -> tuple[str | None, list[str]]:
    """Return the ``ports:`` header remainder and its list items."""

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("ports:"):
            header = stripped[len("ports:") :].strip()
            items: list[str] = []
            for item in lines[index + 1 :]:
                item_stripped = item.strip()
                if not item_stripped.startswith("- "):
                    break
                items.append(item_stripped[2:].strip().strip('"'))
            return header, items
    return None, []


def has_restart(lines: list[str]) -> bool:
    return any(line.strip().startswith("restart:") for line in lines)


class DevDropletComposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = service_blocks((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        self.dev = service_blocks((ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8"))
        self.droplet = service_blocks(
            (DROPLET / "compose.droplet.yml").read_text(encoding="utf-8")
        )

    def test_overlay_only_names_existing_services(self) -> None:
        self.assertTrue(set(self.droplet) <= set(self.base))

    def test_every_published_port_is_removed_or_loopback_only(self) -> None:
        published = {name for name, lines in self.base.items() if port_entries(lines)[0] is not None}
        self.assertTrue(published, "base compose should publish development ports")
        loopback_only = {"api": {"127.0.0.1:8000:8000"}, "web": {"127.0.0.1:3001:3000"}}
        for name in published:
            with self.subTest(service=name):
                header, items = port_entries(self.droplet.get(name, []))
                if name in loopback_only:
                    self.assertEqual(header, "!override")
                    self.assertEqual(set(items), loopback_only[name])
                else:
                    self.assertEqual(header, "!reset []")
                    self.assertEqual(items, [])

    def test_object_storage_never_starts_and_nothing_waits_for_it(self) -> None:
        # minio/minio and minio/mc are no longer published; the droplet must
        # not try to pull or depend on them.
        for name in ("minio", "minio-init"):
            with self.subTest(service=name):
                self.assertIn('profiles: ["object-storage"]', "\n".join(self.droplet[name]))
        api = "\n".join(self.droplet["api"])
        self.assertIn("depends_on: !override", api)
        self.assertNotIn("minio", api)
        for name, lines in {**self.base, **self.dev}.items():
            if name in ("minio", "minio-init", "api"):
                continue
            with self.subTest(dependent=name):
                self.assertNotRegex("\n".join(lines), r"^\s+minio:\s*$")

    def test_object_storage_is_a_required_space_reachable_by_browsers(self) -> None:
        text = (DROPLET / "compose.droplet.yml").read_text(encoding="utf-8")
        anchor = text.split("x-droplet-api-env:", 1)[1].split("\nservices:", 1)[0]
        # Every storage setting must come from .env and fail loudly when
        # missing -- never a committed endpoint, bucket, or credential.
        for variable in (
            "SPACES_ENDPOINT_URL",
            "SPACES_REGION",
            "SPACES_BUCKET",
            "SPACES_ACCESS_KEY",
            "SPACES_SECRET_KEY",
        ):
            with self.subTest(variable=variable):
                self.assertRegex(anchor, rf"(?m)^  {variable}: \$\{{{variable}\?")
        # docker-compose.dev.yml points browsers at MinIO's localhost:9000;
        # the droplet must clear it so presigned URLs use the Space itself.
        self.assertIn("localhost:9000", "\n".join(self.dev["api"]))
        self.assertRegex(anchor, r'(?m)^  SPACES_PUBLIC_ENDPOINT_URL: ""$')
        # Spaces has no bucket policies; public/ reads come from object ACLs.
        self.assertRegex(anchor, r'(?m)^  SPACES_PUBLIC_OBJECT_ACL: "true"$')
        self.assertNotRegex(text, r"digitaloceanspaces\.com")
        # The web CSP and image allowlist trust exactly the Space origin.
        self.assertIn(
            "NEXT_PUBLIC_ASSET_HOST: ${SPACES_ENDPOINT_URL?", "\n".join(self.droplet["web"])
        )

    def test_long_running_services_restart_after_reboot(self) -> None:
        for name in self.base:
            if name in ("minio", "minio-init"):
                continue
            with self.subTest(service=name):
                self.assertTrue(
                    has_restart(self.base[name])
                    or has_restart(self.dev.get(name, []))
                    or has_restart(self.droplet.get(name, [])),
                )

    def test_credentials_come_from_required_variables(self) -> None:
        overlay = "\n".join(
            line
            for line in (DROPLET / "compose.droplet.yml").read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        for variable in ("DEV_SECRET_KEY", "POSTGRES_PASSWORD", "DEV_DOMAIN"):
            with self.subTest(variable=variable):
                self.assertIn(f"${{{variable}?", overlay)
        self.assertNotIn("minioadmin", overlay)
        self.assertNotRegex(overlay, r"app:app@")
        # Both API processes receive the same credentials and origins.
        for name in ("api", "scheduler"):
            self.assertIn("<<: *droplet-api-env", "\n".join(self.droplet[name]))
        self.assertIn('TRUST_PROXY_HEADERS: "true"', overlay)
        self.assertNotIn("OTP_EXPOSE_HINT", overlay)


class DevDropletCaddyTests(unittest.TestCase):
    def test_every_site_denies_non_allowlisted_clients_first(self) -> None:
        caddyfile = (DROPLET / "Caddyfile").read_text(encoding="utf-8")
        sites = re.findall(r"^(\{\$DEV_[A-Z_]+\}) \{\n(.*?)^\}", caddyfile, re.MULTILINE | re.DOTALL)
        self.assertEqual([site for site, _ in sites], ["{$DEV_DOMAIN}"])
        self.assertNotIn(":9000", caddyfile)
        for site, body in sites:
            with self.subTest(site=site):
                directives = [
                    line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith("#")
                ]
                # Caddy reorders site-level directives (handle runs before
                # respond); only a route block preserves the allowlist-first order.
                self.assertEqual(directives[0], "route {")
                self.assertEqual(directives[-1], "}")
                self.assertTrue(directives[1].startswith("@outsiders not remote_ip {$DEV_ALLOWED_IPS}"))
                self.assertEqual(directives[2], "respond @outsiders 403")
                self.assertNotIn("handle", body)
                self.assertNotIn("private_ranges", body)
                self.assertNotIn("/0", body)
                self.assertNotIn("basic_auth", body)


@unittest.skipUnless(BASH and shutil.which("openssl"), "bash and openssl required")
class DevDropletInitEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "infra/dev-droplet").mkdir(parents=True)
        (self.root / "apps/api").mkdir(parents=True)
        shutil.copy(DROPLET / "init-env.sh", self.root / "infra/dev-droplet/init-env.sh")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_init(self, *allow: str) -> subprocess.CompletedProcess[str]:
        args = [
            str(BASH),
            "infra/dev-droplet/init-env.sh",
            "--domain",
            "dev.example.com",
        ]
        for value in allow:
            args += ["--allow-ip", value]
        return subprocess.run(args, cwd=self.root, capture_output=True, text=True, check=False)

    def test_writes_fresh_unique_credentials_once(self) -> None:
        result = self.run_init("203.0.113.10", "198.51.100.0/24")
        self.assertEqual(result.returncode, 0, result.stderr)
        env = dict(
            line.split("=", 1)
            for line in (self.root / ".env").read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        )
        self.assertEqual(env["DEV_DOMAIN"], "dev.example.com")
        self.assertEqual(env["DEV_ALLOWED_IPS"], '"203.0.113.10 198.51.100.0/24"')
        secrets = [env[key] for key in ("POSTGRES_PASSWORD", "DEV_SECRET_KEY")]
        for value in secrets:
            self.assertRegex(value, r"^[0-9a-f]{64}$")
        self.assertEqual(len(set(secrets)), 2)
        self.assertNotIn("SPACES_ACCESS_KEY", env)
        self.assertTrue((self.root / "apps/api/.env.local").exists())

        before = (self.root / ".env").read_bytes()
        again = self.run_init("203.0.113.10")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already exists", again.stderr)
        self.assertEqual((self.root / ".env").read_bytes(), before)

    def test_rejects_allow_all_and_missing_allowlist(self) -> None:
        for value in ("0.0.0.0/0", "::/0", "10.0.0.0/0"):
            with self.subTest(value=value):
                result = self.run_init(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / ".env").exists())
        self.assertEqual(self.run_init().returncode, 2)
        self.assertFalse((self.root / ".env").exists())


if __name__ == "__main__":
    unittest.main()
