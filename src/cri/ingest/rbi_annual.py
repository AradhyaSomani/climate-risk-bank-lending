"""Annual BSR district credit by occupation (Phase 1 C, the sector split).

RBI's annual "Basic Statistical Returns" volumes (March 2002 to March 2025, plus the loose
March 2026 tables) have one table of credit by district and occupation: Table 5.9 to 2018,
Table 3.9 from 2019. It is the only district table with a sector split, and it counts credit
by place of utilisation (where the money is used), unlike the quarterly statement, which counts
it by place of sanction (docs/00_location_basis.md). All scheduled commercial banks, RRBs
included; no split by bank group.

The table comes in two layouts:

- 2002 to 2010 (`wide`): one sheet per state, district names across a header row, an account
  and an amount column per district, occupations down the rows; amounts in rupees thousand,
  often as text with Indian digit grouping ("13,20,46").
- 2011 onwards (`long`): one sheet, one row per district and occupation, with region, state
  and district columns that are filled only on a district's first row.

This module reads the top-level occupations (I. Agriculture to VIII. All others, and the total
where the table has one), converts amounts to rupees crore and writes one long table:
`quarter_end, rbi_state, rbi_district, occupation, accounts, amount_cr` to
data/interim/rbi_annual_occupation.parquet. `SECTORS` groups the occupations into the sectors
the panel uses (agriculture, industry, services, personal, other).

    python -m cri.ingest.rbi_annual
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config
from cri.ingest.rbi_bsr import detect_unit, to_crore

log = logging.getLogger(__name__)

INTERIM_FILE = "rbi_annual_occupation.parquet"
REVIEW_FILE = "rbi_annual_review.csv"
COLUMNS = ["quarter_end", "rbi_state", "rbi_district", "occupation", "accounts", "amount_cr"]

# Top-level occupation rows, by the first keyword their label contains
OCCUPATIONS = {
    "agriculture": "agriculture", "industry": "industry", "transport": "transport",
    "professional": "professional", "personal": "personal", "trade": "trade",
    "finance": "finance", "all others": "other", "total": "total",
}
# The panel's sectors (task list Phase 2 D: agriculture, industry, services, personal)
SECTORS = {
    "agriculture": "agriculture", "industry": "industry", "transport": "services",
    "professional": "services", "trade": "services", "finance": "services",
    "personal": "personal", "other": "other",
}
TOP_LEVEL = re.compile(r"^\s*(VIII|VII|VI|IV|IX|V|III|II|I)\s*[.)]\s*(.+)$")
TABLE_FILE = re.compile(r"^table[\s_]*(no\.?)?[\s_.]*[35][._]?0?9(?![0-9])", re.I)
YEAR = re.compile(r"MARCH[\s,-]*(\d{4})", re.I)


# ---------------------------------------------------------------------------- helpers

def number(v) -> float:
    """'13,20,46' (Indian grouping), 1234.0 -> float. A dash is RBI's nil (0); a stray
    letter next to the digits ('347,73,30I' in March 2010) is dropped; blank is NaN."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    s = str(v).strip()
    if s and re.fullmatch(r"[-\u2010-\u2015\s]+", s):
        return 0.0
    digits = re.sub(r"[^0-9.]", "", s)
    try:
        return float(digits)
    except ValueError:
        return np.nan


def text(v) -> str:
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) \
        else re.sub(r"\s+", " ", str(v)).strip()


def occupation(label: str) -> str | None:
    """Top-level occupation code of a row label, or None for a sub-item or anything else."""
    m = TOP_LEVEL.match(label)
    body = (m.group(2) if m else label).lower()
    if not m and not body.startswith("total"):
        return None
    for key, code in OCCUPATIONS.items():
        if key in body:
            return code
    return None


def state_name(s: str) -> str:
    s = re.sub(r"^\s*STATE\s*[:\-]\s*", "", text(s), flags=re.I)
    return s.strip().upper()


def read_book(data: bytes, suffix: str) -> dict[str, pd.DataFrame]:
    """All sheets of a workbook. The calamine engine reads every year, including the 2014
    file that xlrd rejects; xlrd and openpyxl are the fallback when it is not installed."""
    try:
        return pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object,
                             engine="calamine")
    except ImportError:
        engine = "xlrd" if suffix == ".xls" else "openpyxl"
        return pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object,
                             engine=engine)


