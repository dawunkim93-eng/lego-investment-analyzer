const PALETTE = [
  "#dd5a22", "#4c8f3a", "#2f6fb0", "#b8860b", "#8a5a9b",
  "#c4472e", "#2e8b8b", "#a35d2a", "#6b7a2f", "#7a5c8a",
  "#3b7a57", "#9b6b3f", "#5a6b8a", "#8a4a4a", "#4a7a8a",
];

const EXCLUSION_LABELS = {
  missing_set_number: "세트 번호 없음",
  excluded_theme: "제외 테마 (Duplo/4+/잡화 등)",
  excluded_category: "제외 카테고리",
  excluded_name: "제외 이름 패턴",
  excluded_packaging: "폴리백/봉투 포장",
  missing_launch_date: "출시일 없음",
  missing_exit_date: "단종일 없음",
  not_retired: "미단종",
  year_out_of_range: "출시 연도 범위 밖",
  missing_rrp: "RRP 없음",
  invalid_rrp: "RRP 데이터 오류(연도값)",
  rrp_below_min: "RRP $20 미만",
  missing_value: "현재가 없음",
  low_value_no_rrp: "저가·RRP 미확인",
  too_new: "출시 1년 미만",
};

const BAND_ORDER = ["$20~$50", "$50~$100", "$100~$200", "$200~$400", "$400+"];

const state = {
  data: null,
  source: null,
  tab: "overview",
  sortKey: "cagr",
  filters: {
    search: "",
    theme: "",
    band: "",
    yearMin: null,
    yearMax: null,
    minLiquidity: 0,
    eligibleOnly: true,
  },
  page: 1,
  pageSize: 50,
  themeColors: new Map(),
  rendered: false,
};

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatPct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(digits)}%`;
}

function formatMoney(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `$${Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number(value).toLocaleString("en-US");
}

function formatYears(value) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(1)}년`;
}

function formatDate(value) {
  if (!value) return "—";
  return String(value).slice(0, 10).replaceAll("-", ".");
}

function valueClass(value) {
  if (value === null || value === undefined || value === 0) return "";
  return value > 0 ? "pos" : "neg";
}

function median(values) {
  const cleaned = values
    .filter((value) => value !== null && value !== undefined && !Number.isNaN(value))
    .sort((a, b) => a - b);
  if (!cleaned.length) return null;
  const middle = Math.floor(cleaned.length / 2);
  return cleaned.length % 2
    ? cleaned[middle]
    : (cleaned[middle - 1] + cleaned[middle]) / 2;
}

function themeColor(theme) {
  const key = String(theme || "기타");
  if (!state.themeColors.has(key)) {
    state.themeColors.set(key, PALETTE[state.themeColors.size % PALETTE.length]);
  }
  return state.themeColors.get(key);
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function sparkline(values, extraClass = "") {
  const cleaned = (values || []).filter(
    (value) => value !== null && value !== undefined && !Number.isNaN(value)
  );
  if (cleaned.length < 2) return "";
  const width = 70;
  const height = 20;
  const pad = 1.5;
  const min = Math.min(...cleaned);
  const max = Math.max(...cleaned);
  const span = max - min || 1;
  const points = cleaned
    .map((value, index) => {
      const x = pad + (index * (width - pad * 2)) / (cleaned.length - 1);
      const y = height - pad - ((value - min) / span) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const direction = cleaned[cleaned.length - 1] >= cleaned[0] ? "pos" : "neg";
  return `<svg class="spark ${direction} ${extraClass}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${points}" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

function svg(tag, attrs = {}, text = null) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value !== null && value !== undefined) node.setAttribute(key, value);
  });
  if (text !== null) node.textContent = text;
  return node;
}

function emptyState(container, message) {
  container.innerHTML = `<div class="empty">${escapeHtml(message)}</div>`;
}

function attachTooltip(node, html) {
  node.addEventListener("mouseenter", (event) => {
    const tooltip = $("tooltip");
    tooltip.innerHTML = html;
    tooltip.classList.remove("hidden");
    positionTooltip(event);
  });
  node.addEventListener("mousemove", positionTooltip);
  node.addEventListener("mouseleave", () => $("tooltip").classList.add("hidden"));
}

