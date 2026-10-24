from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
BRICKSET_RAW = RAW_DIR / "brickset.json"
BRICKSET_YEAR_DIR = RAW_DIR / "brickset"
BRICKLINK_RAW_DIR = RAW_DIR / "bricklink"
CPI_RAW = RAW_DIR / "cpi.csv"
SETS_JSON = DATA_DIR / "sets.json"
COVERAGE_JSON = DATA_DIR / "coverage.json"
REPORT_MD = ROOT / "report" / "LEGO_재테크_분석.md"

START_YEAR = 1990
END_YEAR = 2024
RRP_MIN_USD = 20.0
MIN_YEARS_RETIRED = 3.0
MIN_SOLD_6M = 10
MIN_YEARS_SINCE_RELEASE = 1.0

BRICKSET_PAGE_SIZE = 500
BRICKSET_SLEEP = 0.4

BRICKLINK_API_BASE = "https://api.bricklink.com/api/store/v1"
BRICKLINK_SLEEP = 0.6
BRICKLINK_DAILY_LIMIT = 4800
BRICKLINK_RETRY_MAX = 5
BRICKLINK_CURRENCY = "USD"

CPI_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"

EXCLUDED_THEMES = {
    "duplo",
    "4+",
    "juniors",
    "junior",
    "baby",
    "toddler",
    "primo",
    "quatro",
    "gear",
    "books",
    "magazines",
    "accessories",
    "key chains",
    "clocks",
    "watches",
    "stationery",
    "apparel",
    "video games",
    "puzzles",
    "games",
    "bags",
    "home",
    "kitchen",
    "lighting",
    "audio",
    "posters",
    "cards",
}

EXCLUDED_CATEGORIES = {
    "gear",
    "books",
    "magazines",
    "accessories",
    "key chains",
    "clocks",
    "watches",
    "stationery",
    "apparel",
    "video games",
    "puzzles",
    "games",
    "bags",
    "home",
    "kitchen",
    "lighting",
    "audio",
    "posters",
    "cards",
    "duplo",
    "4+",
    "juniors",
    "junior",
}

EXCLUDED_NAME_PARTS = (
    "polybag",
    "key chain",
    "keychain",
    "magnet",
    "lanyard",
    "poster",
    "sticker",
    "stationery",
    "notebook",
    "pencil",
    "mug",
    "cup",
    "bag tag",
    "coin",
    "patch",
    "tattoo",
    "watch",
    "clock",
    "torch",
    "headlamp",
)

EXCLUDED_PACKAGING_PARTS = ("polybag", "foil pack", "bag")

RRP_BANDS = (
    ("$20~$50", 20.0, 50.0),
    ("$50~$100", 50.0, 100.0),
    ("$100~$200", 100.0, 200.0),
    ("$200~$400", 200.0, 400.0),
    ("$400+", 400.0, float("inf")),
)

CURATED_CHECKS = (
    "10179-1",
    "10221-1",
    "10224-1",
    "10188-1",
    "10225-1",
    "10246-1",
    "10243-1",
    "21303-1",
    "75827-1",
    "71040-1",
)

BRICKRANKER_BASE = "https://brickranker.com"
BRICKRANKER_SITEMAP = "https://brickranker.com/sitemaps/themes-1.xml"
BRICKRANKER_RAW = RAW_DIR / "brickranker.json"
BRICKRANKER_CACHE_DIR = RAW_DIR / "brickranker"
BRICKRANKER_LISTING_DIR = BRICKRANKER_CACHE_DIR / "listings"
BRICKRANKER_SET_DIR = BRICKRANKER_CACHE_DIR / "sets"
BRICKRANKER_PRICES_DIR = RAW_DIR / "brickranker_prices"
BRICKRANKER_HISTORY_DIR = RAW_DIR / "brickranker_history"
BRICKRANKER_SLEEP = 0.7
BRICKRANKER_RETRY_MAX = 4
BRICKRANKER_USER_AGENT = (
    "lego-investment-analyzer/1.0 (personal LEGO market research; "
    "polite crawler; contact via project README)"
)

BRICKRANKER_EXCLUDED_THEMES = {
    "duplo",
    "4-juniors",
    "juniors",
    "junior",
    "primo",
    "quatro",
    "scala",
    "clikits",
    "books",
    "magazines",
    "gear",
}