def year_of(sheets: dict[str, pd.DataFrame]) -> int:
    for d in sheets.values():
        for v in d.iloc[:12].to_numpy().ravel():
            m = YEAR.search(text(v))
            if m:
                return int(m.group(1))
    raise ValueError("no 'MARCH <year>' in the table's title rows")


def unit_of(sheets: dict[str, pd.DataFrame]) -> str:
    texts = [text(v) for d in sheets.values() for v in d.iloc[:12].to_numpy().ravel()]
    return detect_unit(texts) or "thousand"


# ---------------------------------------------------------------------------- layouts

def _occupation_column(d: pd.DataFrame) -> int | None:
    """The occupation column of a long-layout sheet, or None for the wide layout. A long
    sheet has a header row with DISTRICT and OCCUPATION cells (2014 on) or 'STATE: ...
    DISTRICT: ...' lines above each district (2011 to 2013)."""
    cells = d.map(text)
    up = cells.apply(lambda col: col.str.upper())
    long = any({"DISTRICT", "OCCUPATION"} <= set(up.iloc[i]) for i in range(min(len(d), 15))) \
        or up.apply(lambda col: col.str.contains("DISTRICT:", regex=False)).to_numpy().any()
    if not long:
        return None
    counts = {c: sum(occupation(v) == "agriculture" for v in cells.iloc[:, c])
              for c in range(1, d.shape[1])}
    c, n = max(counts.items(), key=lambda kv: kv[1])
    return c if n else None


DISTRICT_HEADER = re.compile(r"STATE\s*:\s*(.+?)\s*DISTRICT\s*:\s*(.+)$", re.I)


def parse_long(d: pd.DataFrame, o: int) -> pd.DataFrame:
    """2011 onwards: one row per district and occupation.

    2011 to 2013 put a line 'NORTHERN REGION, STATE: HARYANA DISTRICT: AMBALA' above each
    district, with the district's total on it (2013 has no state column at all); from 2014
    the state and district columns sit left of the occupation and are filled on a district's
    first row only.
    """
    cells = d.map(text)
    occ = cells.iloc[:, o].map(occupation)
    head = cells.apply(lambda r: next((m for m in (DISTRICT_HEADER.search(v) for v in r) if m),
                                      None), axis=1)
    is_head = head.notna()
    keep = occ.notna() | is_head
    num = d[keep].iloc[:, o + 1:].apply(lambda col: col.map(number))
    filled = [c for c in num.columns if num.loc[occ.notna(), c].notna().mean() > 0.5]
    if len(filled) < 2:
        raise ValueError("long layout: expected an account and an amount column")
    acc, amt = filled[-2], filled[-1]
    if is_head.any():
        state = head.map(lambda m: m.group(1) if m else np.nan).ffill()
        dist = head.map(lambda m: m.group(2) if m else np.nan).ffill()
        occ = occ.where(~is_head, "total")
    else:
        # names on a district's first row only: carry them down the occupation rows
        dist = cells.iloc[:, o - 1].where(occ.notna()).replace("", np.nan).ffill()
        state = cells.iloc[:, o - 2].where(occ.notna()).replace("", np.nan).ffill()
    return pd.DataFrame({"rbi_state": state[keep].map(state_name),
                         "rbi_district": dist[keep].str.upper().str.strip(),
                         "occupation": occ[keep],
                         "accounts": num[acc], "amount": num[amt]}).reset_index(drop=True)


NOT_A_NAME = re.compile(r"amount|rupees|march|table|^\(", re.I)


def _header_rows(cells: pd.DataFrame, u: int, first: int) -> list[int]:
    """Rows above the 'No. of' row `u` that hold district names, top to bottom. Names sit on
    the row above, sometimes with a blank row between (2009) and sometimes wrapped onto a
    second row ('SAHIBZADA AJIT SINGH' / 'NAGAR', 2009)."""
    rows: list[int] = []
    for i in range(u - 1, max(u - 4, -1), -1):
        has = any(v and not NOT_A_NAME.search(v) for v in cells.iloc[i, first:])
        if has:
            rows.append(i)
        elif rows:
            break
    return sorted(rows)


