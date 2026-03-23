"""
Main entry point. Loads config.yaml, sets up APScheduler, and runs the
fetch → extract → store → compare → notify pipeline for each product.

Run:
  python -m price_monitor.scheduler
"""
from __future__ import annotations
import sys
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from .fetcher import fetch_page
from .extractor import extract
from .store import init_db, save_snapshot, get_previous_snapshot
from .comparator import find_drops
from .notifier import send_drop_alert, send_daily_summary

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def check_product(product_cfg: dict, telegram_cfg: dict, llm_model: str) -> None:
    """Full pipeline for one product URL."""
    url = product_cfg["url"]
    name = product_cfg.get("name", url)
    daily_summary = product_cfg.get("daily_summary", False)

    print(f"[scheduler] checking: {name}")

    try:
        html = fetch_page(url)
    except Exception as e:
        print(f"[scheduler] fetch failed for {url}: {e}", file=sys.stderr)
        return

    snapshot = extract(html, url, llm_model=llm_model)
    if not snapshot:
        print(f"[scheduler] extraction failed for {url}", file=sys.stderr)
        return

    # Override name from config if extractor returned "Unknown Product"
    if snapshot.product_name in ("Unknown Product", "unknown"):
        snapshot.product_name = name

    previous = get_previous_snapshot(url)
    save_snapshot(snapshot)

    if previous:
        drops = find_drops(previous, snapshot)
        if drops:
            print(f"[scheduler] {len(drops)} drop(s) found — sending alert")
            send_drop_alert(
                drops=drops,
                snapshot=snapshot,
                bot_token=telegram_cfg["bot_token"],
                chat_id=telegram_cfg["chat_id"],
            )
        else:
            print(f"[scheduler] no drops for {name}")
            if daily_summary:
                send_daily_summary(
                    snapshot=snapshot,
                    bot_token=telegram_cfg["bot_token"],
                    chat_id=telegram_cfg["chat_id"],
                )
    else:
        print(f"[scheduler] first run for {name} — snapshot saved, no comparison yet")
        if daily_summary:
            send_daily_summary(
                snapshot=snapshot,
                bot_token=telegram_cfg["bot_token"],
                chat_id=telegram_cfg["chat_id"],
            )


def run_all(config: dict) -> None:
    """Check all products defined in config."""
    telegram_cfg = config.get("telegram", {})
    llm_model = config.get("llm_model", "qwen2.5:7b")
    for product in config.get("products", []):
        try:
            check_product(product, telegram_cfg, llm_model)
        except Exception as e:
            print(f"[scheduler] unexpected error for {product.get('url')}: {e}", file=sys.stderr)


def main() -> None:
    config = load_config()
    init_db()

    schedules = config.get("schedule", ["0 9 * * *"])  # default: 9 AM daily
    if isinstance(schedules, str):
        schedules = [schedules]

    scheduler = BlockingScheduler(timezone="America/Toronto")  # change in config.yaml

    for cron_expr in schedules:
    # Parse "minute hour day month day_of_week" cron string
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            print(f"[scheduler] invalid cron expression: {cron_expr!r}", file=sys.stderr)
            continue
        minute, hour, day, month, day_of_week = parts
        scheduler.add_job(
            run_all,
            "cron",
            args=[config],
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
        print(f"[scheduler] scheduled: {cron_expr}")

    # Also run immediately on startup so you don't wait until the first cron tick
    print("[scheduler] running initial check on startup…")
    run_all(config)

    print("[scheduler] scheduler started. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("[scheduler] stopped.")


if __name__ == "__main__":
    main()
