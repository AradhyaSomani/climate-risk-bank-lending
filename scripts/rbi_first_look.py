"""Phase 0 A first look at the RBI district deposit and credit downloads.

Reads every district-wise statement in data/raw/rbi/quarterly/ with
cri.ingest.rbi_bsr, then prints the numbers docs/00_rbi_audit.md asks for:
coverage, units and the all-India break check. Nothing here looks at a
district's outcomes around an event.

    python scripts/rbi_first_look.py
    python scripts/rbi_first_look.py --out docs/00_rbi_first_look.md
    python scripts/rbi_first_look.py --raw data/raw/rbi/quarterly --unit lakh \
        --states Kerala Odisha "Tamil Nadu"

--plots also draws credit and deposits per district for each test state. Those
lines run through the main events, so leave it off until docs/00_hypotheses.md
is signed.

Outputs:
    data/interim/rbi_first_look.parquet     the parsed long table (not committed)
    docs/figures/00_rbi_<state>.png         with --plots: credit and deposits per district
    printed markdown                        paste into docs/00_rbi_audit.md (--out also
                                            writes it to a file)
"""

import argparse
import contextlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cri.ingest.rbi_bsr import read_folder  # noqa: E402

# BSR-7 discontinued after Dec 2022
BREAK_QUARTERS = [pd.Timestamp("2022-12-31"), pd.Timestamp("2023-03-31")]


def coverage_table(df: pd.DataFrame) -> pd.DataFrame:
    """Districts reporting per quarter (with an amount, not blank), overall and per state."""
    d = df[df.amount_cr.notna()].drop_duplicates(["quarter_end", "rbi_state", "rbi_district"])
    total = d.groupby("quarter_end").size().rename("all_states")
    by_state = d.groupby(["quarter_end", "rbi_state"]).size().unstack(fill_value=0)
    return pd.concat([total, by_state], axis=1)


def missing_quarters(quarters: pd.Series) -> list[pd.Timestamp]:
    q = pd.PeriodIndex(sorted(quarters.unique()), freq="Q")
    full = pd.period_range(q.min(), q.max(), freq="Q")
    return [p.end_time.normalize() for p in full.difference(q)]


def growth_around_break(df: pd.DataFrame) -> pd.DataFrame:
    """Quarter-on-quarter log change of all-India totals, with the median and
    the break quarters side by side, to see whether the switch from BSR-7
    shows up as a jump."""
    tot = (df[(df.bank_group == "all") & (df.sector == "all")]
           .groupby(["measure", "quarter_end"])["amount_cr"].sum(min_count=1)
           .unstack(0).sort_index())
    g = np.log(tot).diff()
    g["is_break_window"] = g.index.isin(BREAK_QUARTERS)
    return g


def plot_state(df: pd.DataFrame, state: str, out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = df[(df.rbi_state.str.lower() == state.lower()) & (df.bank_group == "all")
           & (df.sector == "all")]
    if s.empty:
        print(f"  (no rows for {state}; check the state spelling in the files)")
        return
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharex=True)
    for ax, measure in zip(axes, ["credit", "deposits"], strict=True):
        m = s[s.measure == measure].pivot_table(index="quarter_end", columns="rbi_district",
                                                values="amount_cr")
        ax.plot(m.index, m.values, linewidth=0.9, alpha=0.8)
        ax.set_yscale("log")
        ax.set_title(f"{state}: {measure} per district (₹ crore, log scale)")
        for b in BREAK_QUARTERS[:1]:
            ax.axvline(b, color="grey", linestyle="--", linewidth=0.8)
    fig.text(0.01, 0.01, "Dashed line: last BSR-7 quarter (Dec 2022). One line per district.",
             fontsize=8)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"  saved {out.relative_to(ROOT)}")


class Tee:
    """Write to several streams at once (the screen and the --out file)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text: str) -> None:
        for s in self.streams:
            s.write(text)

    def flush(self) -> None:
        for s in self.streams:
            s.flush()


def report(df: pd.DataFrame, test_states: list[str], plots: bool = False) -> None:
    q = df["quarter_end"]
    print("## Numbers for docs/00_rbi_audit.md\n")
    print(f"- Files read: {df.source_file.nunique()}; rows: {len(df):,}")
    print(f"- First quarter: {q.min():%Y-%m-%d}; last quarter: {q.max():%Y-%m-%d}; "
          f"quarters present: {q.nunique()}")
    gaps = missing_quarters(q)
    print(f"- Missing quarters inside that span: {len(gaps)} {[f'{g:%Y-%m}' for g in gaps][:12]}")
    print(f"- Units seen in the files: {sorted(df.unit.unique())}")
    print(f"- Bank groups: {sorted(df.bank_group.unique())}; sectors: {sorted(df.sector.unique())}")
    print(f"- Amounts missing (blank or '-'): {df.amount_cr.isna().mean():.1%} of rows")

    cov = coverage_table(df)
    states = {s.lower() for s in test_states}
    test = [c for c in cov.columns if c == "all_states" or str(c).lower() in states]
    print("\n### Districts reporting per quarter (first 4, last 4, and the break window)\n")
    rows = set(cov.index[:4]) | set(cov.index[-4:]) | (set(BREAK_QUARTERS) & set(cov.index))
    sel = cov.loc[sorted(rows), test]
    print(sel.rename(index=lambda d: f"{d:%Y-%m-%d}").to_markdown())

    print("\n### All-India quarter-on-quarter log change (break check)\n")
    g = growth_around_break(df)
    med = g.drop(columns="is_break_window").abs().median().round(4).to_dict()
    print(f"Median absolute change: {med}\n")
    after = [b + pd.offsets.QuarterEnd(1) for b in BREAK_QUARTERS]
    print(g[g.is_break_window | g.index.isin(after)].round(4)
          .rename(index=lambda d: f"{d:%Y-%m-%d}").to_markdown())

    if not plots:
        return
    print("\n### Plots\n")
    for s in test_states:
        plot_state(df, s, ROOT / "docs" / "figures" / f"00_rbi_{s.lower().replace(' ', '_')}.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw" / "rbi" / "quarterly"))
    ap.add_argument("--unit", default=None,
                    help="Force the unit if files do not state it (lakh or crore)")
    ap.add_argument("--states", nargs="+", default=["Kerala", "Odisha", "Tamil Nadu"])
    ap.add_argument("--out", help="also write the printed markdown to this file")
    ap.add_argument("--plots", action="store_true",
                    help="plot each test state's districts (only after the pre-registration "
                         "is signed)")
    args = ap.parse_args()

    df = read_folder(args.raw, unit=args.unit)
    out = ROOT / "data" / "interim" / "rbi_first_look.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    if not args.out:
        report(df, args.states, args.plots)
        return
    with open(args.out, "w") as f, contextlib.redirect_stdout(Tee(sys.stdout, f)):
        report(df, args.states, args.plots)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