def parse_wide(sheets: dict[str, pd.DataFrame], relabel: list[dict] | None = None
               ) -> pd.DataFrame:
    """2002 to 2010: a sheet per state; district names across the row above 'No. of'.
    `relabel`: entries of configs/rbi_annual.yaml for this year (state, district, nth,
    rename)."""
    fixes = {(f["state"].upper(), f["district"].upper(), int(f["nth"])): f["rename"].upper()
             for f in relabel or []}
    out = []
    for sheet, d in sheets.items():
        seen: dict[str, int] = {}
        cells = d.map(text)
        unit_rows = [i for i in range(len(d))
                     if any(v.upper().startswith("NO. OF") for v in cells.iloc[i])]
        for k, u in enumerate(unit_rows):
            first = min(c for c in range(d.shape[1])
                        if cells.iat[u, c].upper().startswith("NO. OF"))
            header = _header_rows(cells, u, first)
            end = unit_rows[k + 1] - 1 if k + 1 < len(unit_rows) else len(d)
            # 'STATE : X', sometimes with X in the next cell
            joined = [" ".join(v for v in cells.iloc[i, :first] if v) for i in range(u)]
            above = [t for t in joined if t.upper().startswith("STATE")]
            state = state_name(above[-1]) if above else sheet.strip().upper()
            names = {c: " ".join(cells.iat[i, c] for i in header if cells.iat[i, c]
                                 and not NOT_A_NAME.search(cells.iat[i, c])).upper()
                     for c in range(first, d.shape[1])}
            districts = {c: n for c, n in names.items() if n and not n[0].isdigit()}
            for c, name in districts.items():
                seen[name] = seen.get(name, 0) + 1
                districts[c] = fixes.get((state, name, seen[name]), name)
            # a sheet shared by two territories ('CHANDIGARH-DELHI', 2002) has one district each
            parts = [x.strip() for x in state.split("-")]
            for i in range(u + 1, end):
                label = " ".join(v for v in cells.iloc[i, :first] if v)
                occ = occupation(label)
                if occ is None:
                    continue
                for c, name in districts.items():
                    out.append({"rbi_state": name if len(parts) > 1 and name in parts
                                else state, "rbi_district": name, "occupation": occ,
                                "accounts": number(d.iat[i, c]),
                                "amount": number(d.iat[i, c + 1]) if c + 1 < d.shape[1]
                                else np.nan})
    return pd.DataFrame(out)


def merge_labels(df: pd.DataFrame, merge: dict) -> pd.DataFrame:
    """Add the rows of the labels in `merge` ({state: {label: into}}) to the label they go
    into. Other rows are left alone."""
    df = df.copy()
    hit = pd.Series(False, index=df.index)
    for state, merges in merge.items():
        at = (df.rbi_state == state) & df.rbi_district.isin(
            set(merges) | set(merges.values()))
        df.loc[at, "rbi_district"] = df.loc[at, "rbi_district"].replace(merges)
        hit |= at
    if not hit.any():
        return df
    summed = df[hit].groupby(["rbi_state", "rbi_district", "occupation"], as_index=False) \
        .agg(accounts=("accounts", lambda x: x.sum(min_count=1)),
             amount=("amount", lambda x: x.sum(min_count=1)))
    return pd.concat([df[~hit], summed], ignore_index=True)


