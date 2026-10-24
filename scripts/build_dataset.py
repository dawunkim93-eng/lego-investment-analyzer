import argparse
import csv
import sys
from bisect import bisect_right
from pathlib import Path

from common import (
    cagr,
    extract_price_guide,
    exclusion_reason,
    load_json,
    median,
    month_key,
    normalize_brickset,
    now_iso,
    parse_date,
    rrp_band,
    round_or_none,
    safe_float,
    safe_int,
    save_json,
    today_utc,
)
from config import (
    BRICKLINK_RAW_DIR,
    BRICKRANKER_HISTORY_DIR,
    BRICKSET_RAW,
    COVERAGE_JSON,
    CPI_RAW,
    MIN_SOLD_6M,
    MIN_YEARS_RETIRED,
    REPORT_MD,
    RRP_MIN_USD,
    SETS_JSON,
)


def price_cache_path(prices_dir, set_no, condition):
    safe = set_no.replace("/", "_")
    return Path(prices_dir) / f"{safe}__{condition}_sold.json"


def load_price(prices_dir, set_no, condition, extract):
    path = price_cache_path(prices_dir, set_no, condition)
    payload = load_json(path)
    if not payload or payload.get("error"):
        return None
    return extract(payload)


def load_spark(history_dir, set_no):
    if not history_dir:
        return []
    path = Path(history_dir) / f"{set_no.replace('/', '_')}.json"
    history = load_json(path)
    if not history:
        return []
    values = [
        round(row["avg_price"], 2)
        for row in (history.get("monthly") or [])
        if row.get("avg_price") is not None
    ]
    return values[-12:]


def load_cpi(path):
    path = Path(path)
    if not path.exists():
        return [], {}
    values = {}
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = str(row.get("observation_date") or "")[:7]
            value = safe_float(row.get("CPIAUCSL"))
            if len(key) == 7 and value is not None:
                values[key] = value
    keys = sorted(values)
    return keys, values


def cpi_at(keys, values, target):
    if not keys or target is None:
        return None
    key = month_key(target)
    if key is None:
        return None
    index = bisect_right(keys, key) - 1
    if index < 0:
        return None
    return values[keys[index]]


