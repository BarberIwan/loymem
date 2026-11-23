"""Wallet passes: Apple Wallet (.pkpass) and Google Wallet (save link).

The pass carries the same scan code as the web card, so staff scan it the same
way; it identifies the customer and never grants anything by itself. Both stay
off until the certificates are configured (LOYMEM_WALLET_ENABLED and the keys).

The pass shows the stamp count at the moment it was added. Live updates need the
Apple push service and the Google object API; that comes after the pilot. The
web card stays the place where the count is always current.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import struct
import time
import zipfile
import zlib
from dataclasses import dataclass

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
            "secondaryFields": [{"key": "reward", "label": "", "value": data.reward}],
            "auxiliaryFields": (
                [{"key": "name", "label": "", "value": data.first_name}] if data.first_name else []
            ),
            "backFields": (
                [{"key": "link", "label": data.business_name, "value": data.link_url}]
                if data.link_url
                else []
            ),
        },
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
                    "id": f"{issuer}.{data.serial}",
                    "classId": class_id,
                    "state": "ACTIVE",
                    "accountName": data.first_name or "",
                    "loyaltyPoints": {
                        "label": data.program_name,
                        "balance": {"string": f"{data.stamps} / {data.stamps_required}"},
                    },
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
