import argparse
import sys
from datetime import date

from common import load_json, parse_date, save_json, today_utc
from config import BRICKRANKER_HISTORY_DIR, BRICKRANKER_RAW, BRICKRANKER_SET_DIR
from fetch_brickranker import (
    history_cache_path,
    price_cache_path,
    price_payload,
    recent_window,
    set_cache_path,
    write_raw,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()
    as_of = parse_date(args.as_of) if args.as_of else today_utc()

    updated = 0
    for history_path in sorted(BRICKRANKER_HISTORY_DIR.glob("*.json")):
        history = load_json(history_path)
        if not history:
            continue
        set_no = history.get("set_number")
        if not set_no:
            continue
        parsed = load_json(set_cache_path(set_no))
        if not parsed or parsed.get("error"):
            continue
        monthly = history.get("monthly") or []
        recent = recent_window(monthly, as_of)
        sales = sum(row.get("sales") or 0 for row in recent)
        prices = [
            row.get("avg_price")
            for row in recent
            if row.get("avg_price") is not None
        ]
        current = parsed.get("current_value")
        parsed["sales_6m"] = sales
        parsed["months_with_sales"] = sum(
            1 for row in recent if (row.get("sales") or 0) > 0
        )
        parsed["price_low_6m"] = min(prices) if prices else current
        parsed["price_high_6m"] = max(prices) if prices else current
        save_json(set_cache_path(set_no), parsed)
        payload = price_payload(parsed)
        if payload:
            save_json(price_cache_path(set_no), payload)
        updated += 1

    old = load_json(BRICKRANKER_RAW) or {}
    write_raw(
        [],
        False,
        old.get("listing_pages"),
        old.get("candidate_count"),
        old.get("candidate_reasons") or {},
        old.get("errors") or [],
    )
    print(f"유동성 재계산: {updated}세트")
    return 0


if __name__ == "__main__":
    sys.exit(main())
