"""Read RBI district deposit and credit tables (DBIE downloads) into one long table.

The DBIE export layout is not fixed: files carry a few title rows, the header
wording changes between releases, amounts may be in lakh or crore, and a file
may hold one quarter or several. This reader therefore:

- finds the header row by looking for "state" and "district" in the first rows,
- maps columns by keywords (see COLUMN_KEYWORDS),
- reads the unit from the title rows or headers unless one is given,
- takes the quarter from a period column, from the file name, or from the caller.

Output columns (Phase 1 C long format, before the crosswalk):
quarter_end, rbi_state, rbi_district, bank_group, measure, sector,
amount, unit, amount_cr, n_offices, source_file
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

UNIT_TO_CRORE = {
    "crore": 1.0,
    "lakh": 0.01,
    "million": 0.1,
    "thousand": 1e-4,
    "billion": 100.0,
}

COLUMN_KEYWORDS = {
    "rbi_state": ["state"],
    "rbi_district": ["district"],
    "n_offices": ["office", "branches"],
    "deposits": ["deposit"],
    "credit": ["credit", "advance"],
    "period": ["quarter", "period", "date", "year"],
    "bank_group": ["bank group", "bank-group"],
}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
TOTAL_ROW = re.compile(r"^\s*(all[\s-]*india|total|grand total|sub[\s-]*total)\b", re.I)


def to_crore(amount: float | pd.Series, unit: str) -> float | pd.Series:
    """Convert an amount in rupees `unit` (crore, lakh, million, thousand, billion) to crore."""
    unit = unit.lower().strip()
    if unit not in UNIT_TO_CRORE:
        raise ValueError(f"Unknown unit {unit!r}; expected one of {sorted(UNIT_TO_CRORE)}")
    return amount * UNIT_TO_CRORE[unit]


def quarter_end_from_month(year: int, month: int) -> pd.Timestamp:
    """Last day of the calendar quarter containing year-month."""
    return pd.Period(year=year, month=month, freq="M").asfreq("Q").end_time.normalize()


def parse_quarter_end(text) -> pd.Timestamp | None:
    """Parse the period labels seen in RBI files into a quarter-end date.

    Handles dates ("2018-09-30", "28-Sep-2018" = last reporting Friday),
    month-year labels ("Sep-2018", "September 2018") and Indian fiscal
    quarter labels ("2018-19:Q2", "Q2 2018-19"; fiscal Q1 = April to June).
    Returns None when nothing matches.
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None
    if isinstance(text, (pd.Timestamp,)) or hasattr(text, "year"):
        ts = pd.Timestamp(text)
        return quarter_end_from_month(ts.year, ts.month)
    s = str(text).strip()

    m = re.search(r"(\d{4})\s*-\s*(\d{2,4})\s*[:\s]*q\s*([1-4])|q\s*([1-4])\s*[:,\s]*(\d{4})\s*-\s*(\d{2,4})", s, re.I)
    if m:
        start_year = int(m.group(1) or m.group(5))
        fq = int(m.group(3) or m.group(4))
        month = 3 * fq + 3  # fiscal Q1 ends in June
        year = start_year if month <= 12 else start_year + 1
        return quarter_end_from_month(year, (month - 1) % 12 + 1)

    if not re.search(r"\d{1,2}[\-/\s][a-z]{3}", s, re.I):  # "28-Sep-2018" is a full date, handled below
        for m in re.finditer(r"\b([a-z]{3})[a-z]*[\s\-.,']*(\d{4}|\d{2})\b", s, re.I):
            if m.group(1).lower() in MONTHS:
                year = int(m.group(2))
                year = year + 2000 if year < 100 else year
                return quarter_end_from_month(year, MONTHS[m.group(1).lower()])

    iso = re.match(r"^\d{4}-\d{2}-\d{2}", s)
    ts = pd.to_datetime(s[:10] if iso else s, errors="coerce", dayfirst=not iso)
    if pd.notna(ts):
        return quarter_end_from_month(ts.year, ts.month)
    return None


def detect_unit(texts: list[str]) -> str | None:
    """Find "lakh", "crore" etc. in title rows or headers."""
    blob = " ".join(str(t) for t in texts if pd.notna(t)).lower()
    for unit in ["lakh", "crore", "million", "billion", "thousand"]:
        if re.search(rf"\b{unit}s?\b", blob):
            return unit
    return None


def _read_raw(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, header=None, dtype=object)
    return pd.read_csv(path, header=None, dtype=object, encoding_errors="replace")


def _find_header_row(raw: pd.DataFrame, max_rows: int = 30) -> int:
    for i in range(min(max_rows, len(raw))):
        cells = " | ".join(str(c).lower() for c in raw.iloc[i] if pd.notna(c))
        if "district" in cells and "state" in cells:
            return i
    raise ValueError("No header row with both 'state' and 'district' in the first rows")


