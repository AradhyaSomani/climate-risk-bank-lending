"""Phase 0 B location-basis test on the March 2007 annual BSR volume.

March 2007 is before every main event (the first, the Kosi flood, is August
2008), so nothing here looks at an outcome after an event. The volume has
district credit on two bases:

- Table 2.4: deposits and credit by district, credit by place of sanction
  (the branch that books the loan), in rupees lakh;
- Table 5.9: credit by district and occupation, by place of utilisation
  (where the money is used), in rupees thousand.

The script prints the markdown tables for docs/00_location_basis.md and saves
the district table to data/interim/rbi_location_basis_2007.csv.

    python scripts/rbi_location_basis.py
"""

import argparse
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POP_GROUPS = {"rural", "semi-urban", "urban", "metropolitan"}
# State names as the 2007 volume spells them, upper case, plus the spellings the
# two tables disagree on
STATES = {
    "ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM", "BIHAR", "CHHATTISGARH", "GOA", "GUJARAT",
    "HARYANA", "HIMACHAL PRADESH", "JAMMU & KASHMIR", "JHARKHAND", "KARNATAKA", "KERALA",
    "MADHYA PRADESH", "MAHARASHTRA", "MANIPUR", "MEGHALAYA", "MIZORAM", "NAGALAND", "ORISSA",
    "PUNJAB", "RAJASTHAN", "SIKKIM", "TAMIL NADU", "TRIPURA", "UTTAR PRADESH", "UTTARANCHAL",
    "WEST BENGAL", "ANDAMAN & NICOBAR", "CHANDIGARH", "DADRA & NAGAR HAVELI", "DAMAN & DIU",
    "DELHI", "LAKSHADWEEP", "PONDICHERRY",
}
STATE_ALIASES = {"CHATTISGARH": "CHHATTISGARH", "A&N ISLANDS": "ANDAMAN & NICOBAR",
                 "J&K": "JAMMU & KASHMIR", "ARUNACHAL": "ARUNACHAL PRADESH",
                 "UTTARANCHAL": "UTTARAKHAND", "TAMILNADU": "TAMIL NADU"}
# Table 2.4 spelling -> Table 5.9 spelling, as name keys (letters only)
DISTRICT_ALIASES = {"AHMADABAD": "AHMEDABAD", "AHMADNAGAR": "AHMEDNAGAR",
                    "SUNDARGARH": "SUNDERGARH", "JHUNJHUNU": "JHUNJHUNUN",
                    "SAHIBZADAAJITSINGNAGA": "SAHIBZADAAJITSINGH",
                    "DADRANAGARHAVEL": "DADRANAGARHAVELI"}
# A district whose two bases differ by more than this factor is flagged
BASIS_GAP = 1.25


def number(v) -> float | None:
    """Parse '2139,81,25' (Indian digit grouping) or a plain number."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def label(v) -> str:
    return "" if pd.isna(v) else re.sub(r"\s+", " ", str(v)).strip()


def key(s: str) -> str:
    return re.sub(r"[^A-Z]", "", s.upper())


def sanction_table(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Table 2.4: one sheet per state; a district row is followed by its population groups."""
    rows = []
    for sheet, d in sheets.items():
        state = STATE_ALIASES.get(sheet.strip().upper(), sheet.strip().upper())
        labels = [label(v) for v in d.iloc[:, 0]]
        for i, name in enumerate(labels):
            if not name or name.lower() in POP_GROUPS:
                continue
            nxt = next((x for x in labels[i + 1:] if x), "")
            values = [x for x in (number(c) for c in d.iloc[i, 1:9]) if x is not None]
            if nxt.lower() not in POP_GROUPS or len(values) < 4:
                continue
            upper = re.sub(r"^STATE\s*:\s*", "", name.upper())
            # A state's own row also precedes population groups; single-district
            # territories (Delhi, Chandigarh) have only that row, so keep it when no
            # district row follows in the sheet
            if upper in STATES and any(x and x.lower() not in POP_GROUPS
                                       for x in labels[i + 1:]):
                continue
            rows.append(dict(state=state, district=name.title() if upper in STATES else name,
                             deposits_cr=values[2] * 0.01, credit_sanction_cr=values[3] * 0.01))
    return pd.DataFrame(rows)