def build_set(item, prices_dir, as_of, cpi_keys, cpi_values, extract, cpi_latest):
    normalized = normalize_brickset(item, today=as_of)
    set_no = normalized["set_number"]
    rrp = normalized["rrp_usd"]
    launch = parse_date(normalized["launch_date"])
    exit_date = parse_date(normalized["exit_date"])
    years_release = (as_of - launch).days / 365.25 if launch else None
    years_retired = (as_of - exit_date).days / 365.25 if exit_date else None
    years_calc = round(years_release, 2) if years_release is not None else None

    new = load_price(prices_dir, set_no, "new", extract)
    used = load_price(prices_dir, set_no, "used", extract)
    new_price = new["avg_price"] if new else None
    used_price = used["avg_price"] if used else None
    new_qty = new["quantity"] if new else 0
    used_qty = used["quantity"] if used else 0
    liquidity = (new_qty or 0) + (used_qty or 0)

    multiple_new = new_price / rrp if new_price and rrp else None
    multiple_used = used_price / rrp if used_price and rrp else None
    roi_new = multiple_new - 1 if multiple_new is not None else None
    roi_used = multiple_used - 1 if multiple_used is not None else None
    cagr_new = cagr(multiple_new, years_calc)
    cagr_used = cagr(multiple_used, years_calc)

    cpi_release = cpi_at(cpi_keys, cpi_values, launch)
    real_multiple_new = None
    real_multiple_used = None
    if cpi_latest and cpi_release:
        factor = cpi_latest / cpi_release
        if multiple_new is not None and factor > 0:
            real_multiple_new = multiple_new / factor
        if multiple_used is not None and factor > 0:
            real_multiple_used = multiple_used / factor
    real_cagr_new = cagr(real_multiple_new, years_calc)
    real_cagr_used = cagr(real_multiple_used, years_calc)

    sealed_premium = (
        new_price / used_price - 1 if new_price and used_price and used_price > 0 else None
    )
    abs_profit = new_price - rrp if new_price is not None and rrp is not None else None

    low_liquidity = liquidity < MIN_SOLD_6M
    rank_eligible = bool(
        years_retired is not None
        and years_retired >= MIN_YEARS_RETIRED
        and liquidity >= MIN_SOLD_6M
        and new_price is not None
        and rrp is not None
        and cagr_new is not None
    )

    return {
        "set_number": set_no,
        "name": normalized["name"],
        "theme": normalized["theme"],
        "subtheme": normalized["subtheme"],
        "category": normalized["category"],
        "is_cmf": normalized["is_cmf"],
        "year": normalized["year"],
        "launch_date": normalized["launch_date"],
        "exit_date": normalized["exit_date"],
        "exit_date_estimated": normalized["exit_date_estimated"],
        "launch_date_estimated": normalized["launch_date_estimated"],
        "confidence": normalized["confidence"],
        "retire_year": exit_date.year if exit_date else None,
        "years_since_release": round_or_none(years_release, 2),
        "years_retired": round_or_none(years_retired, 2),
        "pieces": normalized["pieces"],
        "minifigs": normalized["minifigs"],
        "rrp_usd": rrp,
        "rrp_band": rrp_band(rrp),
        "new_price": round_or_none(new_price, 2),
        "new_low": round_or_none(new["min_price"], 2) if new else None,
        "new_high": round_or_none(new["max_price"], 2) if new else None,
        "new_qty": new_qty,
        "new_lots": new["lots"] if new else 0,
        "used_price": round_or_none(used_price, 2),
        "used_low": round_or_none(used["min_price"], 2) if used else None,
        "used_high": round_or_none(used["max_price"], 2) if used else None,
        "used_qty": used_qty,
        "used_lots": used["lots"] if used else 0,
        "liquidity": liquidity,
        "roi_new": round_or_none(roi_new, 4),
        "cagr_new": round_or_none(cagr_new, 4),
        "real_cagr_new": round_or_none(real_cagr_new, 4),
        "roi_used": round_or_none(roi_used, 4),
        "cagr_used": round_or_none(cagr_used, 4),
        "real_cagr_used": round_or_none(real_cagr_used, 4),
        "sealed_premium": round_or_none(sealed_premium, 4),
        "abs_profit_new": round_or_none(abs_profit, 2),
        "low_liquidity": low_liquidity,
        "rank_eligible": rank_eligible,
        "has_new": new is not None,
        "has_used": used is not None,
        "image": normalized["image"],
        "brickset_url": normalized["brickset_url"],
        "bricklink_url": normalized["bricklink_url"],
        "source_url": normalized["source_url"],
        "availability": normalized["availability"],
    }


def aggregate(sets, key, label):
    groups = {}
    for item in sets:
        value = item.get(key)
        if value is None:
            continue
        groups.setdefault(value, []).append(item)
    rows = []
    for value, items in groups.items():
        eligible = [item for item in items if item.get("rank_eligible")]
        rows.append(
            {
                label: value,
                "count": len(items),
                "eligible_count": len(eligible),
                "median_cagr_new": median([item.get("cagr_new") for item in eligible]),
                "median_roi_new": median([item.get("roi_new") for item in eligible]),
                "median_cagr_used": median([item.get("cagr_used") for item in eligible]),
                "median_liquidity": median([item.get("liquidity") for item in items]),
                "median_rrp": median([item.get("rrp_usd") for item in items]),
            }
        )
    return rows


def sort_theme_rows(rows):
    return sorted(
        rows,
        key=lambda row: (
            row["median_cagr_new"] if row["median_cagr_new"] is not None else -99,
            row["eligible_count"],
        ),
        reverse=True,
    )


def top_rows(sets, key, limit=20, eligible=True):
    pool = [item for item in sets if item.get("rank_eligible")] if eligible else sets
    pool = [item for item in pool if item.get(key) is not None]
    return sorted(pool, key=lambda item: item[key], reverse=True)[:limit]