def map_columns(headers: list[str]) -> dict[str, str]:
    """Map our names to the file's column headers by keyword. Each header is used once."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for ours, words in COLUMN_KEYWORDS.items():
        for h in headers:
            hl = str(h).lower()
            if h in used:
                continue
            if any(w in hl for w in words):
                # "credit-deposit ratio" and "per office" columns are derived, not amounts
                if ours in {"deposits", "credit"} and re.search(r"ratio|per\s|share|%|percent|growth", hl):
                    continue
                if ours == "rbi_state" and "district" in hl:
                    continue
                mapping[ours] = h
                used.add(h)
                break
    return mapping


def read_district_table(
    path: str | Path,
    quarter_end: str | None = None,
    unit: str | None = None,
    bank_group: str = "all",
    sector: str = "all",
) -> pd.DataFrame:
    """Read one DBIE district deposits/credit file into the long format.

    `quarter_end` and `unit` override what the file says. `bank_group` and
    `sector` label the whole file when it has no such column (for example a
    table for all scheduled commercial banks, all sectors).
    """
    path = Path(path)
    raw = _read_raw(path)
    h = _find_header_row(raw)
    title_rows = raw.iloc[:h].astype(str).values.ravel().tolist()
    headers = [str(c).strip() for c in raw.iloc[h]]
    df = raw.iloc[h + 1:].copy()
    df.columns = headers
    mapping = map_columns(headers)
    missing = {"rbi_state", "rbi_district"} - mapping.keys()
    if missing or not ({"deposits", "credit"} & mapping.keys()):
        raise ValueError(f"{path.name}: could not find columns {missing or 'deposits/credit'} in {headers}")

    unit = unit or detect_unit(title_rows + headers)
    if unit is None:
        raise ValueError(f"{path.name}: no unit (lakh/crore) found in the title rows; pass unit=")

    df = df.rename(columns={v: k for k, v in mapping.items()})
    # State names often appear only on the first row of each block
    df["rbi_state"] = df["rbi_state"].ffill()
    df = df[df["rbi_district"].notna()]
    df["rbi_district"] = df["rbi_district"].astype(str).str.strip()
    df["rbi_state"] = df["rbi_state"].astype(str).str.strip()
    df = df[~df["rbi_district"].str.match(TOTAL_ROW) & ~df["rbi_state"].str.match(TOTAL_ROW)]

    if quarter_end is not None:
        df["quarter_end"] = parse_quarter_end(quarter_end)
    elif "period" in df.columns:
        df["quarter_end"] = df["period"].map(parse_quarter_end)
    else:
        q = parse_quarter_end(path.stem.replace("_", " "))
        if q is None:
            q = next((parse_quarter_end(t) for t in title_rows if parse_quarter_end(t) is not None), None)
        if q is None:
            raise ValueError(f"{path.name}: no quarter found in a column, the file name or title; pass quarter_end=")
        df["quarter_end"] = q
    if df["quarter_end"].isna().any():
        bad = df.loc[df["quarter_end"].isna(), "period"].iloc[0]
        raise ValueError(f"{path.name}: could not parse period {bad!r}")

    if "bank_group" not in df.columns:
        df["bank_group"] = bank_group
    df["sector"] = sector
    df["n_offices"] = pd.to_numeric(df.get("n_offices"), errors="coerce") if "n_offices" in df else pd.NA

    measures = [m for m in ("deposits", "credit") if m in df.columns]
    long = df.melt(
        id_vars=["quarter_end", "rbi_state", "rbi_district", "bank_group", "sector", "n_offices"],
        value_vars=measures, var_name="measure", value_name="amount",
    )
    long["amount"] = pd.to_numeric(
        long["amount"].astype(str).str.replace(",", "").str.strip().replace({"-": None, "": None, "nan": None}),
        errors="coerce",
    )
    long["unit"] = unit
    long["amount_cr"] = to_crore(long["amount"], unit)
    long["source_file"] = path.name
    cols = ["quarter_end", "rbi_state", "rbi_district", "bank_group", "measure", "sector",
            "amount", "unit", "amount_cr", "n_offices", "source_file"]
    return long[cols].reset_index(drop=True)


def read_folder(folder: str | Path, **kwargs) -> pd.DataFrame:
    """Read every .xlsx/.xls/.csv file in a folder and stack them."""
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in {".xlsx", ".xls", ".csv"})
    if not files:
        raise FileNotFoundError(f"No .xlsx/.xls/.csv files in {folder}")
    return pd.concat([read_district_table(f, **kwargs) for f in files], ignore_index=True)
