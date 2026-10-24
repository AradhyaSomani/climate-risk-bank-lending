"""Check a table against its contract in docs/contracts/.

A contract is a YAML file listing each table's columns, types, allowed values,
primary key and named table-level checks. `validate_frame` returns a list of
problems (empty means the table passes); it never fixes anything.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "docs" / "contracts"
WEIGHT_TOL = 1e-6


def load_contract(code: str) -> dict:
    """Load a contract by its code, e.g. "C2"."""
    matches = sorted(CONTRACTS_DIR.glob(f"{code}_*.yaml"))
    if not matches:
        raise FileNotFoundError(f"No contract file for {code} in {CONTRACTS_DIR}")
    with open(matches[0], encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, keep_default_na=True)


def _check_dtype(s: pd.Series, dtype: str) -> pd.Series:
    """Boolean mask of non-null values that do not fit `dtype`."""
    v = s.dropna()
    if dtype == "int":
        num = pd.to_numeric(v, errors="coerce")
        bad = num.isna() | (num != num.round())
    elif dtype == "float":
        bad = pd.to_numeric(v, errors="coerce").isna()
    elif dtype == "bool":
        bad = ~v.map(lambda x: isinstance(x, bool) or str(x).lower() in {"true", "false", "0", "1"})
    elif dtype == "date":
        bad = pd.to_datetime(v, errors="coerce", format="mixed").isna()
    elif dtype == "str":
        bad = ~v.map(lambda x: isinstance(x, str) and x.strip() != "")
    elif dtype == "geometry":
        bad = ~v.map(lambda x: isinstance(x, (str, bytes)) or hasattr(x, "geom_type"))
    else:
        raise ValueError(f"Unknown dtype in contract: {dtype}")
    return bad.reindex(s.index, fill_value=False)


def _as_bool(s: pd.Series) -> pd.Series:
    return s.map(lambda x: x if isinstance(x, bool) else str(x).lower() in {"true", "1"})


def validate_frame(df: pd.DataFrame, table_spec: dict, full: bool = True) -> list[str]:
    """Return every way `df` breaks `table_spec`.

    `full=False` skips checks that only make sense on the complete table
    (such as the 640-district row count), so toy samples can pass.
    """
    problems: list[str] = []
    cols = table_spec["columns"]
    df = df.reset_index(drop=True)

    missing = [c for c in cols if c not in df.columns]
    if missing:
        problems.append(f"missing columns: {missing}")
    extra = [c for c in df.columns if c not in cols]
    if extra:
        problems.append(f"columns not in the contract: {extra}")

    for name, spec in cols.items():
        if name not in df.columns:
            continue
        s = df[name]
        if not spec.get("nullable", True) and s.isna().any():
            problems.append(f"{name}: {int(s.isna().sum())} null values, contract says not nullable")
        bad = _check_dtype(s, spec["dtype"])
        if bad.any():
            problems.append(f"{name}: {int(bad.sum())} values are not {spec['dtype']}, e.g. {s[bad].iloc[0]!r}")
            continue
        v = s.dropna()
        if spec["dtype"] in {"int", "float"}:
            num = pd.to_numeric(v)
            if "min" in spec and (num < spec["min"]).any():
                problems.append(f"{name}: {int((num < spec['min']).sum())} values below {spec['min']}")
            if "max" in spec and (num > spec["max"]).any():
                problems.append(f"{name}: {int((num > spec['max']).sum())} values above {spec['max']}")
        if "allowed" in spec:
            outside = sorted(set(v.astype(str)) - {str(a) for a in spec["allowed"]})
            if outside:
                problems.append(f"{name}: values not allowed: {outside}")
        if "pattern" in spec:
            rx = re.compile(spec["pattern"])
            nomatch = ~v.astype(str).map(lambda x: bool(rx.match(x)))
            if nomatch.any():
                problems.append(f"{name}: {int(nomatch.sum())} values do not match {spec['pattern']}")
        if spec.get("quarter_end"):
            d = pd.to_datetime(v, format="mixed")
            off = ~(d.dt.is_quarter_end & (d.dt.normalize() == d))
            if off.any():
                problems.append(f"{name}: {int(off.sum())} dates are not calendar quarter-ends, e.g. {v[off].iloc[0]}")

    key = table_spec.get("primary_key", [])
    if key and all(k in df.columns for k in key):
        dup = df.duplicated(subset=key, keep=False)
        if dup.any():
            problems.append(f"primary key {key}: {int(dup.sum())} rows share a key")

    if not missing:
        for check in table_spec.get("checks", []):
            problems.extend(TABLE_CHECKS[check](df, full))
    return problems


# Table-level checks -------------------------------------------------------

def _row_count_640_if_full(df, full):
    if full and len(df) != 640:
        return [f"district_master has {len(df)} rows, expected 640 Census 2011 districts"]
    return []


def _weights_sum_to_one(df, full):
    sums = df.groupby(["rbi_name", "rbi_state", "valid_from"])["weight"].sum()
    bad = sums[(sums - 1).abs() > WEIGHT_TOL]
    if len(bad):
        return [f"crosswalk weights do not sum to 1 for {len(bad)} source rows, e.g. {bad.index[0]} sums to {bad.iloc[0]:.6f}"]
    return []


def _valid_to_after_valid_from(df, full):
    vf = pd.to_datetime(df["valid_from"], format="mixed")
    vt = pd.to_datetime(df["valid_to"], format="mixed")
    bad = vt.notna() & (vt < vf)
    return [f"valid_to before valid_from in {int(bad.sum())} rows"] if bad.any() else []


def _deposits_sector_all(df, full):
    bad = (df["measure"] == "deposits") & (df["sector"] != "all")
    return [f"{int(bad.sum())} deposit rows have a sector other than 'all'"] if bad.any() else []


def _interval_contains(point):
    lo, hi = ("ci_low", "ci_high") if point == "estimate" else ("lower", "upper")

    def check(df, full):
        bad = ~((df[lo] <= df[point]) & (df[point] <= df[hi]))
        return [f"{int(bad.sum())} rows where {point} is outside [{lo}, {hi}]"] if bad.any() else []

    return check


def _window_ordered(df, full):
    bad = df["window_start"] > df["window_end"]
    return [f"{int(bad.sum())} rows with window_start after window_end"] if bad.any() else []


def _var_shares_sum_to_one(df, full):
    cols = ["var_share_effect", "var_share_hazard", "var_share_exposure", "var_share_generator"]
    shares = df[cols]
    present = shares.notna().all(axis=1)
    bad = present & ((shares.sum(axis=1) - 1).abs() > 0.01)
    return [f"{int(bad.sum())} rows where the variance shares do not sum to 1"] if bad.any() else []


TABLE_CHECKS = {
    "row_count_640_if_full": _row_count_640_if_full,
    "weights_sum_to_one": _weights_sum_to_one,
    "valid_to_after_valid_from": _valid_to_after_valid_from,
    "deposits_sector_all": _deposits_sector_all,
    "interval_contains_estimate": _interval_contains("estimate"),
    "interval_contains_median": _interval_contains("median"),
    "window_ordered": _window_ordered,
    "var_shares_sum_to_one": _var_shares_sum_to_one,
}


def validate_file(code: str, table: str, path: str | Path | None = None) -> list[str]:
    """Validate a file against a contract table. With no path, checks the toy sample."""
    spec = load_contract(code)["tables"][table]
    is_sample = path is None
    df = read_table(REPO_ROOT / spec["sample"] if is_sample else path)
    return validate_frame(df, spec, full=not is_sample)
