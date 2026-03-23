"""
Extract product variants and prices from raw HTML.

Pipeline:
  1. Rule-based: try known JS variable patterns (fast, free, no LLM)
  2. LLM fallback: send cleaned HTML to local qwen2.5:7b via Ollama
"""
from __future__ import annotations
import json
import re
import sys
import os

import ollama

from .models import ProductSnapshot, Variant

# ── Rule-based patterns (ordered by commonality) ───────────────────────────

# Each pattern is a JS variable name whose value is a JSON object/array.
JS_PATTERNS = [
    "var rawData",           # Mountain Warehouse
    "window.__NEXT_DATA__",  # Next.js (ASOS, many modern stores)
    "window.__INITIAL_STATE__",  # React/Redux stores
    "__APP_STATE__",
    "window.dataLayer",
    "var pageData",
    "var productData",
]


def _extract_json_object(s: str, start_key: str) -> str | None:
    """Find `start_key` in s, then extract the JSON object/array that follows."""
    idx = s.find(start_key)
    if idx == -1:
        return None

    # Find the first { or [ after the key
    brace_pos = -1
    for i in range(idx, min(idx + 200, len(s))):
        if s[i] in ('{', '['):
            brace_pos = i
            break
    if brace_pos == -1:
        return None

    open_ch = s[brace_pos]
    close_ch = '}' if open_ch == '{' else ']'

    depth = 0
    in_string = False
    escape = False
    for i in range(brace_pos, len(s)):
        ch = s[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return s[brace_pos:i + 1]
    return None


def _parse_mountain_warehouse(obj: dict) -> list[Variant] | None:
    """Parse Mountain Warehouse rawData structure."""
    product = obj.get("Product") or obj
    options = product.get("Options")
    if not options or not isinstance(options, list):
        return None

    variants = []
    for opt in options:
        attrs = {}
        if colour := opt.get("ColourName"):
            attrs["colour"] = colour
        if size := opt.get("SizeName"):
            attrs["size"] = size

        price = opt.get("PriceValue") or opt.get("Price")
        msrp = opt.get("MsrpValue") or opt.get("Msrp")
        currency = opt.get("CurrencyCode", "USD")
        in_stock = (opt.get("StockCount") or 0) > 0

        if price is None:
            continue
        variants.append(Variant(
            attributes=attrs,
            price=float(price),
            msrp=float(msrp) if msrp else None,
            in_stock=in_stock,
            currency=currency,
        ))
    return variants or None


def _try_rule_based(html: str, url: str) -> ProductSnapshot | None:
    """Try all known JS patterns and return a snapshot if any works."""
    for pattern in JS_PATTERNS:
        raw = _extract_json_object(html, pattern)
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue

        # Mountain Warehouse / rawData
        variants = _parse_mountain_warehouse(obj)
        if variants:
            product = obj.get("Product", obj)
            name = product.get("Name") or product.get("StandardName") or "Unknown Product"
            currency = variants[0].currency if variants else "USD"
            return ProductSnapshot(product_name=name, url=url, variants=variants)

        # Next.js __NEXT_DATA__ — the product data is nested, let LLM handle it
        # (fall through to LLM)

    return None


# ── LLM fallback ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a precise product-data extraction agent.
Given HTML from an e-commerce product page, extract ALL variants and their prices.
Return ONLY a valid JSON object — no markdown, no explanation — in exactly this schema:

{
  "product_name": "<string>",
  "currency": "<ISO 4217 code, e.g. USD, CAD, GBP>",
  "variants": [
    {
      "attributes": {"<dimension>": "<value>", ...},
      "price": <current sale price as number>,
      "msrp": <original full price as number or null>,
      "in_stock": <true|false>
    }
  ]
}

Rules:
- "price" is the final purchase price (after discounts), never the MRP/MSRP.
- Include every variant (colour × size, or whatever dimensions exist).
- If a dimension does not apply (e.g. the product has no colour), omit that key.
- If you cannot find structured variant data, return {"product_name":"unknown","currency":"USD","variants":[]}.
"""


def _clean_html_for_llm(html: str) -> str:
    """Strip noise so the LLM gets a smaller, more focused input."""
    # Remove <script> blocks that are clearly not product data (analytics, ads)
    html = re.sub(r'<script[^>]*src=[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove <style> blocks
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    # Collapse whitespace
    html = re.sub(r'\s{2,}', ' ', html)
    # Trim to 12k chars — enough for product data, cheap on tokens
    return html[:12000]


def _try_llm(html: str, url: str, model: str = "qwen2.5:7b") -> ProductSnapshot | None:
    """Send cleaned HTML to local Ollama model and parse the response."""
    cleaned = _clean_html_for_llm(html)
    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"URL: {url}\n\nHTML:\n{cleaned}"},
            ],
            options={"temperature": 0},
        )
        content = response["message"]["content"].strip()

        # Strip possible markdown code fences
        content = re.sub(r'^```(?:json)?\s*', '', content)
        content = re.sub(r'\s*```$', '', content)

        obj = json.loads(content)
    except Exception as e:
        print(f"[extractor] LLM error: {e}", file=sys.stderr)
        return None

    raw_variants = obj.get("variants", [])
    if not raw_variants:
        return None

    currency = obj.get("currency", "USD")
    variants = []
    for v in raw_variants:
        price = v.get("price")
        if price is None:
            continue
        variants.append(Variant(
            attributes=v.get("attributes", {}),
            price=float(price),
            msrp=float(v["msrp"]) if v.get("msrp") else None,
            in_stock=bool(v.get("in_stock", True)),
            currency=currency,
        ))

    return ProductSnapshot(
        product_name=obj.get("product_name", "Unknown Product"),
        url=url,
        variants=variants,
    )


# ── Public API ─────────────────────────────────────────────────────────────

def extract(html: str, url: str, llm_model: str = "qwen2.5:7b") -> ProductSnapshot | None:
    """
    Extract a ProductSnapshot from raw HTML.
    Tries rule-based extraction first; falls back to the local LLM.
    Returns None if extraction completely fails.
    """
    snapshot = _try_rule_based(html, url)
    if snapshot and snapshot.variants:
        print(f"[extractor] rule-based OK — {len(snapshot.variants)} variants", file=sys.stderr)
        return snapshot

    print("[extractor] rule-based failed, trying LLM…", file=sys.stderr)
    snapshot = _try_llm(html, url, model=llm_model)
    if snapshot and snapshot.variants:
        print(f"[extractor] LLM OK — {len(snapshot.variants)} variants", file=sys.stderr)
        return snapshot

    print("[extractor] both extractors failed.", file=sys.stderr)
    return None
