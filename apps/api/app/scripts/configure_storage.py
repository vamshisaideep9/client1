"""Apply and verify the object-storage bucket posture (DigitalOcean Spaces).

Locally, docker-compose's `minio-init` creates the bucket and grants anonymous
read on `public/` only, and MinIO's CORS comes from an environment variable.
A DigitalOcean Space needs the same two things set on the bucket itself:

  * a CORS rule, because browsers POST/PUT presigned uploads straight to the
    Space from the web origin (services/storage.py) -- exact origins only;
  * anonymous read on `public/` and nothing else (no listing), so
    banner/property images render while KYC and task documents stay behind
    short-lived signed URLs. MinIO gets this from a bucket policy on
    `{bucket}/public/*`. DigitalOcean Spaces refuses bucket policies (403
    even for a full-access key), so with SPACES_PUBLIC_OBJECT_ACL=true the
    app grants it per object instead and --apply sets only CORS.

Create the Space in the DigitalOcean console first (file listing Restricted,
CDN off) with a key scoped to that Space only, put the SPACES_* values in the
environment, then run inside the api container:

    uv run python -m app.scripts.configure_storage --apply --verify

--verify writes three throwaway probe objects through the app's ACL rule,
checks them with anonymous, unsigned HTTP requests against the
browser-facing endpoint, deletes them, and
prints the production evidence booleans (infra/production-environment).
Output never contains credentials. Exit status is non-zero on any failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import quote, urlsplit

from botocore.exceptions import BotoCoreError, ClientError

PUBLIC_PREFIX = "public/"
_PROBE_DIR = "storage-probe"
_PROBE_BODY = b"dhanadhara storage posture probe\n"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1"}
_HTTP_TIMEOUT_SECONDS = 10
_UNTRUSTED_ORIGIN = "https://untrusted-origin.invalid"

# (method, url, headers) -> (status, lower-cased response headers)
HttpCall = Callable[[str, str, dict[str, str]], tuple[int, dict[str, str]]]


def validate_origins(origins: Iterable[str], *, environment: str) -> list[str]:
    """Exact browser origins allowed to upload, deduplicated in order.

    A wildcard would let any site drive uploads with a leaked presigned URL,
    and plain http is accepted only for loopback in development.
    """
    result: list[str] = []
    for raw in origins:
        origin = raw.strip()
        parts = urlsplit(origin)
        if (
            "*" in origin
            or parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.path
            or parts.query
            or parts.fragment
        ):
            raise ValueError(f"CORS origin must be an exact http(s) origin: {origin!r}")
        if parts.scheme == "http" and not (
            environment == "development" and parts.hostname in _LOOPBACK_HOSTS
        ):
            raise ValueError(f"CORS origin must use https outside local development: {origin!r}")
        if origin not in result:
            result.append(origin)
    if not result:
        raise ValueError("At least one CORS origin is required.")
    return result


def build_cors_configuration(origins: list[str]) -> dict[str, Any]:
    return {
        "CORSRules": [
            {
                "AllowedOrigins": list(origins),
                "AllowedMethods": ["GET", "HEAD", "PUT", "POST"],
                "AllowedHeaders": ["*"],
                "ExposeHeaders": ["ETag"],
                "MaxAgeSeconds": 3000,
            }
        ]
    }


def build_public_read_policy(bucket: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PublicPrefixReadOnly",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/{PUBLIC_PREFIX}*"],
                }
            ],
        },
        separators=(",", ":"),
    )


def apply_posture(
    client: Any, *, bucket: str, origins: list[str], bucket_policy: bool = True
) -> None:
    """CORS always; the `public/*` bucket policy only where the provider
    supports one. DigitalOcean Spaces refuses bucket policies, so there
    SPACES_PUBLIC_OBJECT_ACL grants the same read per object instead."""
    client.put_bucket_cors(Bucket=bucket, CORSConfiguration=build_cors_configuration(origins))
    if bucket_policy:
        client.put_bucket_policy(Bucket=bucket, Policy=build_public_read_policy(bucket))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def anonymous_request(method: str, url: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
    """Unsigned request, exactly as an anonymous browser/visitor would send it."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method=method, headers=headers)
    try:
        with opener.open(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}