def build_coverage(raw_sets, sets, reasons):
    with_new = sum(1 for item in sets if item["has_new"])
    with_used = sum(1 for item in sets if item["has_used"])
    with_both = sum(1 for item in sets if item["has_new"] and item["has_used"])
    eligible = sum(1 for item in sets if item["rank_eligible"])
    low_liquidity = sum(1 for item in sets if item["low_liquidity"])
    return {
        "raw_brickset_sets": len(raw_sets),
        "universe_sets": len(sets),
        "with_new_price": with_new,
        "with_used_price": with_used,
        "with_both_prices": with_both,
        "missing_new_price": len(sets) - with_new,
        "missing_used_price": len(sets) - with_used,
        "rank_eligible": eligible,
        "low_liquidity": low_liquidity,
        "excluded_reasons": reasons,
        "coverage_new_pct": round(with_new / len(sets), 4) if sets else 0.0,
        "coverage_used_pct": round(with_used / len(sets), 4) if sets else 0.0,
        "rank_eligible_pct": round(eligible / len(sets), 4) if sets else 0.0,
    }


def pct(value):
    if value is None:
        return "-"
    return f"{value * 100:+.1f}%"


def money(value):
    if value is None:
        return "-"
    return f"${value:,.2f}"


def write_report(path, meta, coverage, sets, themes, retire_years, bands):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    top_cagr = top_rows(sets, "cagr_new", 20)
    top_profit = top_rows(sets, "abs_profit_new", 10)
    top_roi = top_rows(sets, "roi_new", 10)

    lines = []
    lines.append("# LEGO 재테크 분석 리포트")
    lines.append("")
    lines.append(f"- 기준일: {meta['as_of']}")
    lines.append(f"- 데이터: {meta['source']}")
    lines.append(f"- 분석 대상: 단종 세트, US RRP ≥ ${RRP_MIN_USD:.0f}, {meta['universe_count']}개")
    lines.append(
        f"- 랭킹 조건: 단종 {MIN_YEARS_RETIRED:.0f}년 이상, 6개월 체결 {MIN_SOLD_6M}건 이상"
    )
    lines.append("")
    lines.append("## 데이터 커버리지")
    lines.append("")
    lines.append(f"- 신품 가격 확보: {coverage['with_new_price']} / {coverage['universe_sets']} ({coverage['coverage_new_pct'] * 100:.1f}%)")
    lines.append(f"- 중고 가격 확보: {coverage['with_used_price']} / {coverage['universe_sets']} ({coverage['coverage_used_pct'] * 100:.1f}%)")
    lines.append(f"- 랭킹 적합: {coverage['rank_eligible']}개")
    lines.append(f"- 저유동성(6개월 체결 {MIN_SOLD_6M}건 미만): {coverage['low_liquidity']}개")
    if not coverage.get("with_used_price"):
        lines.append("- 중고 가격: BrickRanker 신품(New) 전용으로 미포함")
    lines.append("")
    lines.append("## CAGR 상위 20")
    lines.append("")
    lines.append("| 순위 | 세트 | 테마 | 단종 | RRP | 현재 신품 | CAGR | 실질 CAGR | 6개월 체결 |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|")
    for index, item in enumerate(top_cagr, start=1):
        lines.append(
            "| {rank} | {number} {name} | {theme} | {year} | {rrp} | {price} | {cagr} | {real} | {qty} |".format(
                rank=index,
                number=item["set_number"],
                name=item["name"].replace("|", "/"),
                theme=item["theme"].replace("|", "/"),
                year=item["exit_date"][:4] if item["exit_date"] else "-",
                rrp=money(item["rrp_usd"]),
                price=money(item["new_price"]),
                cagr=pct(item["cagr_new"]),
                real=pct(item["real_cagr_new"]),
                qty=item["liquidity"],
            )
        )
    lines.append("")
    lines.append("## 절대 차익 상위 10")
    lines.append("")
    lines.append("| 순위 | 세트 | RRP | 현재 신품 | 차익 | CAGR |")
    lines.append("|---:|---|---:|---:|---:|---:|")
    for index, item in enumerate(top_profit, start=1):
        lines.append(
            "| {rank} | {number} {name} | {rrp} | {price} | {profit} | {cagr} |".format(
                rank=index,
                number=item["set_number"],
                name=item["name"].replace("|", "/"),
                rrp=money(item["rrp_usd"]),
                price=money(item["new_price"]),
                profit=money(item["abs_profit_new"]),
                cagr=pct(item["cagr_new"]),
            )
        )
    lines.append("")
    lines.append("## ROI 상위 10")
    lines.append("")
    lines.append("| 순위 | 세트 | RRP | 현재 신품 | ROI |")
    lines.append("|---:|---|---:|---:|---:|")
    for index, item in enumerate(top_roi, start=1):
        lines.append(
            "| {rank} | {number} {name} | {rrp} | {price} | {roi} |".format(
                rank=index,
                number=item["set_number"],
                name=item["name"].replace("|", "/"),
                rrp=money(item["rrp_usd"]),
                price=money(item["new_price"]),
                roi=pct(item["roi_new"]),
            )
        )
    lines.append("")
    lines.append("## 테마별 중위 CAGR")
    lines.append("")
    lines.append("| 테마 | 분석 세트 | 랭킹 적합 | 중위 CAGR | 중위 ROI | 중위 유동성 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in themes[:20]:
        lines.append(
            "| {theme} | {count} | {eligible} | {cagr} | {roi} | {liq} |".format(
                theme=str(row["theme"]).replace("|", "/"),
                count=row["count"],
                eligible=row["eligible_count"],
                cagr=pct(row["median_cagr_new"]),
                roi=pct(row["median_roi_new"]),
                liq=row["median_liquidity"] if row["median_liquidity"] is not None else "-",
            )
        )
    lines.append("")
    lines.append("## 단종 연도별 중위 CAGR")
    lines.append("")
    lines.append("| 단종 연도 | 분석 세트 | 랭킹 적합 | 중위 CAGR | 중위 ROI |")
    lines.append("|---:|---:|---:|---:|---:|")
    for row in sorted(retire_years, key=lambda item: item["retire_year"] or 0):
        lines.append(
            "| {year} | {count} | {eligible} | {cagr} | {roi} |".format(
                year=row["retire_year"],
                count=row["count"],
                eligible=row["eligible_count"],
                cagr=pct(row["median_cagr_new"]),
                roi=pct(row["median_roi_new"]),
            )
        )
    lines.append("")
    lines.append("## 주의사항")
    lines.append("")
    lines.append("- 현재 시세는 BrickRanker가 집계한 최근 6개월 신품 평균 판매가이며, 개별 거래·상태·구성에 따라 달라집니다.")
    lines.append("- CAGR은 출시가(RRP) 대비 현재 신품가 기준입니다. 실제 구매가·할인·수수료·배송·보관·세금은 반영하지 않았습니다.")
    lines.append("- 단종 후 가격 경로와 최대 낙폭은 데이터에 포함되지 않습니다.")
    lines.append("- 저유동성 세트는 평균가가 소수 거래에 좌우될 수 있어 랭킹에서 제외하거나 별도 표시했습니다.")
    lines.append("- BrickRanker는 신품 가격만 제공하므로 중고 가격과 Sealed Premium은 분석하지 않았습니다.")
    lines.append("- 단종일이 공개되지 않은 세트는 출시일과 상태를 이용해 추정했습니다.")
    lines.append("- 재출시·리메이크 세트는 가치가 희석될 수 있습니다.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(BRICKSET_RAW))
    parser.add_argument("--prices-dir", default=str(BRICKLINK_RAW_DIR))
    parser.add_argument("--cpi", default=str(CPI_RAW))
    parser.add_argument("--history-dir", default=str(BRICKRANKER_HISTORY_DIR))
    parser.add_argument("--out", default=str(SETS_JSON))
    parser.add_argument("--coverage-out", default=str(COVERAGE_JSON))
    parser.add_argument("--report", default=str(REPORT_MD))
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()

    as_of = parse_date(args.as_of) if args.as_of else today_utc()
    raw = load_json(args.input)
    if not raw:
        print(f"Brickset 원본이 없습니다: {args.input}")
        return 1
    raw_sets = raw.get("sets") or []
    if raw.get("complete") is False:
        print("경고: 수집 원본이 미완료 상태입니다. 일부 세트가 누락될 수 있습니다.")

    reasons = {}
    candidates = []
    for item in raw_sets:
        reason = exclusion_reason(item, today=as_of)
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        candidates.append(item)

    cpi_keys, cpi_values = load_cpi(args.cpi)
    cpi_latest = cpi_values[cpi_keys[-1]] if cpi_keys else None
    if not cpi_latest:
        print("CPI 데이터가 없어 실질 수익률은 계산하지 않습니다.")

    sets = [
        build_set(
            item,
            args.prices_dir,
            as_of,
            cpi_keys,
            cpi_values,
            extract_price_guide,
            cpi_latest,
        )
        for item in candidates
    ]
    for item in sets:
        item["spark"] = load_spark(args.history_dir, item["set_number"])
    sets.sort(key=lambda item: item["set_number"])

    themes = sort_theme_rows(aggregate(sets, "theme", "theme"))
    retire_years = aggregate(sets, "retire_year", "retire_year")
    bands = aggregate(sets, "rrp_band", "rrp_band")
    coverage = build_coverage(raw_sets, sets, reasons)

    meta = {
        "generated_at": now_iso(),
        "as_of": as_of.isoformat(),
        "currency": "USD",
        "source": raw.get("source") or "Brickset + BrickLink",
        "brickset_raw_count": len(raw_sets),
        "candidate_count": raw.get("candidate_count"),
        "candidate_reasons": raw.get("candidate_reasons") or {},
        "collection_complete": raw.get("complete"),
        "collection_errors": len(raw.get("errors") or []),
        "universe_count": len(sets),
        "rrp_min_usd": RRP_MIN_USD,
        "min_years_retired": MIN_YEARS_RETIRED,
        "min_sold_6m": MIN_SOLD_6M,
        "cpi_source": "FRED CPIAUCSL" if cpi_latest else None,
        "spark_sets": sum(1 for item in sets if item.get("spark")),
        "demo": False,
    }

    document = {
        "meta": meta,
        "coverage": coverage,
        "themes": themes,
        "retire_years": retire_years,
        "rrp_bands": bands,
        "top_cagr": [
            {
                "set_number": item["set_number"],
                "name": item["name"],
                "theme": item["theme"],
                "cagr_new": item["cagr_new"],
                "new_price": item["new_price"],
                "rrp_usd": item["rrp_usd"],
                "liquidity": item["liquidity"],
            }
            for item in top_rows(sets, "cagr_new", 20)
        ],
        "top_profit": [
            {
                "set_number": item["set_number"],
                "name": item["name"],
                "abs_profit_new": item["abs_profit_new"],
                "new_price": item["new_price"],
                "rrp_usd": item["rrp_usd"],
            }
            for item in top_rows(sets, "abs_profit_new", 20)
        ],
        "top_roi": [
            {
                "set_number": item["set_number"],
                "name": item["name"],
                "roi_new": item["roi_new"],
                "new_price": item["new_price"],
                "rrp_usd": item["rrp_usd"],
            }
            for item in top_rows(sets, "roi_new", 20)
        ],
        "sets": sets,
    }

    save_json(args.out, document)
    save_json(args.coverage_out, coverage)
    print(f"저장: {args.out}")
    print(f"분석 대상: {len(sets)} / 원본: {len(raw_sets)}")
    print(
        f"가격 확보 신품 {coverage['with_new_price']} / 중고 {coverage['with_used_price']} / 랭킹 적합 {coverage['rank_eligible']}"
    )
    if sets:
        print("상위 CAGR:")
        for item in top_rows(sets, "cagr_new", 10):
            print(
                f"  {item['set_number']:>10} {item['name'][:38]:<38} {pct(item['cagr_new']):>8} {money(item['new_price']):>12}"
            )
    if not args.no_report:
        report_path = write_report(
            args.report, meta, coverage, sets, themes, retire_years, bands
        )
        print(f"리포트: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
