"""Phase 1f: wallet passes, with throwaway certificates generated in the test."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import jwt

from tests.conftest import Api, Shop, card, signup


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