def utilisation_table(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Table 5.9: one sheet per state, district names across a header row, a
    TOTAL BANK CREDIT row below with accounts and amount per district."""
    rows = []
    for sheet, d in sheets.items():
        state = STATE_ALIASES.get(sheet.strip().upper(), sheet.strip().upper())
        first = [label(v).upper() for v in d.iloc[:, 0]]
        units = [i for i in range(len(d))
                 if any(isinstance(c, str) and "NO. OF" in c.upper() for c in d.iloc[i])]
        for t in (i for i, x in enumerate(first) if x.startswith("TOTAL BANK CREDIT")):
            header = max(i for i in units if i < t) - 1
            for c in range(2, d.shape[1] - 1, 2):
                name = label(d.iat[header, c])
                amount = number(d.iat[t, c + 1])
                if name and amount is not None:
                    rows.append(dict(state=state, district=name,
                                     credit_utilisation_cr=amount * 1e-4))
    return pd.DataFrame(rows)


def read_volume(zip_path: Path) -> tuple[dict, dict]:
    with zipfile.ZipFile(zip_path) as z:
        names = {Path(n).name.lower(): n for n in z.namelist()}
        out = []
        for want in ("table204.xls", "table509.xls"):
            with z.open(names[want]) as f:
                out.append(pd.read_excel(f, sheet_name=None, header=None))
    return out[0], out[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--volume", default=str(ROOT / "data/raw/rbi/annual_bsr/bsr_vol36.zip"))
    ap.add_argument("--out", default=str(ROOT / "data/interim/rbi_location_basis_2007.csv"))
    args = ap.parse_args()

    t24, t59 = read_volume(Path(args.volume))
    san, util = sanction_table(t24), utilisation_table(t59)
    for df in (san, util):
        df["k_state"], df["k_district"] = df.state.map(key), df.district.map(key)
    san["k_district"] = san.k_district.replace(DISTRICT_ALIASES)
    m = san.merge(util.rename(columns={"state": "state_u", "district": "district_u"}),
                  on=["k_state", "k_district"], how="outer", indicator=True)
    both = m[m._merge == "both"].drop(columns=["_merge", "k_state", "k_district", "state_u",
                                               "district_u"]).copy()
    both["cd_ratio"] = both.credit_sanction_cr / both.deposits_cr
    both["utilisation_over_sanction"] = both.credit_utilisation_cr / both.credit_sanction_cr
    both["basis_flag"] = ((both.utilisation_over_sanction > BASIS_GAP)
                          | (both.utilisation_over_sanction < 1 / BASIS_GAP))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    both.to_csv(args.out, index=False)

    only_s = m[m._merge == "left_only"]
    only_u = m[m._merge == "right_only"]
    print("## Numbers for docs/00_location_basis.md (March 2007)\n")
    print(f"- Districts: {len(san)} in Table 2.4, {len(util)} in Table 5.9, {len(both)} matched "
          f"by name. Unmatched in 2.4: {sorted(only_s.district)}; in 5.9: "
          f"{sorted(only_u.district_u)}")
    print(f"- Totals over matched districts (₹ crore): deposits {both.deposits_cr.sum():,.0f}, "
          f"credit by sanction {both.credit_sanction_cr.sum():,.0f}, by utilisation "
          f"{both.credit_utilisation_cr.sum():,.0f}")
    corr = np.corrcoef(np.log(both.credit_sanction_cr), np.log(both.credit_utilisation_cr))[0, 1]
    print(f"- Correlation of log credit on the two bases: {corr:.3f}")
    print(f"- Districts whose bases differ by more than a factor {BASIS_GAP}: "
          f"{int(both.basis_flag.sum())} of {len(both)}")
    top10 = both.nlargest(10, "credit_sanction_cr").credit_sanction_cr.sum()
    print(f"- Share of credit by sanction in the 10 largest districts: "
          f"{top10 / both.credit_sanction_cr.sum():.1%}")
    q = both[["cd_ratio", "utilisation_over_sanction"]].quantile([.05, .25, .5, .75, .95])
    print("\n### Distribution\n")
    print(q.round(2).rename(index=lambda p: f"{p:.0%}").to_markdown())
    cols = ["state", "district", "deposits_cr", "credit_sanction_cr", "credit_utilisation_cr",
            "cd_ratio", "utilisation_over_sanction"]
    for title, frame in [
        ("Largest districts by credit (sanction)", both.nlargest(10, "credit_sanction_cr")),
        ("Highest credit-deposit ratio", both.nlargest(10, "cd_ratio")),
        ("Lowest credit-deposit ratio", both.nsmallest(10, "cd_ratio")),
        ("Most credit used beyond what is booked (utilisation / sanction)",
         both.nlargest(10, "utilisation_over_sanction")),
        ("Most credit booked beyond what is used", both.nsmallest(10, "utilisation_over_sanction")),
    ]:
        print(f"\n### {title}\n")
        print(frame[cols].round(2).to_markdown(index=False, floatfmt=",.2f"))


if __name__ == "__main__":
    main()
