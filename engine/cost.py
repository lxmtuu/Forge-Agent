# -*- coding: utf-8 -*-
"""Ước lượng chi phí ($): usage tokens × giá model từ OpenRouter /models.

- Cache giá 1 giờ (đủ dùng, không spam API public).
- Không có giá / không mạng → trả None (UI tự ẩn, không bao giờ làm hỏng chat).
Đơn vị giá OpenRouter: USD / token (vd 0.000003 = $3/M token).
"""
from __future__ import annotations

import time

import httpx

_PRICES: dict[str, tuple[float, float]] | None = None
_FETCHED_AT = 0.0
TTL = 3600.0


async def _fetch_prices() -> dict[str, tuple[float, float]]:
    global _PRICES, _FETCHED_AT
    if _PRICES is not None and time.time() - _FETCHED_AT < TTL:
        return _PRICES
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get("https://openrouter.ai/api/v1/models")
        r.raise_for_status()
        rows = (r.json() or {}).get("data") or []
    out: dict[str, tuple[float, float]] = {}
    for row in rows:
        pid = str(row.get("id") or "").lower()
        pr = row.get("pricing") or {}
        try:
            out[pid] = (float(pr.get("prompt") or 0), float(pr.get("completion") or 0))
        except (TypeError, ValueError):
            continue
    if out:
        _PRICES = out
        _FETCHED_AT = time.time()
    return _PRICES or {}


def price_for(model: str | None, prices: dict[str, tuple[float, float]]):
    """Tìm giá theo model ID; bỏ hậu tố :online nếu không khớp trực tiếp."""
    key = (model or "").strip().lower()
    if key in prices:
        return prices[key]
    base = key.split(":")[0]
    return prices.get(base)


async def estimate(model: str | None, usage: dict | None) -> float | None:
    """$ cho 1 lượt gọi. Trả None nếu thiếu dữ liệu (không ném lỗi)."""
    u = usage or {}
    p = int(u.get("prompt_tokens") or 0)
    c = int(u.get("completion_tokens") or 0)
    if not (p or c):
        return None
    try:
        prices = await _fetch_prices()
    except Exception:
        return None
    pr = price_for(model, prices)
    if not pr:
        return None
    return round(p * pr[0] + c * pr[1], 6)
