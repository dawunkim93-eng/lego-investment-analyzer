import argparse
import math
import sys

from common import load_json, parse_date
from config import MIN_SOLD_6M, MIN_YEARS_RETIRED, RRP_MIN_USD, SETS_JSON


def close(a, b, tolerance=0.002):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tolerance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(SETS_JSON))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    document = load_json(args.input)
    if not document:
        print(f"데이터 없음: {args.input}")
        return 1

    meta = document.get("meta") or {}
    coverage = document.get("coverage") or {}
    sets = document.get("sets") or []
    as_of = parse_date(meta.get("as_of"))
    errors = []
    warnings = []

    if not as_of:
        errors.append("meta.as_of 없음")
    if meta.get("universe_count") != len(sets):
        errors.append(
            f"universe_count 불일치: meta={meta.get('universe_count')} sets={len(sets)}"
        )
    if not meta.get("demo") and meta.get("source") not in {
        "Brickset + BrickLink",
        "BrickRanker",
    }:
        warnings.append(f"예상과 다른 source: {meta.get('source')}")

    counters = {
        "with_new_price": 0,
        "with_used_price": 0,
        "with_both_prices": 0,
        "rank_eligible": 0,
        "low_liquidity": 0,
    }

    for item in sets:
        label = item.get("set_number") or "<unknown>"
        rrp = item.get("rrp_usd")
        new_price = item.get("new_price")
        used_price = item.get("used_price")
        years = item.get("years_since_release")
        years_retired = item.get("years_retired")
        liquidity = item.get("liquidity")
        new_qty = item.get("new_qty") or 0
        used_qty = item.get("used_qty") or 0

        if rrp is None or rrp < RRP_MIN_USD:
            errors.append(f"{label}: RRP 범위 위반 ({rrp})")
        if new_price is not None and new_price <= 0:
            errors.append(f"{label}: 신품가 <= 0")
        if used_price is not None and used_price <= 0:
            errors.append(f"{label}: 중고가 <= 0")
        if new_price is not None:
            counters["with_new_price"] += 1
        if used_price is not None:
            counters["with_used_price"] += 1
        if new_price is not None and used_price is not None:
            counters["with_both_prices"] += 1
        if item.get("rank_eligible"):
            counters["rank_eligible"] += 1
        if item.get("low_liquidity"):
            counters["low_liquidity"] += 1

        if liquidity != new_qty + used_qty:
            errors.append(f"{label}: liquidity 불일치")
        if item.get("low_liquidity") != (liquidity < MIN_SOLD_6M):
            errors.append(f"{label}: low_liquidity 플래그 불일치")

        exit_date = parse_date(item.get("exit_date"))
        if exit_date and as_of and exit_date >= as_of:
            errors.append(f"{label}: 단종일이 기준일 이후")

        if years is not None and years < 1.0:
            errors.append(f"{label}: 보유연수 1년 미만인데 포함")

        if new_price is not None and rrp and years:
            expected_roi = new_price / rrp - 1
            if not close(item.get("roi_new"), expected_roi):
                errors.append(f"{label}: roi_new 재계산 불일치")
            expected_cagr = (new_price / rrp) ** (1 / years) - 1
            if not close(item.get("cagr_new"), expected_cagr):
                errors.append(f"{label}: cagr_new 재계산 불일치")

        if used_price is not None and rrp and years:
            expected_roi = used_price / rrp - 1
            if not close(item.get("roi_used"), expected_roi):
                errors.append(f"{label}: roi_used 재계산 불일치")
            expected_cagr = (used_price / rrp) ** (1 / years) - 1
            if not close(item.get("cagr_used"), expected_cagr):
                errors.append(f"{label}: cagr_used 재계산 불일치")

        if new_price and used_price:
            expected_premium = new_price / used_price - 1
            if not close(item.get("sealed_premium"), expected_premium):
                errors.append(f"{label}: sealed_premium 재계산 불일치")

        if item.get("rank_eligible"):
            if years_retired is None or years_retired < MIN_YEARS_RETIRED:
                errors.append(f"{label}: 랭킹 적합인데 단종연수 미달")
            if liquidity < MIN_SOLD_6M:
                errors.append(f"{label}: 랭킹 적합인데 유동성 미달")
            if new_price is None or item.get("cagr_new") is None:
                errors.append(f"{label}: 랭킹 적합인데 가격/CAGR 없음")

        for key in ("roi_new", "cagr_new", "real_cagr_new", "roi_used", "cagr_used"):
            value = item.get(key)
            if value is not None and (math.isnan(value) or math.isinf(value)):
                errors.append(f"{label}: {key} NaN/Inf")

    for key, value in counters.items():
        if coverage.get(key) != value:
            errors.append(
                f"coverage.{key} 불일치: coverage={coverage.get(key)} actual={value}"
            )

    print(f"검증: {args.input}")
    print(f"세트 {len(sets)} / 랭킹 적합 {counters['rank_eligible']} / 오류 {len(errors)}")
    print(
        f"가격 커버리지: 신품 {counters['with_new_price']} / 중고 {counters['with_used_price']} / 둘 다 {counters['with_both_prices']}"
    )
    if warnings:
        print("경고:")
        for warning in warnings[:20]:
            print(f"  - {warning}")
        if args.strict:
            return 1
    if errors:
        print("오류:")
        for error in errors[:50]:
            print(f"  - {error}")
        if len(errors) > 50:
            print(f"  ... 외 {len(errors) - 50}건")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
