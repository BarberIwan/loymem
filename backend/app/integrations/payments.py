"""The payment provider seen from Loymem: the business's own account.

Loymem never holds customer money. It starts payments in the business's own
account (Mollie Connect by default) and reads their status back. The only
implementation lives in ``mollie.py``; tests use ``FakeProvider``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: datetime


@dataclass(frozen=True)
class PaymentInfo:
    payment_id: str
    status: str  # open, pending, authorized, paid, failed, canceled, expired
    amount_cents: int
    customer_id: str | None
    mandate_id: str | None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NewPayment:
    payment_id: str
    checkout_url: str | None


class PaymentProvider(Protocol):
    name: str

    def authorize_url(self, state: str, redirect_uri: str) -> str: ...

    def exchange_code(self, code: str, redirect_uri: str) -> Tokens: ...

    def refresh(self, refresh_token: str) -> Tokens: ...

    def create_payment(
        self,
        access_token: str,
        *,
        amount_cents: int,
        description: str,
        sequence: str,  # oneoff, first, recurring
        redirect_url: str,
        webhook_url: str,
        metadata: dict[str, str],
        customer_id: str | None = None,
        mandate_id: str | None = None,
    ) -> NewPayment: ...

    def get_payment(self, access_token: str, payment_id: str) -> PaymentInfo: ...

    def refund(
        self, access_token: str, payment_id: str, amount_cents: int, description: str
    ) -> str:
        """Give money back on a paid payment, to the same method. Returns the refund id."""
        ...


class FakeProvider:
    """In-memory provider for tests and local work. Never used in production."""

    name = "fake"

    def __init__(self) -> None:
        self.payments: dict[str, PaymentInfo] = {}
        self.refunds: list[tuple[str, int]] = []
        self.counter = 0

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        return f"https://fake.example/authorize?state={state}"

    def exchange_code(self, code: str, redirect_uri: str) -> Tokens:
        return Tokens("access-" + code, "refresh-" + code, datetime(2099, 1, 1))

    def refresh(self, refresh_token: str) -> Tokens:
        return Tokens("access-new", refresh_token, datetime(2099, 1, 1))

    def create_payment(self, access_token: str, **kw: object) -> NewPayment:
        self.counter += 1
        pid = f"tr_fake{self.counter}"
        meta = kw["metadata"]
        assert isinstance(meta, dict)
        amount = kw["amount_cents"]
        assert isinstance(amount, int)
        self.payments[pid] = PaymentInfo(pid, "open", amount, None, None, dict(meta))
        return NewPayment(pid, f"https://fake.example/checkout/{pid}")

    def set_status(
        self, pid: str, status: str, *, customer: str = "cst_1", mandate: str = "mdt_1"
    ) -> None:
        p = self.payments[pid]
        self.payments[pid] = PaymentInfo(pid, status, p.amount_cents, customer, mandate, p.metadata)

    def get_payment(self, access_token: str, payment_id: str) -> PaymentInfo:
        return self.payments[payment_id]

    def refund(
        self, access_token: str, payment_id: str, amount_cents: int, description: str
    ) -> str:
        paid = self.payments[payment_id]
        if paid.status != "paid" or amount_cents > paid.amount_cents:
            raise ValueError("refund_not_possible")
        self.refunds.append((payment_id, amount_cents))
        return f"re_fake{len(self.refunds)}"
