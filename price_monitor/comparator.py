"""
Compare two ProductSnapshots and return any variants whose price dropped.
Also builds the price matrix table for display in alerts.
"""
from __future__ import annotations
from .models import ProductSnapshot, PriceDrop


def find_drops(previous: ProductSnapshot, current: ProductSnapshot) -> list[PriceDrop]:
    """Return PriceDrop records for every variant cheaper in current vs previous."""
    prev_by_key = {v.attr_key: v for v in previous.variants}
    drops = []
    for v in current.variants:
        prev = prev_by_key.get(v.attr_key)
        if prev and v.price < prev.price:
            drops.append(PriceDrop(
                product_name=current.product_name,
                url=current.url,
                attributes=v.attributes,
                old_price=prev.price,
                new_price=v.price,
                currency=v.currency,
            ))
    return drops


def build_price_matrix(snapshot: ProductSnapshot) -> str:
    """
    Render a text price matrix.

    For two-dimensional variants (e.g. colour × size):
        rows = first attribute (e.g. colour)
        cols = second attribute (e.g. size)

    For one-dimensional variants (e.g. size only):
        flat list.

    Returns a plain-text table string.
    """
    variants = snapshot.variants
    if not variants:
        return "(no variants found)"

    # Determine dimensions
    all_keys = list(variants[0].attributes.keys())

    if len(all_keys) == 0:
        # No attributes at all — single variant
        v = variants[0]
        return f"{v.currency} {v.price:.2f}"

    if len(all_keys) == 1:
        # One dimension — simple list
        key = all_keys[0]
        lines = [f"  {v.attributes[key]:<20}  {v.currency} {v.price:.2f}"
                 + ("  [out of stock]" if not v.in_stock else "")
                 for v in variants]
        return "\n".join(lines)

    # Two (or more) dimensions — matrix on first two
    row_key, col_key = all_keys[0], all_keys[1]

    # Ordered unique values preserving first-seen order
    rows_seen: dict[str, None] = {}
    cols_seen: dict[str, None] = {}
    lookup: dict[tuple[str, str], float | str] = {}

    for v in variants:
        r = v.attributes.get(row_key, "?")
        c = v.attributes.get(col_key, "?")
        rows_seen[r] = None
        cols_seen[c] = None
        label = f"{v.currency} {v.price:.2f}" + ("*" if not v.in_stock else "")
        lookup[(r, c)] = label

    row_labels = list(rows_seen)
    col_labels = list(cols_seen)

    col_w = max(len(c) for c in col_labels + [""])
    col_w = max(col_w, 10)
    row_w = max(len(r) for r in row_labels + [row_key])

    # Header
    header = f"{'':>{row_w}} | " + " | ".join(f"{c:^{col_w}}" for c in col_labels)
    sep = "-" * len(header)
    lines = [header, sep]

    for r in row_labels:
        cells = []
        for c in col_labels:
            val = lookup.get((r, c), "—")
            cells.append(f"{val:^{col_w}}")
        lines.append(f"{r:>{row_w}} | " + " | ".join(cells))

    lines.append("  (* = out of stock)")
    return "\n".join(lines)