function positionTooltip(event) {
  const tooltip = $("tooltip");
  if (tooltip.classList.contains("hidden")) return;
  const margin = 12;
  const left = Math.min(window.innerWidth - margin, Math.max(margin, event.clientX));
  const top = Math.max(margin, event.clientY);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function stats() {
  const sets = state.data?.sets || [];
  const eligible = sets.filter((item) => item.rank_eligible);
  const cagrs = eligible.map((item) => item.cagr_new).filter((value) => value !== null);
  const reals = eligible.map((item) => item.real_cagr_new).filter((value) => value !== null);
  const rois = eligible.map((item) => item.roi_new).filter((value) => value !== null);
  const medianCagr = median(cagrs);
  const medianReal = median(reals);
  const medianRoi = median(rois);
  const beat = cagrs.length
    ? cagrs.filter((value) => value > 0.07).length / cagrs.length
    : null;
  return { sets, eligible, cagrs, reals, rois, medianCagr, medianReal, medianRoi, beat };
}

function renderHero() {
  const meta = state.data?.meta || {};
  const { eligible, medianCagr, medianReal, beat } = stats();
  const universe = meta.universe_count ?? (state.data?.sets || []).length;
  const errors = meta.collection_errors || 0;
  const isDemo = Boolean(meta.demo) || state.source === "data/sets.sample.json";
  $("demo-card").classList.toggle("hidden", !isDemo);
  $("hero-badge").textContent = `신품 기준 · ${formatNumber(universe)}세트 · ${formatNumber(eligible.length)} 랭킹 적합`;
  $("hero-title").textContent = `중위 CAGR ${formatPct(medianCagr).replace(/^\+/, "")}`;
  $("hero-desc").innerHTML =
    `단종 3년 이상·최근 6개월 체결 10건 이상 <b>${formatNumber(eligible.length)}세트</b>를 분석했습니다. ` +
    `출시가(US RRP) 대비 현재 신품가 기준이며 실질 CAGR은 <b>${formatPct(medianReal).replace(/^\+/, "")}</b>입니다.`;
  const sourceLabel = meta.source || "BrickRanker";
  $("data-status").innerHTML =
    `<span><b>${escapeHtml(sourceLabel)}</b> · ${escapeHtml(meta.as_of || "")} 갱신</span>` +
    `<span>${formatNumber(universe)}세트 · ${
      errors ? `<span class="stale">수집 오류 ${formatNumber(errors)}건</span>` : "정상"
    }</span>`;
  if (isDemo) {
    $("demo-card").innerHTML =
      "<b>샘플 데이터</b><span>UI 확인용 가상 데이터입니다. 실제 분석 결과가 아닙니다.</span>";
  }
}

function renderKpis() {
  const meta = state.data?.meta || {};
  const { eligible, medianCagr, medianReal, medianRoi, beat } = stats();
  const cards = [
    ["분석 세트", formatNumber(meta.universe_count ?? (state.data?.sets || []).length), "단종 · RRP $20+"],
    ["중위 CAGR", formatPct(medianCagr), "랭킹 적합 기준", valueClass(medianCagr)],
    ["실질 CAGR", formatPct(medianReal), "CPI 보정", valueClass(medianReal)],
    ["S&P500 초과", beat === null ? "—" : `${(beat * 100).toFixed(1)}%`, "연 7% 기준"],
    ["중위 ROI", formatPct(medianRoi), "현재가 / RRP - 1", valueClass(medianRoi)],
    ["랭킹 적합", formatNumber(eligible.length), "단종 3년+ · 체결 10건+"],
  ];
  $("kpi-grid").innerHTML = cards
    .map(
      ([label, value, sub, cls]) => `
      <div class="kpi">
        <div class="k">${escapeHtml(label)}</div>
        <div class="v ${cls || ""}">${escapeHtml(value)}</div>
        <div class="s">${escapeHtml(sub)}</div>
      </div>`
    )
    .join("");
}

function renderTopList() {
  const container = $("top-list");
  const items = (state.data?.sets || [])
    .filter((item) => item.rank_eligible && item.cagr_new !== null)
    .sort((a, b) => b.cagr_new - a.cagr_new)
    .slice(0, 10);
  if (!items.length) {
    emptyState(container, "랭킹 적합 세트가 없습니다.");
    return;
  }
  container.innerHTML = items
    .map(
      (item, index) => `
      <button class="set-row" type="button" data-set-number="${escapeHtml(item.set_number)}">
        <span class="rank">${index + 1}</span>
        <span class="set-main">
          <span class="set-name">${escapeHtml(item.name)}</span>
          <span class="set-meta">${escapeHtml(item.theme)} · RRP ${formatMoney(item.rrp_usd)}</span>
        </span>
        <span class="set-side">
          <span class="set-cagr ${valueClass(item.cagr_new)}">${formatPct(item.cagr_new)}</span>
          ${sparkline(item.spark)}
          <span class="set-sub">${formatMoney(item.new_price)} · ${formatNumber(item.liquidity)}건</span>
        </span>
      </button>`
    )
    .join("");
}

function renderProfitList() {
  const container = $("profit-list");
  const items = (state.data?.sets || [])
    .filter((item) => item.rank_eligible && item.abs_profit_new !== null)
    .sort((a, b) => b.abs_profit_new - a.abs_profit_new)
    .slice(0, 5);
  if (!items.length) {
    emptyState(container, "절대 차익을 계산할 세트가 없습니다.");
    return;
  }
  container.innerHTML = items
    .map(
      (item, index) => `
      <button class="set-row" type="button" data-set-number="${escapeHtml(item.set_number)}">
        <span class="rank">${index + 1}</span>
        <span class="set-main">
          <span class="set-name">${escapeHtml(item.name)}</span>
          <span class="set-meta">${escapeHtml(item.theme)} · RRP ${formatMoney(item.rrp_usd)}</span>
        </span>
        <span class="set-side">
          <span class="set-cagr ${valueClass(item.abs_profit_new)}">${formatMoney(item.abs_profit_new)}</span>
          <span class="set-sub">CAGR ${formatPct(item.cagr_new)} · ${formatNumber(item.liquidity)}건</span>
        </span>
      </button>`
    )
    .join("");
}

function barRow(label, value, maxAbs, dataTheme = "", dataBand = "") {
  const width = maxAbs ? Math.min(100, (Math.abs(value) / maxAbs) * 100) : 0;
  const cls = valueClass(value);
  const themeAttr = dataTheme ? ` data-theme-filter="${escapeHtml(dataTheme)}"` : "";
  const bandAttr = dataBand ? ` data-band-filter="${escapeHtml(dataBand)}"` : "";
  return `
    <button class="bar-row" type="button"${themeAttr}${bandAttr}>
      <span class="bar-label">${escapeHtml(label)}</span>
      <span class="bar-track"><i class="bar-fill ${cls}" style="width:${width}%"></i></span>
      <span class="bar-value ${cls}">${formatPct(value)}</span>
    </button>`;
}

function renderThemeBars() {
  const container = $("theme-bars");
  const rows = (state.data?.themes || [])
    .filter((row) => row.eligible_count >= 5 && row.median_cagr_new !== null)
    .sort((a, b) => b.median_cagr_new - a.median_cagr_new)
    .slice(0, 10);
  if (!rows.length) {
    emptyState(container, "테마별로 비교할 세트가 부족합니다.");
    return;
  }
  const maxAbs = Math.max(0.01, ...rows.map((row) => Math.abs(row.median_cagr_new)));
  container.innerHTML = rows
    .map((row) => barRow(row.theme, row.median_cagr_new, maxAbs, row.theme))
    .join("");
}

function renderBandBars() {
  const container = $("band-bars");
  const rows = [...(state.data?.rrp_bands || [])]
    .filter((row) => row.median_cagr_new !== null)
    .sort((a, b) => BAND_ORDER.indexOf(a.rrp_band) - BAND_ORDER.indexOf(b.rrp_band));
  if (!rows.length) {
    emptyState(container, "RRP 구간별로 비교할 세트가 부족합니다.");
    return;
  }
  const maxAbs = Math.max(0.01, ...rows.map((row) => Math.abs(row.median_cagr_new)));
  container.innerHTML = rows
    .map((row) => barRow(row.rrp_band, row.median_cagr_new, maxAbs, "", row.rrp_band))
    .join("");
}

function getFilteredSets() {
  const filters = state.filters;
  return (state.data?.sets || []).filter((item) => {
    if (filters.eligibleOnly && !item.rank_eligible) return false;
    if (filters.theme && item.theme !== filters.theme) return false;
    if (filters.band && item.rrp_band !== filters.band) return false;
    if (filters.yearMin !== null && (item.retire_year ?? 0) < filters.yearMin) return false;
    if (filters.yearMax !== null && (item.retire_year ?? 9999) > filters.yearMax) return false;
    if ((item.liquidity ?? 0) < filters.minLiquidity) return false;
    if (item.cagr_new === null || item.new_price === null) return false;
    if (filters.search) {
      const haystack = `${item.set_number} ${item.name} ${item.theme} ${item.subtheme}`.toLowerCase();
      if (!haystack.includes(filters.search)) return false;
    }
    return true;
  });
}

function sortSets(sets) {
  const list = sets.slice();
  switch (state.sortKey) {
    case "roi":
      return list.sort((a, b) => (b.roi_new ?? -Infinity) - (a.roi_new ?? -Infinity));
    case "profit":
      return list.sort(
        (a, b) => (b.abs_profit_new ?? -Infinity) - (a.abs_profit_new ?? -Infinity)
      );
    case "liquidity":
      return list.sort((a, b) => (b.liquidity ?? 0) - (a.liquidity ?? 0));
    case "rrp":
      return list.sort((a, b) => (b.rrp_usd ?? 0) - (a.rrp_usd ?? 0));
    case "year":
      return list.sort((a, b) => (b.retire_year ?? 0) - (a.retire_year ?? 0));
    case "name":
      return list.sort((a, b) => a.name.localeCompare(b.name, "ko"));
    default:
      return list.sort((a, b) => (b.cagr_new ?? -Infinity) - (a.cagr_new ?? -Infinity));
  }
}

function badgesFor(item) {
  return [
    item.low_liquidity ? '<span class="pill low">저유동성</span>' : "",
    item.is_cmf ? '<span class="pill cmf">CMF</span>' : "",
    item.exit_date_estimated ? '<span class="pill est">단종일 추정</span>' : "",
  ]
    .filter(Boolean)
    .join("");
}

function renderRankTable() {
  const table = $("rank-table");
  const filtered = sortSets(getFilteredSets());
  const totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
  state.page = Math.min(Math.max(1, state.page), totalPages);
  const start = (state.page - 1) * state.pageSize;
  const pageItems = filtered.slice(start, start + state.pageSize);
  $("rank-count").textContent = `${formatNumber(filtered.length)}개 세트 · 신품 기준`;

  const head = `
    <thead><tr>
      <th>세트</th><th>테마</th><th>단종</th><th>RRP</th>
      <th>현재</th><th>CAGR</th><th>ROI</th><th>유동성</th>
    </tr></thead>`;
  if (!pageItems.length) {
    table.innerHTML = `${head}<tbody><tr><td colspan="8"><div class="empty">조건에 맞는 세트가 없습니다.</div></td></tr></tbody>`;
    $("pagination").innerHTML = "";
    return;
  }
  const body = pageItems
    .map(
      (item, index) => `
      <tr data-set-number="${escapeHtml(item.set_number)}">
        <td>
          <span class="tbl-rank">${start + index + 1}</span>
          <span class="set-name">${escapeHtml(item.name)}</span>
          <span class="set-meta">${escapeHtml(item.set_number)} ${badgesFor(item)}</span>
        </td>
        <td>${escapeHtml(item.theme)}</td>
        <td>${item.retire_year ?? "—"}</td>
        <td>${formatMoney(item.rrp_usd)}</td>
        <td>${formatMoney(item.new_price)}</td>
        <td class="${valueClass(item.cagr_new)}">${formatPct(item.cagr_new)}</td>
        <td class="${valueClass(item.roi_new)}">${formatPct(item.roi_new)}</td>
        <td>${formatNumber(item.liquidity)}</td>
      </tr>`
    )
    .join("");
  table.innerHTML = `${head}<tbody>${body}</tbody>`;
  renderPagination(totalPages, filtered.length);
}

function renderPagination(totalPages, totalItems) {
  const container = $("pagination");
  if (totalPages <= 1) {
    container.innerHTML = `<span class="count">${formatNumber(totalItems)}개</span>`;
    return;
  }
  const buttons = [];
  buttons.push(
    `<button class="page-btn" type="button" data-page="${state.page - 1}" ${state.page === 1 ? "disabled" : ""}>이전</button>`
  );
  const pages = new Set([1, totalPages, state.page, state.page - 1, state.page + 1]);
  const sorted = [...pages].filter((page) => page >= 1 && page <= totalPages).sort((a, b) => a - b);
  let previous = 0;
  sorted.forEach((page) => {
    if (page - previous > 1) buttons.push('<span class="page-ellipsis">…</span>');
    buttons.push(
      `<button class="page-btn ${page === state.page ? "on" : ""}" type="button" data-page="${page}">${page}</button>`
    );
    previous = page;
  });
  buttons.push(
    `<button class="page-btn" type="button" data-page="${state.page + 1}" ${state.page === totalPages ? "disabled" : ""}>다음</button>`
  );
  container.innerHTML = buttons.join("");
}

function renderThemes() {
  const table = $("theme-table");
  const rows = (state.data?.themes || []).filter((row) => row.count > 0);
  if (!rows.length) {
    table.innerHTML = '<tbody><tr><td><div class="empty">테마 데이터가 없습니다.</div></td></tr></tbody>';
    return;
  }
  const head = `
    <thead><tr>
      <th>테마</th><th>분석</th><th>적합</th><th>CAGR</th><th>ROI</th><th>유동성</th>
    </tr></thead>`;
  const body = rows
    .map(
      (row) => `
      <tr data-theme-filter="${escapeHtml(row.theme)}">
        <td>${escapeHtml(row.theme)}</td>
        <td>${formatNumber(row.count)}</td>
        <td>${formatNumber(row.eligible_count)}</td>
        <td class="${valueClass(row.median_cagr_new)}">${formatPct(row.median_cagr_new)}</td>
        <td class="${valueClass(row.median_roi_new)}">${formatPct(row.median_roi_new)}</td>
        <td>${formatNumber(row.median_liquidity)}</td>
      </tr>`
    )
    .join("");
  table.innerHTML = `${head}<tbody>${body}</tbody>`;
  renderHeatmap();
  renderBandBars();
}

function renderHeatmap() {
  const container = $("heatmap");
  const sets = (state.data?.sets || []).filter((item) => item.rank_eligible);
  if (!sets.length) {
    emptyState(container, "히트맵을 그릴 데이터가 없습니다.");
    return;
  }
  const themeCounts = new Map();
  sets.forEach((item) => {
    themeCounts.set(item.theme, (themeCounts.get(item.theme) || 0) + 1);
  });
  const themes = [...themeCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([theme]) => theme);
  const years = [...new Set(sets.map((item) => item.retire_year).filter(Boolean))]
    .sort((a, b) => a - b)
    .slice(-16);
  const matrix = new Map();
  sets.forEach((item) => {
    if (!themes.includes(item.theme) || !years.includes(item.retire_year)) return;
    const key = `${item.theme}||${item.retire_year}`;
    if (!matrix.has(key)) matrix.set(key, []);
    matrix.get(key).push(item.cagr_new);
  });
  const header = `<tr><th>테마</th>${years.map((year) => `<th>${year}</th>`).join("")}</tr>`;
  const body = themes
    .map((theme) => {
      const cells = years
        .map((year) => {
          const values = matrix.get(`${theme}||${year}`) || [];
          const value = median(values);
          if (value === null) return '<td class="heat-empty">—</td>';
          const alpha = Math.min(0.34, 0.1 + Math.abs(value) * 0.55);
          const background =
            value >= 0
              ? `rgba(76,143,58,${alpha})`
              : `rgba(196,71,46,${alpha})`;
          const color = value >= 0 ? "var(--pos)" : "var(--neg)";
          return `<td style="background:${background};color:${color}" title="${escapeHtml(theme)} ${year} · ${formatPct(value)} · n=${values.length}">${formatPct(value, 0)}</td>`;
        })
        .join("");
      return `<tr><td>${escapeHtml(theme)}</td>${cells}</tr>`;
    })
    .join("");
  container.innerHTML = `<table class="heatmap"><thead>${header}</thead><tbody>${body}</tbody></table>`;
}

function renderScatter() {
  const container = $("scatter");
  const items = (state.data?.sets || [])
    .filter(
      (item) =>
        item.rank_eligible &&
        item.cagr_new !== null &&
        item.liquidity !== null &&
        item.liquidity > 0
    )
    .sort((a, b) => b.liquidity - a.liquidity)
    .slice(0, 2500);
  if (!items.length) {
    emptyState(container, "산점도로 표시할 세트가 없습니다.");
    return;
  }
  const width = Math.max(container.clientWidth || 500, 320);
  const height = 260;
  const margin = { top: 14, right: 12, bottom: 34, left: 42 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  container.replaceChildren();
  const root = svg("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    preserveAspectRatio: "xMinYMin meet",
  });
  container.appendChild(root);

  const cagrs = items.map((item) => item.cagr_new);
  const yMinRaw = Math.min(0, ...cagrs);
  const yMaxRaw = Math.max(0.05, ...cagrs);
  const yPad = (yMaxRaw - yMinRaw) * 0.08 || 0.04;
  const yMin = yMinRaw - yPad;
  const yMax = yMaxRaw + yPad;
  const xMin = Math.max(1, Math.min(...items.map((item) => item.liquidity)));
  const xMax = Math.max(xMin * 10, ...items.map((item) => item.liquidity));
  const logMin = Math.log10(xMin);
  const logMax = Math.log10(xMax);
  const x = (value) =>
    margin.left + ((Math.log10(Math.max(1, value)) - logMin) / (logMax - logMin || 1)) * plotWidth;
  const y = (value) =>
    margin.top + (1 - (value - yMin) / (yMax - yMin || 1)) * plotHeight;

  const yTicks = niceTicks(yMin, yMax, 5);
  yTicks.forEach((tick) => {
    root.appendChild(
      svg("line", {
        x1: margin.left,
        x2: width - margin.right,
        y1: y(tick),
        y2: y(tick),
        class: "svg-grid",
      })
    );
    root.appendChild(
      svg(
        "text",
        {
          x: margin.left - 6,
          y: y(tick) + 3,
          "text-anchor": "end",
          class: "svg-muted",
          "font-size": "9",
        },
        formatPct(tick, 0)
      )
    );
  });

  const xTicks = [];
  for (let power = Math.floor(logMin); power <= Math.ceil(logMax); power += 1) {
    const value = 10 ** power;
    if (value >= xMin * 0.9 && value <= xMax * 1.1) xTicks.push(value);
  }
  xTicks.forEach((tick) => {
    root.appendChild(
      svg("line", {
        x1: x(tick),
        x2: x(tick),
        y1: margin.top,
        y2: height - margin.bottom,
        class: "svg-grid",
      })
    );
    root.appendChild(
      svg(
        "text",
        {
          x: x(tick),
          y: height - margin.bottom + 15,
          "text-anchor": "middle",
          class: "svg-muted",
          "font-size": "9",
        },
        formatNumber(tick)
      )
    );
  });

  root.appendChild(
    svg(
      "text",
      {
        x: width / 2,
        y: height - 3,
        "text-anchor": "middle",
        class: "svg-muted",
        "font-size": "9",
      },
      "6개월 체결 수량 (로그)"
    )
  );
  root.appendChild(
    svg(
      "text",
      { x: 8, y: 10, class: "svg-muted", "font-size": "9" },
      "CAGR"
    )
  );

  items.forEach((item) => {
    const radius = Math.max(2.5, Math.min(9, 2.5 + Math.sqrt(item.liquidity) / 8));
    const circle = svg("circle", {
      cx: x(item.liquidity),
      cy: y(item.cagr_new),
      r: radius,
      fill: themeColor(item.theme),
      opacity: 0.75,
      style: "cursor:pointer",
    });
    attachTooltip(
      circle,
      `<strong>${escapeHtml(item.name)}</strong><span class="muted">${escapeHtml(item.set_number)} · ${escapeHtml(item.theme)}</span><br>CAGR ${formatPct(item.cagr_new)} · ${formatMoney(item.new_price)}<br>6개월 체결 ${formatNumber(item.liquidity)}건`
    );
    circle.addEventListener("click", () => openSheet(item.set_number));
    root.appendChild(circle);
  });
}

function niceTicks(min, max, count = 5) {
  if (min === max) return [min];
  const span = max - min;
  const step = span / Math.max(1, count - 1);
  const magnitude = 10 ** Math.floor(Math.log10(Math.abs(step) || 1));
  const residual = step / magnitude;
  const niceStep = residual >= 5 ? 5 * magnitude : residual >= 2 ? 2 * magnitude : magnitude;
  const start = Math.floor(min / niceStep) * niceStep;
  const end = Math.ceil(max / niceStep) * niceStep;
  const ticks = [];
  for (let value = start; value <= end + niceStep / 2; value += niceStep) {
    ticks.push(Number(value.toFixed(10)));
  }
  return ticks;
}

function renderData() {
  const meta = state.data?.meta || {};
  const coverage = state.data?.coverage || {};
  const sets = state.data?.sets || [];
  const estimated = sets.filter((item) => item.exit_date_estimated).length;
  const errors = meta.collection_errors || 0;
  const items = [
    ["분석 세트", coverage.universe_sets, "단종 · RRP $20+"],
    ["신품 가격", coverage.with_new_price, `${((coverage.coverage_new_pct ?? 0) * 100).toFixed(1)}%`],
    ["랭킹 적합", coverage.rank_eligible, "단종 3년+ · 체결 10건+"],
    ["저유동성", coverage.low_liquidity, "6개월 체결 10건 미만"],
    ["단종일 추정", estimated, "공개 단종일 없음"],
    ["수집 오류", errors, meta.collection_complete === false ? "일부 누락 가능" : "수집 완료"],
  ];
  $("coverage-grid").innerHTML = items
    .map(
      ([label, value, note]) => `
      <div class="coverage-item">
        <strong>${formatNumber(value ?? 0)}</strong>
        <span>${escapeHtml(label)}</span>
        <span>${escapeHtml(note)}</span>
      </div>`
    )
    .join("");
  $("collection-note").textContent = errors
    ? `수집 오류 ${formatNumber(errors)}건 · 원본이 미완료 상태일 수 있습니다.`
    : "수집 완료";

  const reasonMap = {
    ...(meta.candidate_reasons || {}),
    ...(coverage.excluded_reasons || {}),
  };
  const reasons = Object.entries(reasonMap).sort((a, b) => b[1] - a[1]);
  const table = $("exclusion-table");
  table.innerHTML = `
    <thead><tr><th>사유</th><th>세트 수</th></tr></thead>
    <tbody>${
      reasons.length
        ? reasons
            .map(
              ([reason, count]) => `
              <tr>
                <td>${escapeHtml(EXCLUSION_LABELS[reason] || reason)}</td>
                <td>${formatNumber(count)}</td>
              </tr>`
            )
            .join("")
        : '<tr><td colspan="2"><div class="empty">제외된 세트가 없습니다.</div></td></tr>'
    }</tbody>`;
}

function openSheet(setNumber) {
  const item = (state.data?.sets || []).find((row) => row.set_number === setNumber);
  if (!item) return;
  const profit =
    item.new_price !== null && item.rrp_usd !== null
      ? item.new_price - item.rrp_usd
      : null;
  const image = item.image
    ? `<img class="sheet-img" src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}">`
    : `<div class="sheet-img sheet-placeholder">${escapeHtml(item.set_number)}</div>`;
  const badges = badgesFor(item);
  const metrics = [
    ["RRP", formatMoney(item.rrp_usd, 2), ""],
    ["현재 신품", formatMoney(item.new_price, 2), ""],
    ["CAGR", formatPct(item.cagr_new), valueClass(item.cagr_new)],
    ["실질 CAGR", formatPct(item.real_cagr_new), valueClass(item.real_cagr_new)],
    ["ROI", formatPct(item.roi_new), valueClass(item.roi_new)],
    ["절대 차익", formatMoney(profit, 2), valueClass(profit)],
    ["6개월 체결", formatNumber(item.liquidity), ""],
    ["데이터 신뢰도", item.confidence || "—", ""],
  ];
  const rows = [
    ["출시 연도", item.year ?? "—"],
    ["보유 연수", formatYears(item.years_since_release)],
    ["단종 후", formatYears(item.years_retired)],
    ["브릭 / 미니피그", `${formatNumber(item.pieces)} / ${formatNumber(item.minifigs)}`],
    ["신품 가격 범위", `${formatMoney(item.new_low, 2)} ~ ${formatMoney(item.new_high, 2)}`],
    ["6개월 체결", `${formatNumber(item.new_qty)}건`],
    [
      "단종일",
      item.exit_date_estimated
        ? `${formatDate(item.exit_date)} (추정)`
        : formatDate(item.exit_date),
    ],
    ["테마", item.subtheme ? `${item.theme} / ${item.subtheme}` : item.theme],
  ];
  $("sheet-content").innerHTML = `
    <div class="sheet-header">
      ${image}
      <div>
        <h3 class="sheet-title" id="sheet-title">${escapeHtml(item.name)}</h3>
        <div class="sheet-sub">${escapeHtml(item.set_number)} · ${escapeHtml(item.theme)}</div>
        <div class="sheet-sub">출시 ${formatDate(item.launch_date)} · 단종 ${formatDate(item.exit_date)}</div>
        <div class="sheet-badges">${badges}</div>
      </div>
    </div>
    ${sparkline(item.spark, "spark-lg")}
    <div class="metrics-grid">
      ${metrics
        .map(
          ([label, value, cls]) =>
            `<div class="metric-box"><span>${escapeHtml(label)}</span><strong class="${cls}">${escapeHtml(value)}</strong></div>`
        )
        .join("")}
    </div>
    <table class="sheet-table"><tbody>
      ${rows
        .map(
          ([label, value]) =>
            `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`
        )
        .join("")}
    </tbody></table>
    <div class="sheet-links">
      ${item.source_url ? `<a class="btn-link" href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">BrickRanker</a>` : ""}
      <a class="btn-link" href="${escapeHtml(item.brickset_url)}" target="_blank" rel="noreferrer">Brickset</a>
      <a class="btn-link" href="${escapeHtml(item.bricklink_url)}" target="_blank" rel="noreferrer">BrickLink</a>
    </div>
    <p class="sheet-note">BrickRanker 신품 기준 · 최근 6개월 평균 판매가입니다. 실제 거래가는 상태·구성에 따라 달라질 수 있습니다.</p>`;
  $("sheet").classList.remove("hidden");
  $("sheet").setAttribute("aria-hidden", "false");
  document.body.classList.add("sheet-open");
}

function closeSheet() {
  $("sheet").classList.add("hidden");
  $("sheet").setAttribute("aria-hidden", "true");
  document.body.classList.remove("sheet-open");
}

function applyTab(tab) {
  state.tab = tab;
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const on = button.dataset.tab === tab;
    button.classList.toggle("on", on);
    if (button.getAttribute("role") === "tab") {
      button.setAttribute("aria-selected", on ? "true" : "false");
    }
  });
  document.querySelectorAll(".tabpane").forEach((pane) => {
    pane.classList.toggle("on", pane.id === `tab-${tab}`);
  });
}

function switchTab(tab) {
  applyTab(tab);
  if (tab === "ranking") renderRankTable();
  if (tab === "themes") {
    renderThemes();
    requestAnimationFrame(renderScatter);
  }
  if (tab === "data") renderData();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setFilterTheme(theme) {
  state.filters.theme = theme;
  state.filters.search = "";
  $("f-theme").value = theme;
  $("f-search").value = "";
  state.page = 1;
  switchTab("ranking");
}

function setFilterBand(band) {
  state.filters.band = band;
  state.filters.search = "";
  $("f-band").value = band;
  $("f-search").value = "";
  state.page = 1;
  switchTab("ranking");
}

function initTheme() {
  const button = $("theme-btn");
  const meta = document.querySelector('meta[name="theme-color"]');
  let saved = null;
  try {
    saved = localStorage.getItem("lego-theme");
  } catch (error) {
    saved = null;
  }
  if (saved === "dark") document.body.classList.add("dark");
  const update = () => {
    const dark = document.body.classList.contains("dark");
    button.textContent = dark ? "라이트" : "다크";
    button.setAttribute("aria-label", dark ? "라이트 모드 전환" : "다크 모드 전환");
    if (meta) meta.setAttribute("content", dark ? "#131416" : "#f7f7f5");
  };
  button.addEventListener("click", () => {
    document.body.classList.toggle("dark");
    try {
      localStorage.setItem("lego-theme", document.body.classList.contains("dark") ? "dark" : "light");
    } catch (error) {
      return;
    }
    update();
  });
  update();
}

function initTabs() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
}

function initGlobalClicks() {
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-close]")) {
      closeSheet();
      return;
    }
    const pageButton = event.target.closest("[data-page]");
    if (pageButton) {
      const page = Number(pageButton.dataset.page);
      if (!Number.isNaN(page)) {
        state.page = page;
        renderRankTable();
        const card = $("rank-table")?.closest(".card");
        card?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      return;
    }
    const themeButton = event.target.closest("[data-theme-filter]");
    if (themeButton) {
      setFilterTheme(themeButton.dataset.themeFilter);
      return;
    }
    const bandButton = event.target.closest("[data-band-filter]");
    if (bandButton) {
      setFilterBand(bandButton.dataset.bandFilter);
      return;
    }
    const setRow = event.target.closest("[data-set-number]");
    if (setRow) {
      openSheet(setRow.dataset.setNumber);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("sheet").classList.contains("hidden")) {
      closeSheet();
    }
  });
}

function initFilters() {
  const themeSelect = $("f-theme");
  const themes = (state.data?.themes || [])
    .filter((row) => row.count > 0)
    .slice()
    .sort((a, b) => b.count - a.count);
  themeSelect.innerHTML =
    '<option value="">전체 테마</option>' +
    themes
      .map(
        (row) =>
          `<option value="${escapeHtml(row.theme)}">${escapeHtml(row.theme)} (${row.count})</option>`
      )
      .join("");

  const bandSelect = $("f-band");
  const availableBands = new Set((state.data?.rrp_bands || []).map((row) => row.rrp_band));
  bandSelect.innerHTML =
    '<option value="">전체 구간</option>' +
    BAND_ORDER.filter((band) => availableBands.has(band))
      .map((band) => `<option value="${escapeHtml(band)}">${escapeHtml(band)}</option>`)
      .join("");

  $("f-search").addEventListener(
    "input",
    debounce((event) => {
      state.filters.search = event.target.value.trim().toLowerCase();
      state.page = 1;
      renderRankTable();
    }, 120)
  );
  themeSelect.addEventListener("change", (event) => {
    state.filters.theme = event.target.value;
    state.page = 1;
    renderRankTable();
  });
  bandSelect.addEventListener("change", (event) => {
    state.filters.band = event.target.value;
    state.page = 1;
    renderRankTable();
  });
  $("f-year-min").addEventListener("change", (event) => {
    state.filters.yearMin = event.target.value ? Number(event.target.value) : null;
    state.page = 1;
    renderRankTable();
  });
  $("f-year-max").addEventListener("change", (event) => {
    state.filters.yearMax = event.target.value ? Number(event.target.value) : null;
    state.page = 1;
    renderRankTable();
  });
  $("f-liquidity").addEventListener("change", (event) => {
    state.filters.minLiquidity = Math.max(0, Number(event.target.value) || 0);
    state.page = 1;
    renderRankTable();
  });
  $("f-eligible").addEventListener("change", (event) => {
    state.filters.eligibleOnly = event.target.checked;
    state.page = 1;
    renderRankTable();
  });
  $("f-sort").addEventListener("change", (event) => {
    state.sortKey = event.target.value;
    state.page = 1;
    renderRankTable();
  });
  $("f-reset").addEventListener("click", () => {
    state.filters = {
      search: "",
      theme: "",
      band: "",
      yearMin: null,
      yearMax: null,
      minLiquidity: 0,
      eligibleOnly: true,
    };
    state.sortKey = "cagr";
    state.page = 1;
    $("f-search").value = "";
    themeSelect.value = "";
    bandSelect.value = "";
    $("f-year-min").value = "";
    $("f-year-max").value = "";
    $("f-liquidity").value = "0";
    $("f-eligible").checked = true;
    $("f-sort").value = "cagr";
    renderRankTable();
  });
}

async function loadData() {
  for (const source of ["data/sets.json", "data/sets.sample.json"]) {
    try {
      const response = await fetch(source, { cache: "no-store" });
      if (!response.ok) continue;
      const document = await response.json();
      return { document, source };
    } catch (error) {
      continue;
    }
  }
  return { document: null, source: null };
}

function renderAll() {
  renderHero();
  renderKpis();
  renderTopList();
  renderThemeBars();
  renderProfitList();
  renderThemes();
  renderData();
  renderRankTable();
  applyTab(state.tab);
}

async function init() {
  initTheme();
  initTabs();
  initGlobalClicks();
  const { document, source } = await loadData();
  if (!document) {
    $("hero-title").textContent = "데이터를 불러오지 못했습니다";
    $("hero-desc").textContent =
      "data/sets.json을 생성하거나 python3 -m http.server로 실행하세요.";
    $("data-status").innerHTML = '<span class="stale">데이터 로드 실패</span>';
    $("demo-card").classList.remove("hidden");
    $("demo-card").innerHTML =
      "<b>오류</b><span>data/sets.json 파일을 확인하세요.</span>";
    return;
  }
  state.data = document;
  state.data.sets = state.data.sets || [];
  state.data.themes = state.data.themes || [];
  state.data.rrp_bands = state.data.rrp_bands || [];
  state.data.coverage = state.data.coverage || {};
  state.source = source;
  initFilters();
  renderAll();
  window.addEventListener(
    "resize",
    debounce(() => {
      if (state.tab === "themes") renderScatter();
    }, 180)
  );
}

init();
