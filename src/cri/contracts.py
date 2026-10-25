"""Table contracts between the two sides of the project (docs/contracts/C*.yaml).

Each contract lists one or more tables with column types, ranges, allowed values, a primary
key and table-level checks. `validate_frame` returns a list of human-readable problems; an
empty list means the table satisfies the contract. It never fixes anything.

A table check is either a dict with a `kind` (sum_to_one, ordered, ...) or the name of a rule
in `TABLE_CHECKS`. Checks that only make sense on the complete table (the 640-district row
count) are skipped when `full=False`, which is how the toy samples are validated.

    python -m cri.contracts --samples              # validate every toy sample
    python -m cri.contracts C3 flood_extent_district_event path/to/file.parquet
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = REPO_ROOT / "docs" / "contracts"

DTYPES = {"int", "float", "str", "bool", "date", "datetime", "geometry"}


@dataclass
class TableSpec:
    contract: str
    name: str
    columns: dict
    primary_key: list[str]
    checks: list[dict] = field(default_factory=list)
    file: str | None = None
    sample: str | None = None
    version: str | None = None


def load_contracts(contract_dir: Path = CONTRACT_DIR) -> dict[str, dict[str, TableSpec]]:
    """Return {contract_id: {table_name: TableSpec}}."""
    out: dict[str, dict[str, TableSpec]] = {}
    for path in sorted(contract_dir.glob("C*.yaml")):
        doc = yaml.safe_load(path.read_text())
        cid = doc["contract"]
        out[cid] = {}
        for tname, t in doc["tables"].items():
            for col, spec in t["columns"].items():
                if spec["dtype"] not in DTYPES:
                    raise ValueError(f"{cid}.{tname}.{col}: unknown dtype {spec['dtype']}")
            out[cid][tname] = TableSpec(
                contract=cid,
                name=tname,
                columns=t["columns"],
                primary_key=t["primary_key"],
                checks=t.get("checks", []),
                file=t.get("file"),
                sample=t.get("sample"),
                version=doc.get("version"),
            )
    return out


def get_table(contract: str, table: str) -> TableSpec:
    return load_contracts()[contract][table]


def read_table(path: str | Path, spec: TableSpec) -> pd.DataFrame:
    """Read a parquet or CSV file, coercing CSV columns to the contract's types."""
    path = Path(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    df = pd.read_csv(path, keep_default_na=True)
    for col, cs in spec.columns.items():
        if col not in df:
            continue
        if cs["dtype"] == "date":
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif cs["dtype"] == "datetime":
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
        elif cs["dtype"] == "bool":
            df[col] = df[col].map(
                lambda v: v if isinstance(v, bool) else str(v).strip().lower() in {"true", "1"}
            )
        elif cs["dtype"] == "int":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def _type_ok(series: pd.Series, dtype: str) -> bool:
    s = series.dropna()
    if s.empty:
        return True
    if dtype == "int":
        if pd.api.types.is_integer_dtype(s):
            return True
        return pd.api.types.is_float_dtype(s) and bool(np.all(np.mod(s, 1) == 0))
    if dtype == "float":
        return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
    if dtype == "bool":
        return pd.api.types.is_bool_dtype(s) or s.map(lambda v: isinstance(v, bool)).all()
    if dtype in {"date", "datetime"}:
        return pd.api.types.is_datetime64_any_dtype(s)
    if dtype == "str":
        return s.map(lambda v: isinstance(v, str)).all()
    if dtype == "geometry":
        # GeoSeries, shapely objects, WKB bytes or WKT strings are all accepted here;
        # geometry validity is tested separately with shapely in tests/data.
        return True
    return False


def validate_frame(df: pd.DataFrame, spec: TableSpec, full: bool = True) -> list[str]:
    errs: list[str] = []
    where = f"{spec.contract}.{spec.name}"

    missing = [c for c in spec.columns if c not in df.columns]
    if missing:
        errs.append(f"{where}: missing columns {missing}")
    extra = [c for c in df.columns if c not in spec.columns]
    if extra:
        errs.append(f"{where}: unexpected columns {extra}")

    for col, cs in spec.columns.items():
        if col not in df.columns:
            continue
        s = df[col]
        if not cs.get("nullable", False) and s.isna().any():
            errs.append(f"{where}.{col}: {int(s.isna().sum())} null values")
        if not _type_ok(s, cs["dtype"]):
            errs.append(f"{where}.{col}: expected {cs['dtype']}, got {s.dtype}")
            continue
        nn = s.dropna()
        if "allowed" in cs:
            bad = sorted(set(nn) - set(cs["allowed"]))
            if bad:
                errs.append(f"{where}.{col}: values not allowed {bad[:5]}")
        if "min" in cs and len(nn):
            low = nn <= cs["min"] if cs.get("exclusive_min") else nn < cs["min"]
            if low.any():
                errs.append(f"{where}.{col}: {int(low.sum())} values below {cs['min']}")
        if "max" in cs and len(nn) and (nn > cs["max"]).any():
            errs.append(f"{where}.{col}: {int((nn > cs['max']).sum())} values above {cs['max']}")
        if "pattern" in cs and len(nn):
            nomatch = ~nn.astype(str).str.match(cs["pattern"])
            if nomatch.any():
                errs.append(f"{where}.{col}: {int(nomatch.sum())} values do not match "
                            f"{cs['pattern']}")
        if cs.get("quarter_end") and len(nn):
            d = pd.to_datetime(nn)
            not_qe = ~(d.dt.is_quarter_end & (d.dt.normalize() == d))
            if not_qe.any():
                errs.append(f"{where}.{col}: {int(not_qe.sum())} dates are not quarter ends")

    pk = [c for c in spec.primary_key if c in df.columns]
    if len(pk) == len(spec.primary_key):
        dup = df.duplicated(subset=pk, keep=False)
        if dup.any():
            errs.append(f"{where}: {int(dup.sum())} rows share a primary key {pk}")

    if not missing:
        for chk in spec.checks:
            if isinstance(chk, str):
                if chk not in TABLE_CHECKS:
                    errs.append(f"{where}: unknown check {chk}")
                    continue
                errs.extend(f"{where}: {e}" for e in TABLE_CHECKS[chk](df, full))
            else:
                errs.extend(_run_check(df, chk, where))
    return errs


# Named table checks (B's contracts C1, C2, C5) ------------------------------

WEIGHT_TOL = 1e-6


def _row_count_640_if_full(df, full):
    if full and len(df) != 640:
        return [f"district_master has {len(df)} rows, expected 640 Census 2011 districts"]
    return []


def _weights_sum_to_one(df, full):
    sums = df.groupby(["rbi_name", "rbi_state", "valid_from"])["weight"].sum()
    bad = sums[(sums - 1).abs() > WEIGHT_TOL]
    if len(bad):
        return [f"crosswalk weights do not sum to 1 for {len(bad)} source rows, e.g. "
                f"{bad.index[0]} sums to {bad.iloc[0]:.6f}"]
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
        if bad.any():
            return [f"{int(bad.sum())} rows where {point} is outside [{lo}, {hi}]"]
        return []

    return check


def _window_ordered(df, full):
    bad = df["window_start"] > df["window_end"]
    return [f"{int(bad.sum())} rows with window_start after window_end"] if bad.any() else []


def _var_shares_sum_to_one(df, full):
    cols = ["var_share_effect", "var_share_hazard", "var_share_exposure", "var_share_generator"]
    shares = df[cols]
    present = shares.notna().all(axis=1)
    bad = present & ((shares.sum(axis=1) - 1).abs() > 0.01)
    if bad.any():
        return [f"{int(bad.sum())} rows where the variance shares do not sum to 1"]
    return []


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


def _run_check(df: pd.DataFrame, chk: dict, where: str) -> list[str]:
    kind = chk["kind"]
    if kind == "sum_to_one":
        sums = df.groupby(chk["by"], dropna=False)[chk["column"]].sum()
        bad = (sums - 1).abs() > chk.get("tol", 1e-6)
        what = f"groups where {chk['column']} does not sum to 1"
    elif kind == "sum_to_one_row":
        sub = df[chk["columns"]]
        tot = sub[sub.notna().all(axis=1)].sum(axis=1)
        bad = (tot - 1).abs() > chk.get("tol", 0.01)
        what = f"rows where {chk['columns']} do not sum to 1"
    elif kind == "ordered":
        cols = chk["columns"]
        bad = pd.Series(False, index=df.index)
        for a, b in zip(cols, cols[1:], strict=False):
            bad |= df[a] > df[b]
        what = f"rows break order {cols}"
    elif kind == "implies":
        bad = df[chk["if"]].astype(bool) & ~df[chk["then"]].astype(bool)
        what = f"rows with {chk['if']} but not {chk['then']}"
    elif kind == "not_both":
        a, b = chk["columns"]
        bad = df[a].astype(bool) & df[b].astype(bool)
        what = f"rows with both {a} and {b}"
    else:
        return [f"{where}: unknown check kind {kind}"]
    n = int(bad.sum())
    return [f"{where}: {n} {what}"] if n else []


def validate_file(contract: str, table: str, path: str | Path) -> list[str]:
    spec = get_table(contract, table)
    return validate_frame(read_table(path, spec), spec)


def validate_samples() -> dict[str, list[str]]:
    results = {}
    for cid, tables in load_contracts().items():
        for tname, spec in tables.items():
            key = f"{cid}.{tname}"
            if not spec.sample:
                results[key] = ["no sample file declared"]
                continue
            results[key] = validate_frame(read_table(REPO_ROOT / spec.sample, spec), spec,
                                          full=False)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("contract", nargs="?")
    p.add_argument("table", nargs="?")
    p.add_argument("path", nargs="?")
    p.add_argument("--samples", action="store_true", help="validate every contract's toy sample")
    p.add_argument(
        "--processed", action="store_true", help="validate every processed file that exists"
    )
    a = p.parse_args(argv)

    if a.samples:
        results = validate_samples()
    elif a.processed:
        results = {}
        for cid, tables in load_contracts().items():
            for tname, spec in tables.items():
                path = REPO_ROOT / spec.file
                if path.exists():
                    results[f"{cid}.{tname}"] = validate_frame(read_table(path, spec), spec)
    elif a.contract and a.table and a.path:
        results = {f"{a.contract}.{a.table}": validate_file(a.contract, a.table, a.path)}
    else:
        p.error("give CONTRACT TABLE PATH, --samples or --processed")

    failed = 0
    for key, errs in results.items():
        status = "ok" if not errs else "FAIL"
        print(f"{status:4}  {key}")
        for e in errs:
            print(f"      {e}")
        failed += bool(errs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