def verify_posture(
    client: Any,
    *,
    bucket: str,
    public_endpoint: str,
    origin: str,
    http: HttpCall = anonymous_request,
    acl_for: Callable[[str], dict[str, str]] = lambda _key: {},
) -> dict[str, bool]:
    """Probe the live bucket anonymously and return named pass/fail checks.

    `acl_for` is the application's own per-key ACL rule (storage._public_acl),
    so the probes are written exactly as real uploads are: the check covers
    the boundary the app enforces, not just the bucket's static settings.
    """
    bucket_url = f"{public_endpoint.rstrip('/')}/{quote(bucket)}"
    token = uuid.uuid4().hex
    private_key = f"private/{_PROBE_DIR}/{token}.txt"
    public_key = f"{PUBLIC_PREFIX}{_PROBE_DIR}/{token}.txt"
    # Shares the bare string prefix "public" but not the "public/" directory:
    # a policy written as `public*` instead of `public/*` would expose it.
    lookalike_key = f"{PUBLIC_PREFIX.rstrip('/')}{_PROBE_DIR}/{token}.txt"
    written: list[str] = []
    try:
        for key in (private_key, lookalike_key, public_key):
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=_PROBE_BODY,
                ContentType="text/plain",
                **acl_for(key),
            )
            written.append(key)

        listing_status, _ = http("GET", f"{bucket_url}/?list-type=2", {})
        private_status, _ = http("GET", f"{bucket_url}/{quote(private_key)}", {})
        lookalike_status, _ = http("GET", f"{bucket_url}/{quote(lookalike_key)}", {})
        public_status, _ = http("GET", f"{bucket_url}/{quote(public_key)}", {})

        def preflight(from_origin: str) -> str | None:
            _, headers = http(
                "OPTIONS",
                f"{bucket_url}/{quote(private_key)}",
                {"Origin": from_origin, "Access-Control-Request-Method": "POST"},
            )
            return headers.get("access-control-allow-origin")

        allowed_header = preflight(origin)
        untrusted_header = preflight(_UNTRUSTED_ORIGIN)
    finally:
        for key in written:
            try:
                client.delete_object(Bucket=bucket, Key=key)
            except (BotoCoreError, ClientError):
                print(f"warning: could not delete probe object {key}", file=sys.stderr)

    private_denied = private_status in (401, 403)
    return {
        "storage_listing_denied": listing_status in (401, 403),
        "private_object_anonymous_access_denied": private_denied,
        "public_object_prefix_only_verified": (
            public_status == 200 and private_denied and lookalike_status in (401, 403)
        ),
        "cors_upload_origin_allowed": allowed_header == origin,
        "cors_untrusted_origin_rejected": untrusted_header not in (_UNTRUSTED_ORIGIN, "*"),
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="set bucket CORS and policy")
    parser.add_argument("--verify", action="store_true", help="probe the live posture")
    parser.add_argument(
        "--origin",
        action="append",
        default=None,
        help="browser origin allowed to upload (repeatable); "
        "defaults to PUBLIC_WEB_ORIGIN plus ALLOWED_ORIGINS",
    )
    args = parser.parse_args(argv)
    if not (args.apply or args.verify):
        parser.error("choose --apply, --verify, or both")
    return args


def main(argv: list[str] | None = None) -> int:
    from app.core.config import settings
    from app.services import storage

    args = _parse_args(argv)
    try:
        origins = validate_origins(
            args.origin or [settings.PUBLIC_WEB_ORIGIN, *settings.ALLOWED_ORIGINS],
            environment=settings.ENV,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    bucket = settings.SPACES_BUCKET
    public_endpoint = storage._public_endpoint()
    client = storage._client(settings.SPACES_ENDPOINT_URL)
    print(f"bucket={bucket} endpoint={urlsplit(public_endpoint).netloc} origins={origins}")

    try:
        object_acl = settings.SPACES_PUBLIC_OBJECT_ACL
        if args.apply:
            apply_posture(client, bucket=bucket, origins=origins, bucket_policy=not object_acl)
            print(
                "applied: CORS rule; public/ read via per-object ACL"
                if object_acl
                else "applied: CORS rule and public/* read-only policy"
            )
        if args.verify:
            results = verify_posture(
                client,
                bucket=bucket,
                public_endpoint=public_endpoint,
                origin=origins[0],
                acl_for=storage._public_acl,
            )
            print(json.dumps(results, indent=2, sort_keys=True))
            if not all(results.values()):
                print("error: storage posture verification failed", file=sys.stderr)
                return 1
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "unknown")
        print(f"error: storage rejected the request ({code})", file=sys.stderr)
        return 1
    except (BotoCoreError, urllib.error.URLError) as exc:
        print(f"error: storage unreachable ({type(exc).__name__})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
