from __future__ import annotations


def validate_email(email: str) -> bool:
    return "@" in email


def validate_amount(amount: float) -> bool:
    return amount > 0
