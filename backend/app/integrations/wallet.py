"""Wallet passes: Apple Wallet (.pkpass) and Google Wallet (save link).

The pass carries the same scan code as the web card, so staff scan it the same
way; it identifies the customer and never grants anything by itself. Both stay
off until the certificates are configured (LOYMEM_WALLET_ENABLED and the keys).

Live updates: the Apple pass carries a web service URL and a per-pass token, so
the phone registers itself; when the stamps or the balance change we send an
empty push to the phone (APNs, HTTP/2, the pass certificate) and it fetches the
new pass. A Google pass is updated by patching its object through the API.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import ssl
import struct
import tempfile
import time
import zipfile
import zlib
from dataclasses import dataclass

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7

from app.config import get_settings


@dataclass(frozen=True)
class PassData:
    serial: str
    business_name: str
    program_name: str
    first_name: str | None
    stamps: int
    stamps_required: int
    reward: str
    scan_token: str
    background: str
    foreground: str
    link_url: str | None  # never the secret card link: a pass can end up on other servers
    balance: str | None = None  # formatted prepaid balance, when there is one
    web_service_url: str | None = None
    auth_token: str | None = None

    def shown(self) -> dict[str, object]:
        """What the customer sees; a change here is what warrants an update."""
        return {
            "stamps": self.stamps,
            "required": self.stamps_required,
            "reward": self.reward,
            "program": self.program_name,
            "business": self.business_name,
            "name": self.first_name,
            "balance": self.balance,
            "colours": [self.background, self.foreground],
            "link": self.link_url,
        }


def _b64(value: str) -> bytes:
    return base64.b64decode(value) if value else b""


def apple_configured() -> bool:
    s = get_settings()
    return bool(
        s.wallet_enabled
        and s.apple_pass_type_id
        and s.apple_team_id
        and s.apple_pass_cert_pem_b64
        and s.apple_pass_key_pem_b64
        and s.apple_wwdr_pem_b64
    )


def google_configured() -> bool:
    s = get_settings()
    return bool(
        s.wallet_enabled and s.google_wallet_issuer_id and s.google_wallet_service_account_b64
    )


def _rgb(hex_colour: str) -> str:
    h = hex_colour.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(h[i : i + 2], 16) for i in (0, 2, 4)))


def _png(size: int, hex_colour: str) -> bytes:
    """A plain square in the brand colour; Apple requires an icon file."""
    h = hex_colour.lstrip("#")
    pixel = bytes(int(h[i : i + 2], 16) for i in (0, 2, 4))
    raw = b"".join(b"\x00" + pixel * size for _ in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def apple_pass(data: PassData) -> bytes:
    s = get_settings()
    pass_json = {
        "formatVersion": 1,
        "passTypeIdentifier": s.apple_pass_type_id,
        "teamIdentifier": s.apple_team_id,
        "serialNumber": data.serial,
        "organizationName": data.business_name,
        "description": f"{data.business_name} {data.program_name}",
        "logoText": data.business_name,
        "backgroundColor": _rgb(data.background),
        "foregroundColor": _rgb(data.foreground),
        "labelColor": _rgb(data.foreground),
        "storeCard": {
            "primaryFields": [
                {
                    "key": "stamps",
                    "label": data.program_name,
                    "value": f"{data.stamps} / {data.stamps_required}",
                }
            ],
            "secondaryFields": [{"key": "reward", "label": "", "value": data.reward}]
            + (
                [
                    {
                        "key": "balance",
                        "label": "Tegoed",
                        "value": data.balance,
                        "textAlignment": "PKTextAlignmentRight",
                        "changeMessage": "Je tegoed is nu %@",
                    }
                ]
                if data.balance
                else []
            ),
            "auxiliaryFields": (
                [{"key": "name", "label": "", "value": data.first_name}] if data.first_name else []
            ),
            "backFields": (
                [{"key": "link", "label": data.business_name, "value": data.link_url}]
                if data.link_url
                else []
            ),
        },
        **(
            {"webServiceURL": data.web_service_url, "authenticationToken": data.auth_token}
            if data.web_service_url and data.auth_token
            else {}
        ),
        "barcodes": [
            {
                "format": "PKBarcodeFormatQR",
                "message": data.scan_token,
                "messageEncoding": "iso-8859-1",
                "altText": data.scan_token,
            }
        ],
    }
    files = {
        "pass.json": json.dumps(pass_json, ensure_ascii=False).encode(),
        "icon.png": _png(29, data.background),
        "icon@2x.png": _png(58, data.background),
        "logo.png": _png(50, data.background),
    }
    manifest = json.dumps(
        {
            n: hashlib.sha1(b).hexdigest()  # noqa: S324 - required by Apple
            for n, b in files.items()
        }
    ).encode()
    cert = x509.load_pem_x509_certificate(_b64(s.apple_pass_cert_pem_b64))
    key = serialization.load_pem_private_key(_b64(s.apple_pass_key_pem_b64), password=None)
    wwdr = x509.load_pem_x509_certificate(_b64(s.apple_wwdr_pem_b64))
    signature = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(manifest)
        .add_signer(cert, key, hashes.SHA256())  # type: ignore[arg-type]
        .add_certificate(wwdr)
        .sign(
            serialization.Encoding.DER,
            [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary],
        )
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
        z.writestr("manifest.json", manifest)
        z.writestr("signature", signature)
    return out.getvalue()


def _google_points(data: PassData) -> dict[str, object]:
    points: dict[str, object] = {
        "loyaltyPoints": {
            "label": data.program_name,
            "balance": {"string": f"{data.stamps} / {data.stamps_required}"},
        }
    }
    if data.balance:
        points["secondaryLoyaltyPoints"] = {"label": "Tegoed", "balance": {"string": data.balance}}
    return points


def google_object_id(serial: str) -> str:
    return f"{get_settings().google_wallet_issuer_id}.{serial}"


def google_save_url(data: PassData, business_slug: str) -> str:
    s = get_settings()
    account = json.loads(_b64(s.google_wallet_service_account_b64))
    issuer = s.google_wallet_issuer_id
    class_id = f"{issuer}.{business_slug.replace('-', '_')}"
    claims = {
        "iss": account["client_email"],
        "aud": "google",
        "typ": "savetowallet",
        "iat": int(time.time()),
        "payload": {
            "loyaltyClasses": [
                {
                    "id": class_id,
                    "issuerName": data.business_name,
                    "programName": data.program_name,
                    "hexBackgroundColor": data.background,
                    "reviewStatus": "UNDER_REVIEW",
                }
            ],
            "loyaltyObjects": [
                {
                    "id": google_object_id(data.serial),
                    "classId": class_id,
                    "state": "ACTIVE",
                    "accountName": data.first_name or "",
                    **_google_points(data),
                    "barcode": {
                        "type": "QR_CODE",
                        "value": data.scan_token,
                        "alternateText": data.scan_token,
                    },
                    **(
                        {
                            "linksModuleData": {
                                "uris": [{"uri": data.link_url, "description": data.business_name}]
                            }
                        }
                        if data.link_url
                        else {}
                    ),
                }
            ],
        },
    }
    token = jwt.encode(claims, account["private_key"], algorithm="RS256")
    return f"https://pay.google.com/gp/v/save/{token}"


# --- Live updates ------------------------------------------------------------------

APNS_HOST = "https://api.push.apple.com"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
GOOGLE_OBJECTS = "https://walletobjects.googleapis.com/walletobjects/v1/loyaltyObject"


def _apns_context() -> ssl.SSLContext:
    """TLS client context with the pass certificate; APNs authenticates with it."""
    s = get_settings()
    ctx = ssl.create_default_context()
    fd, path = tempfile.mkstemp(suffix=".pem")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_b64(s.apple_pass_cert_pem_b64) + b"\n" + _b64(s.apple_pass_key_pem_b64))
        ctx.load_cert_chain(path)
    finally:
        os.unlink(path)
    return ctx


def apns_push(push_tokens: list[str]) -> list[str]:
    """Tell each phone its pass changed. Returns the tokens Apple says are gone."""
    if not push_tokens:
        return []
    topic = get_settings().apple_pass_type_id
    gone: list[str] = []
    with httpx.Client(http2=True, verify=_apns_context(), timeout=10) as c:
        for token in push_tokens:
            r = c.post(
                f"{APNS_HOST}/3/device/{token}",
                content=b"{}",
                headers={"apns-topic": topic},  # Wallet ignores the payload; {} is enough
            )
            if r.status_code == 410 or (r.status_code == 400 and "BadDeviceToken" in r.text):
                gone.append(token)
            elif r.status_code >= 400:
                raise RuntimeError(f"apns {r.status_code}: {r.text[:200]}")
    return gone


def _google_access_token() -> str:
    account = json.loads(_b64(get_settings().google_wallet_service_account_b64))
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": account["client_email"],
            "scope": "https://www.googleapis.com/auth/wallet_object.issuer",
            "aud": GOOGLE_TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        account["private_key"],
        algorithm="RS256",
    )
    r = httpx.post(
        GOOGLE_TOKEN_URL,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        timeout=10,
    )
    r.raise_for_status()
    return str(r.json()["access_token"])


def google_update(updates: list[PassData]) -> int:
    """Patch the points on saved Google passes. A pass never saved is skipped."""
    if not updates:
        return 0
    headers = {"Authorization": f"Bearer {_google_access_token()}"}
    done = 0
    with httpx.Client(timeout=10, headers=headers) as c:
        for data in updates:
            r = c.patch(
                f"{GOOGLE_OBJECTS}/{google_object_id(data.serial)}", json=_google_points(data)
            )
            if r.status_code == 404:
                continue  # the customer opened the save link but never saved
            r.raise_for_status()
            done += 1
    return done