def read_table(data: bytes, suffix: str, cfg: dict | None = None) -> pd.DataFrame:
    """One year's Table 5.9 / 3.9 as long rows, amounts in crore. `cfg`: configs/rbi_annual.yaml
    (states, relabel, unit_override, merge, drop)."""
    cfg = cfg or {}
    sheets = read_book(data, suffix)
    year = year_of(sheets)
    unit = (cfg.get("unit_override") or {}).get(year) or unit_of(sheets)
    fixes = [f for f in cfg.get("relabel") or [] if int(f["year"]) == year]
    longs = [(d, _occupation_column(d)) for d in sheets.values()]
    longs = [(d, o) for d, o in longs if o is not None]
    df = pd.concat([parse_long(d, o) for d, o in longs]) if longs \
        else parse_wide(sheets, fixes)
    df = df[df.rbi_district.notna() & (df.rbi_district != "")]
    df["rbi_state"] = df.rbi_state.replace(cfg.get("states") or {})
    df = merge_labels(df, cfg.get("merge") or {})
    for d in cfg.get("drop") or []:
        if int(d["year"]) == year:
            gone = (df.rbi_state == d["state"].upper()) & df.rbi_district.isin(
                [x.upper() for x in d["districts"]])
            df = df[~gone]
    df["amount_cr"] = to_crore(df.pop("amount"), unit)
    df["quarter_end"] = pd.Timestamp(year=year, month=3, day=31)
    return df[COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------- files

def find_tables(folder: Path) -> list[tuple[str, str, bytes]]:
    """(source, suffix, bytes) of the district-occupation table in every annual volume zip
    and in loose table folders (`2026_tables/`)."""
    out = []
    for z in sorted(folder.glob("bsr_vol*.zip")):
        with zipfile.ZipFile(z) as zf:
            hits = [n for n in zf.namelist() if not n.endswith("/")
                    and Path(n).suffix.lower() in {".xls", ".xlsx"}
                    and TABLE_FILE.match(Path(n).name)]
            if len(hits) != 1:
                raise ValueError(f"{z.name}: expected one Table 5.9 / 3.9, found {hits}")
            out.append((f"{z.name}:{hits[0]}", Path(hits[0]).suffix.lower(), zf.read(hits[0])))
    for f in sorted(folder.glob("*/*.xls*")):
        name = f.name.replace("Table_No_", "Table No ")
        if TABLE_FILE.match(name) and "district" in name.lower():
            out.append((str(f.relative_to(folder)), f.suffix.lower(), f.read_bytes()))
    return out


KEY = ["quarter_end", "rbi_state", "rbi_district"]
PARTS = [o for o in OCCUPATIONS.values() if o != "total"]


def reconcile(df: pd.DataFrame, tolerance: float = 0.01) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Check each district-year's occupations against the total the table gives.

    - One blank occupation, when the others fall short of the total: the blank is the
      difference (West Bengal 2010 leaves Finance blank).
    - Other blanks, when the rest add up to the total, are nil (0).
    - Still more than `tolerance` of the total apart (a typo in one cell): whichever of the
      total and the sum of occupations is further from the district's total in the year
      before and after is taken to be wrong. A wrong total (Ahmedabad 2010: 832 crore) is
      replaced by the sum; a wrong occupation (Rajkot 2007 industry) leaves the split missing
      and keeps the total.

    Returns the table and one review row per district-year that was changed.
    """
    w = df.pivot_table(index=KEY, columns="occupation", values="amount_cr",
                       aggfunc="first", dropna=False).reindex(columns=PARTS + ["total"])
    w = w[w.notna().any(axis=1)]
    tol = tolerance * w.total.abs() + 0.01
    gap = w.total - w[PARTS].sum(axis=1, min_count=1).fillna(0)
    blank = w[PARTS].isna()
    review = []
    one = (blank.sum(axis=1) == 1) & (gap > 0.01)
    for k in w.index[one]:
        col = blank.loc[k][blank.loc[k]].index[0]
        w.loc[k, col] = gap[k]
        review.append({**dict(zip(KEY, k, strict=True)), "action": f"{col} = total - others",
                       "amount_cr": gap[k]})
    nil = w[PARTS].isna().any(axis=1) & ((w.total - w[PARTS].sum(axis=1)).abs() <= tol)
    w.loc[nil, PARTS] = w.loc[nil, PARTS].fillna(0.0)
    parts = w[PARTS].sum(axis=1, min_count=1)
    gap = w.total - parts
    bad = w.total.notna() & ~(gap.abs() <= tol)
    # which of the two is the typo: the one further (in log) from the district's total in
    # the years before and after
    tot = w.total.reset_index().sort_values(KEY)
    g = tot.groupby(["rbi_state", "rbi_district"]).total
    ref = np.exp((np.log(g.shift()) + np.log(g.shift(-1))) / 2)
    ref.index = pd.MultiIndex.from_frame(tot[KEY])
    ref = ref.reindex(w.index)
    use_parts = bad & ref.notna() & (np.log(parts / ref).abs() < np.log(w.total / ref).abs())
    for k in w.index[bad]:
        action = ("total does not match its occupations and is off the trend: replaced by "
                  "their sum") if use_parts[k] else \
            "occupations do not add up to the total: split left missing"
        review.append({**dict(zip(KEY, k, strict=True)), "action": action,
                       "amount_cr": float(gap[k])})
    w.loc[use_parts, "total"] = parts[use_parts]
    w.loc[bad & ~use_parts, PARTS] = np.nan
    total = w.total.where(w.total.notna(), w[PARTS].sum(axis=1, min_count=1))
    w["total"] = total
    out = w.reset_index().melt(id_vars=KEY, var_name="occupation", value_name="amount_cr")
    acc = df[KEY + ["occupation", "accounts"]].drop_duplicates(KEY + ["occupation"])
    out = out.merge(acc, on=KEY + ["occupation"], how="left")
    return out[COLUMNS].sort_values(KEY + ["occupation"]).reset_index(drop=True), \
        pd.DataFrame(review, columns=KEY + ["action", "amount_cr"])


def repeated_columns(df: pd.DataFrame) -> pd.DataFrame:
    """District-years whose occupation figures repeat another district's exactly (a copied
    column in the table)."""
    w = df[df.occupation != "total"].pivot_table(index=KEY, columns="occupation",
                                                  values="amount_cr", aggfunc="first")
    w = w[(w.fillna(0) > 0).sum(axis=1) >= 5].round(4)
    dup = w.reset_index().duplicated(["quarter_end", *w.columns], keep=False)
    return w.reset_index()[dup.to_numpy()][KEY]


def yearly_jumps(df: pd.DataFrame, factor: float) -> pd.Series:
    """All-India total by year, where it moves by more than `factor` from the year before."""
    t = df[df.occupation == "total"].groupby("quarter_end").amount_cr.sum()
    r = t / t.shift()
    return t[(r > factor) | (r < 1 / factor)]


def read_folder(folder: Path, cfg: dict | None = None) -> pd.DataFrame:
    frames = []
    for source, suffix, data in find_tables(folder):
        df = read_table(data, suffix, cfg)
        log.info("%s: March %d, %d districts", source, df.quarter_end.iloc[0].year,
                 df[["rbi_state", "rbi_district"]].drop_duplicates().shape[0])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    dup = df.duplicated(["quarter_end", "rbi_state", "rbi_district", "occupation"], keep=False)
    if dup.any():
        # a district listed twice under one state (the 2002 to 2010 sheets repeat a district
        # on a continuation page): the rows must agree
        g = df[dup].groupby(["quarter_end", "rbi_state", "rbi_district", "occupation"])
        if (g.amount_cr.nunique() > 1).any():
            raise ValueError("a district appears twice in one year with different amounts")
        df = df.drop_duplicates(["quarter_end", "rbi_state", "rbi_district", "occupation"])
    return df


def interim_path() -> Path:
    return config.path("interim") / INTERIM_FILE


def build(folder: Path | None = None, out: Path | None = None) -> Path:
    folder = folder or config.path("raw") / "rbi" / "annual_bsr"
    out = out or interim_path()
    cfg = config.load("rbi_annual")
    df = read_folder(folder, cfg)
    rep = repeated_columns(df)
    if not rep.empty:
        raise ValueError(f"{len(rep)} district columns repeat another district's figures; list "
                         f"them under `drop` in configs/rbi_annual.yaml: {rep.to_dict('records')}")
    df, review = reconcile(df, cfg.get("total_tolerance", 0.01))
    jumps = yearly_jumps(df, cfg.get("max_yearly_factor", 1.6))
    if not jumps.empty:
        raise ValueError(f"all-India credit jumps in {list(jumps.index)}: check the unit; "
                         "see unit_override in configs/rbi_annual.yaml")
    review_path = config.path("interim") / REVIEW_FILE
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(review_path, index=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    log.info("annual occupation: %d rows, %d years, %d district-years reconciled (%s); "
             "written to %s", len(df), df.quarter_end.nunique(), len(review), review_path, out)
    return out


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(build())


if __name__ == "__main__":
    main()
