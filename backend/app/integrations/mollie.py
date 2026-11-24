"""Mollie Connect: OAuth to the business's own Mollie account, payments in it.

Mollie webhooks carry only a payment id and are not signed; the status is
always read back from the Mollie API with the business's own token, so a forged
call can at most make us look a payment up.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.integrations.payments import NewPayment, PaymentInfo, Tokens

SCOPES = "payments.read payments.write customers.read customers.write mandates.read profiles.read"


class MollieProvider:
    name = "mollie"

    def __init__(self) -> None:
        s = get_settings()
        self.client_id, self.client_secret = s.mollie_client_id, s.mollie_client_secret
        self.api, self.oauth = s.mollie_api_base, s.mollie_oauth_base
        self.testmode = s.environment != "production"

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        q = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": SCOPES,
                "response_type": "code",
                "approval_prompt": "auto",
            }
        )
        return f"https://my.mollie.com/oauth2/authorize?{q}"

    def _tokens(self, data: dict[str, str]) -> Tokens:
        r = httpx.post(
            f"{self.oauth}/tokens", data=data, auth=(self.client_id, self.client_secret), timeout=15
        )
        r.raise_for_status()
        body = r.json()
        return Tokens(
            body["access_token"],
            body["refresh_token"],
            datetime.now(UTC) + timedelta(seconds=int(body["expires_in"]) - 60),
        )

    def exchange_code(self, code: str, redirect_uri: str) -> Tokens:
        return self._tokens(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        )

    def refresh(self, refresh_token: str) -> Tokens:
        return self._tokens({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def _client(self, token: str) -> httpx.Client:
        return httpx.Client(
            base_url=self.api, timeout=15, headers={"Authorization": f"Bearer {token}"}
        )

    def create_payment(
        self,
        access_token: str,
        *,
        amount_cents: int,
        description: str,
        sequence: str,
        redirect_url: str,
        webhook_url: str,
        metadata: dict[str, str],
        customer_id: str | None = None,
        mandate_id: str | None = None,
    ) -> NewPayment:
        with self._client(access_token) as c:
            profile = c.get("/profiles/me").json()["id"]
            body: dict[str, object] = {
                "amount": {"currency": "EUR", "value": f"{amount_cents / 100:.2f}"},
                "description": description[:255],
                "redirectUrl": redirect_url,
                "webhookUrl": webhook_url,
                "metadata": metadata,
                "sequenceType": sequence,
                "profileId": profile,
                "testmode": self.testmode,
            }
            if sequence == "first" and customer_id is None:
                cust = c.post("/customers", json={"testmode": self.testmode}).json()
                customer_id = cust["id"]
            if customer_id:
                body["customerId"] = customer_id
            if mandate_id:
                body["mandateId"] = mandate_id
            r = c.post("/payments", json=body)
            r.raise_for_status()
            p = r.json()
            return NewPayment(p["id"], (p.get("_links", {}).get("checkout") or {}).get("href"))

    def get_payment(self, access_token: str, payment_id: str) -> PaymentInfo:
        with self._client(access_token) as c:
            r = c.get(f"/payments/{payment_id}", params={"testmode": str(self.testmode).lower()})
            r.raise_for_status()
            p = r.json()
        cents = round(float(p["amount"]["value"]) * 100)
        return PaymentInfo(
            p["id"],
            p["status"],
            cents,
            p.get("customerId"),
            p.get("mandateId"),
            p.get("metadata") or {},
        )

    def refund(
        self, access_token: str, payment_id: str, amount_cents: int, description: str
    ) -> str:
        with self._client(access_token) as c:
            r = c.post(
                f"/payments/{payment_id}/refunds",
                json={
                    "amount": {"currency": "EUR", "value": f"{amount_cents / 100:.2f}"},
                    "description": description[:140],
                    "testmode": self.testmode,
                },
            )
            r.raise_for_status()
            return str(r.json()["id"])
