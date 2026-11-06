"""Deterministic synthetic banking transactions.

The same size, seed and currency rebuild the same rows. Boundary amounts required
by the experiment are always present and are included in the row count.
"""

import csv
import hashlib
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

FIELDS = [
    "transaction_id",
    "customer_id",
    "transaction_date",
    "account_id",
    "transaction_type",
    "currency",
    "transaction_amount",
]

BOUNDARIES = (
    ("BND-999.99", Decimal("999.99")),
    ("BND-1000.00", Decimal("1000.00")),
    ("BND-4999.99", Decimal("4999.99")),
    ("BND-5000.00", Decimal("5000.00")),
    ("BND-9999.99", Decimal("9999.99")),
    ("BND-10000.00", Decimal("10000.00")),
)

TRANSACTION_TYPES = ("CARD", "TRANSFER", "PAYMENT", "CASH")
ORIGIN = date(2024, 1, 1)


def build_rows(size, seed, currency):
    if size < len(BOUNDARIES):
        raise ValueError(f"dataset size must be at least {len(BOUNDARIES)}")
    if currency != "AUD":
        raise ValueError("phase 1 uses fixed currency AUD")
    rows = [_boundary_row(transaction_id, amount, currency) for transaction_id, amount in BOUNDARIES]
    rng = random.Random(seed)
    for number in range(1, size - len(BOUNDARIES) + 1):
        rows.append(_generated_row(rng, number, currency))
    ids = [row["transaction_id"] for row in rows]
    if len(ids) != size or len(set(ids)) != size:
        raise RuntimeError("generated transaction keys are not unique")
    return rows


def canonical_checksum(rows):
    ordered = sorted(rows, key=lambda row: row["transaction_id"])
    lines = [",".join(row[field] for field in FIELDS) for row in ordered]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_csv(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return canonical_checksum(rows)


def _boundary_row(transaction_id, amount, currency):
    return {
        "transaction_id": transaction_id,
        "customer_id": "C-BOUNDARY",
        "transaction_date": "2024-01-01",
        "account_id": "A-BOUNDARY",
        "transaction_type": "CARD",
        "currency": currency,
        "transaction_amount": f"{amount:.2f}",
    }


def _generated_row(rng, number, currency):
    roll = rng.randrange(100)
    if roll < 40:
        cents = rng.randrange(1, 100_000)
    elif roll < 70:
        cents = rng.randrange(100_000, 500_000)
    elif roll < 90:
        cents = rng.randrange(500_000, 1_000_000)
    else:
        cents = rng.randrange(1_000_000, 2_500_001)
    amount = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
    return {
        "transaction_id": f"TX-{number:08d}",
        "customer_id": f"C-{rng.randrange(1, 10_001):06d}",
        "transaction_date": (ORIGIN + timedelta(days=rng.randrange(0, 366))).isoformat(),
        "account_id": f"A-{rng.randrange(1, 5_001):06d}",
        "transaction_type": TRANSACTION_TYPES[rng.randrange(len(TRANSACTION_TYPES))],
        "currency": currency,
        "transaction_amount": f"{amount:.2f}",
    }
