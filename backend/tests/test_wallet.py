"""Phase 1f: wallet passes, with throwaway certificates generated in the test."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.config import get_settings
from tests.conftest import Api, Shop, card, signup


def _cert() -> tuple[bytes, bytes, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "toets")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        key,
    )


@pytest.fixture
def wallet_keys(monkeypatch: pytest.MonkeyPatch) -> rsa.RSAPrivateKey:
    s = get_settings()
    cert, key, raw = _cert()
    wwdr, _, _ = _cert()
    b64 = lambda v: base64.b64encode(v).decode()  # noqa: E731
    account = {"client_email": "pas@toets.example", "private_key": key.decode()}
    for name, value in {
        "wallet_enabled": True,
        "apple_pass_type_id": "pass.example.toets",
        "apple_team_id": "TEAM123456",
        "apple_pass_cert_pem_b64": b64(cert),
        "apple_pass_key_pem_b64": b64(key),
        "apple_wwdr_pem_b64": b64(wwdr),
        "google_wallet_issuer_id": "3388000000000000000",
        "google_wallet_service_account_b64": b64(json.dumps(account).encode()),
    }.items():
        monkeypatch.setattr(s, name, value)
    return raw


def test_wallet_is_off_without_certificates(api: Api, shop: Shop) -> None:
    secret = signup(api, shop.business.slug)
    assert card(api, shop.business.slug, secret)["wallet"] == {"apple": False, "google": False}
    assert (
        api.get(f"/api/v1/public/{shop.business.slug}/card/{secret}/wallet/apple").status_code
        == 404
    )


def test_apple_pass_is_signed_and_carries_only_the_scan_code(
    api: Api, shop: Shop, wallet_keys: object
) -> None:
    secret = signup(api, shop.business.slug, first_name="Sam")
    view = card(api, shop.business.slug, secret)
    assert view["wallet"] == {"apple": True, "google": True}
    r = api.get(f"/api/v1/public/{shop.business.slug}/card/{secret}/wallet/apple")
    assert r.status_code == 200 and r.headers["content-type"] == "application/vnd.apple.pkpass"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert {"pass.json", "manifest.json", "signature", "icon.png"} <= set(z.namelist())
    manifest = json.loads(z.read("manifest.json"))
    for name, digest in manifest.items():
        assert hashlib.sha1(z.read(name)).hexdigest() == digest  # noqa: S324
    pass_json = json.loads(z.read("pass.json"))
    assert pass_json["barcodes"][0]["message"] == view["scan_token"]
    assert secret not in z.read("pass.json").decode()


def test_google_save_link_is_signed(api: Api, shop: Shop, wallet_keys: object) -> None:
    secret = signup(api, shop.business.slug)
    r = api.get(f"/api/v1/public/{shop.business.slug}/card/{secret}/wallet/google")
    token = r.json()["url"].rsplit("/", 1)[-1]
    key = wallet_keys
    assert hasattr(key, "public_key")
    claims = jwt.decode(token, key.public_key(), algorithms=["RS256"], audience="google")  # type: ignore[attr-defined]
    obj = claims["payload"]["loyaltyObjects"][0]
    assert obj["barcode"]["value"] == card(api, shop.business.slug, secret)["scan_token"]
    assert secret not in json.dumps(claims)
