"""app/scripts/configure_storage.py -- bucket CORS/policy builders, origin
validation, and the anonymous posture probe, all without network access."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.scripts import configure_storage as cs

_ENDPOINT = "https://blr1.digitaloceanspaces.com"
_ORIGIN = "https://dev.dhanadhara.com"


def test_policy_grants_anonymous_get_on_public_prefix_only() -> None:
    policy = json.loads(cs.build_public_read_policy("dhanadhara-dev"))
    assert len(policy["Statement"]) == 1
    statement = policy["Statement"][0]
    assert statement["Effect"] == "Allow"
    assert statement["Principal"] == "*"
    # Never ListBucket, never a bare-prefix or whole-bucket resource.
    assert statement["Action"] == ["s3:GetObject"]
    assert statement["Resource"] == ["arn:aws:s3:::dhanadhara-dev/public/*"]


def test_cors_rule_uses_exact_origins_and_upload_methods() -> None:
    config = cs.build_cors_configuration([_ORIGIN])
    (rule,) = config["CORSRules"]
    assert rule["AllowedOrigins"] == [_ORIGIN]
    assert set(rule["AllowedMethods"]) == {"GET", "HEAD", "PUT", "POST"}
    assert rule["ExposeHeaders"] == ["ETag"]


def test_validate_origins_dedupes_in_order() -> None:
    assert cs.validate_origins(
        [_ORIGIN, " https://www.example.com ", _ORIGIN], environment="production"
    ) == [_ORIGIN, "https://www.example.com"]


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "dev.dhanadhara.com",
        "https://dev.dhanadhara.com/",
        "https://dev.dhanadhara.com/path",
        "https://user@dev.dhanadhara.com",
        "ftp://dev.dhanadhara.com",
        "http://dev.dhanadhara.com",
    ],
)
def test_validate_origins_rejects_non_exact_or_insecure(origin: str) -> None:
    with pytest.raises(ValueError):
        cs.validate_origins([origin], environment="development")


def test_validate_origins_allows_http_loopback_only_in_development() -> None:
    assert cs.validate_origins(["http://localhost:3001"], environment="development") == [
        "http://localhost:3001"
    ]
    with pytest.raises(ValueError):
        cs.validate_origins(["http://localhost:3001"], environment="production")


def test_validate_origins_requires_one() -> None:
    with pytest.raises(ValueError):
        cs.validate_origins([], environment="production")


def test_apply_sets_cors_and_policy_on_the_bucket() -> None:
    client = MagicMock()
    cs.apply_posture(client, bucket="dhanadhara-dev", origins=[_ORIGIN])
    client.put_bucket_cors.assert_called_once_with(
        Bucket="dhanadhara-dev", CORSConfiguration=cs.build_cors_configuration([_ORIGIN])
    )
    client.put_bucket_policy.assert_called_once_with(
        Bucket="dhanadhara-dev", Policy=cs.build_public_read_policy("dhanadhara-dev")
    )


def test_apply_skips_bucket_policy_in_object_acl_mode() -> None:
    client = MagicMock()
    cs.apply_posture(client, bucket="b", origins=[_ORIGIN], bucket_policy=False)
    client.put_bucket_cors.assert_called_once()
    client.put_bucket_policy.assert_not_called()


def test_verify_writes_probes_through_the_app_acl_rule() -> None:
    client = MagicMock()
    http, _ = _fake_http()

    def acl_for(key: str) -> dict[str, str]:
        return {"ACL": "public-read"} if key.startswith("public/") else {}

    cs.verify_posture(
        client, bucket="b", public_endpoint=_ENDPOINT, origin=_ORIGIN, http=http, acl_for=acl_for
    )
    acls = {c.kwargs["Key"]: c.kwargs.get("ACL") for c in client.put_object.call_args_list}
    assert [acl for key, acl in acls.items() if key.startswith("public/")] == ["public-read"]
    # The private probe and the `public` look-alike are written without one.
    assert all(acl is None for key, acl in acls.items() if not key.startswith("public/"))


def _fake_http(
    *,
    listing: int = 403,
    private: int = 403,
    lookalike: int = 403,
    public: int = 200,
    cors_echo: bool = True,
) -> tuple[cs.HttpCall, list[tuple[str, str, dict[str, str]]]]:
    calls: list[tuple[str, str, dict[str, str]]] = []

    def http(method: str, url: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
        calls.append((method, url, headers))
        if method == "OPTIONS":
            origin = headers["Origin"]
            if cors_echo and origin == _ORIGIN:
                return 200, {"access-control-allow-origin": origin}
            return 403, {}
        if "list-type" in url:
            return listing, {}
        if "/public/" in url:
            return public, {}
        if "/publicstorage-probe/" in url:
            return lookalike, {}
        return private, {}

    return http, calls


def test_verify_passes_for_a_correct_posture_and_cleans_up() -> None:
    client = MagicMock()
    http, calls = _fake_http()
    results = cs.verify_posture(
        client, bucket="dhanadhara-dev", public_endpoint=_ENDPOINT, origin=_ORIGIN, http=http
    )
    assert results == {
        "storage_listing_denied": True,
        "private_object_anonymous_access_denied": True,
        "public_object_prefix_only_verified": True,
        "cors_upload_origin_allowed": True,
        "cors_untrusted_origin_rejected": True,
    }
    written = [c.kwargs["Key"] for c in client.put_object.call_args_list]
    deleted = [c.kwargs["Key"] for c in client.delete_object.call_args_list]
    assert sorted(written) == sorted(deleted)
    assert any(key.startswith("private/") for key in written)
    assert any(key.startswith("public/") for key in written)
    # Every anonymous probe targets the browser-facing path-style bucket URL
    # and carries no credentials.
    for _method, url, headers in calls:
        assert url.startswith(f"{_ENDPOINT}/dhanadhara-dev/")
        assert "Authorization" not in headers


@pytest.mark.parametrize(
    ("overrides", "failed"),
    [
        ({"listing": 200}, {"storage_listing_denied"}),
        (
            {"private": 200},
            {"private_object_anonymous_access_denied", "public_object_prefix_only_verified"},
        ),
        ({"public": 403}, {"public_object_prefix_only_verified"}),
        # A bare-prefix `public*` grant leaks look-alike keys.
        ({"lookalike": 200}, {"public_object_prefix_only_verified"}),
        ({"cors_echo": False}, {"cors_upload_origin_allowed"}),
    ],
)
def test_verify_reports_each_broken_control(overrides: dict, failed: set[str]) -> None:
    http, _ = _fake_http(**overrides)
    results = cs.verify_posture(
        MagicMock(), bucket="b", public_endpoint=_ENDPOINT, origin=_ORIGIN, http=http
    )
    assert {name for name, ok in results.items() if not ok} == failed


def test_verify_flags_wildcard_cors() -> None:
    def http(method: str, url: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
        if method == "OPTIONS":
            return 200, {"access-control-allow-origin": "*"}
        return (200 if "/public/" in url else 403), {}

    results = cs.verify_posture(
        MagicMock(), bucket="b", public_endpoint=_ENDPOINT, origin=_ORIGIN, http=http
    )
    assert results["cors_untrusted_origin_rejected"] is False


def test_verify_deletes_probes_even_when_a_probe_request_fails() -> None:
    client = MagicMock()

    def http(method: str, url: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
        raise OSError("network down")

    with pytest.raises(OSError):
        cs.verify_posture(client, bucket="b", public_endpoint=_ENDPOINT, origin=_ORIGIN, http=http)
    assert client.delete_object.call_count == 3


def test_main_requires_an_action() -> None:
    with pytest.raises(SystemExit):
        cs.main([])
