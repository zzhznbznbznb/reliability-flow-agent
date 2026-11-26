"""Deterministic per-entity random streams.

Seed derivation is explicit: each stream seed is the SHA-256 digest of
``rfa-sim/1|<base_seed>|<entity_id>|<stream>``. Business and reliability
streams therefore never share mutable generator state, and adding business
sampling cannot shift the reliability sequence.
"""

from __future__ import annotations

import hashlib
import random

RELIABILITY_STREAM = "reliability"
BUSINESS_STREAM = "business"


def derive_stream_seed(base_seed: int, entity_id: str, stream: str) -> int:
    payload = f"rfa-sim/1|{base_seed}|{entity_id}|{stream}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:16], "big")


def make_stream_rng(base_seed: int, entity_id: str, stream: str) -> random.Random:
    return random.Random(derive_stream_seed(base_seed, entity_id, stream))


__all__ = [
    "BUSINESS_STREAM",
    "RELIABILITY_STREAM",
    "derive_stream_seed",
    "make_stream_rng",
]
