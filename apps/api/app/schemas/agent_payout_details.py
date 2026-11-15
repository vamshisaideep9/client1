"""Agent-saved payout destination (bank account / UPI ID) schemas.

The Agent's own endpoints return only masked hints. The full values leave the
API only through the payout-maker prefill read, which is guarded and audited.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints, model_validator

# name@handle; the local part allows the characters Indian PSPs issue.
_UPI_PATTERN = r"^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$"
# RBI IFSC: four bank letters, a zero, six branch characters. The pattern is
# checked before upper-casing, so it accepts either case; the stored value is
# upper case.
_IFSC_PATTERN = r"^[A-Za-z]{4}0[A-Za-z0-9]{6}$"
_ACCOUNT_PATTERN = r"^\d{6,18}$"

UpiId = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=320, pattern=_UPI_PATTERN)
]
Ifsc = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=_IFSC_PATTERN)
]
AccountNumber = Annotated[str, StringConstraints(strip_whitespace=True, pattern=_ACCOUNT_PATTERN)]
HolderName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
BankName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AgentBankAccount(BaseModel):
    account_holder_name: HolderName
    account_number: AccountNumber
    ifsc: Ifsc
    bank_name: BankName | None = None


class AgentPayoutDetailsUpdate(BaseModel):
    """Partial update. Omit a field to keep it; send ``null`` to remove it.

    After the update at least one destination must remain (the service
    answers 422 otherwise); remove everything with DELETE instead.
    """

    upi_id: UpiId | None = None
    bank: AgentBankAccount | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> AgentPayoutDetailsUpdate:
        if not self.model_fields_set & {"upi_id", "bank"}:
            raise ValueError("Provide upi_id and/or bank.")
        return self


class AgentPayoutDetailsRead(BaseModel):
    """What the Agent sees about their own saved destination: masked only."""

    saved: bool
    upi_hint: str | None = None
    bank_hint: str | None = None
    updated_at: datetime | None = None
    # False when this environment has no encryption key; saving is disabled.
    available: bool


class SavedPayoutDestinationRead(BaseModel):
    """Decrypted destination for prefilling one payout (audited read)."""

    upi_id: str | None = None
    bank: AgentBankAccount | None = None
    updated_at: datetime
