"""Storefront payment tests — pass without real keys (monkeypatched env)."""

import pytest

from payments import PaymentClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_demo123")
    return PaymentClient()


def test_create_charge(client):
    charge = client.create_charge(amount_cents=1250, currency="usd")
    assert charge.amount_cents == 1250
    assert charge.currency == "usd"
    assert charge.id.startswith("ch_")
    assert not charge.refunded


def test_refund_marks_charge(client):
    charge = client.create_charge(amount_cents=500)
    refunded = client.refund(charge.id)
    assert refunded.refunded


def test_rejects_non_positive_amount(client):
    with pytest.raises(ValueError):
        client.create_charge(amount_cents=0)


def test_missing_key_fails_fast(monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    with pytest.raises(KeyError):
        PaymentClient()
