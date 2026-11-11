"""Toy RBI tables shared by the crosswalk and panel tests (Phase 1 B and C)."""

import pandas as pd

Q = pd.Timestamp


def _master():
    # Parent and Child (a Census 2011 district carved from Parent before 2011, reported by
    # RBI from the third quarter), Other (a later district, NEWDIST, is carved from it), and
    # a two-district territory that RBI reports as one label
    return pd.DataFrame({
        "district_id": [1, 2, 3, 4, 5],
        "name": ["Parent", "Child", "Other", "Delhi North", "Delhi South"],
        "state": ["Toy", "Toy", "Toy", "Capital", "Capital"],
        "population": [300, 100, 200, 600, 400],
        "split_flag": [False] * 5,
    })


CFG = {
    "states": {"TOY STATE": "Toy", "CAPITAL TERRITORY": "Capital"},
    "names": {"Toy": {"OTHR": "Other"}},
    "new_districts": {"Toy": {"NEWDIST": {"parent": "Other", "also_from": ["Parent"]}}},
    "pre_2011_children": {"Toy": {"Child": {"parent": "Parent"}}},
    "state_wide_labels": {"Capital": ["CAPITAL"]},
}
ALIASES = {"districts": {}}
QUARTERS = [Q("2005-03-31"), Q("2005-06-30"), Q("2005-09-30"), Q("2005-12-31")]


def _rbi(rows):
    """rows: (label, state, quarter, credit, offices); deposits = 2 x credit."""
    out = []
    for lab, st, q, cr, off in rows:
        for meas, amt in [("credit", cr), ("deposits", None if cr is None else 2 * cr)]:
            out.append({"quarter_end": q, "rbi_state": st, "rbi_district": lab,
                        "bank_group": "all", "measure": meas, "sector": "all",
                        "amount_cr": amt, "n_offices": off})
    return pd.DataFrame(out)


def _toy_rbi():
    rows = []
    for i, q in enumerate(QUARTERS):
        # the child is reported from the third quarter; the parent label shrinks then
        child_in = i >= 2
        rows.append(("PARENT", "TOY STATE", q, 30.0 if child_in else 40.0, 30 if child_in else 40))
        rows.append(("CHILD", "TOY STATE", q, 10.0 if child_in else None,
                     10 if child_in else None))
        rows.append(("OTHR", "TOY STATE", q, 20.0 if i < 3 else 15.0, 20 if i < 3 else 15))
        rows.append(("NEWDIST", "TOY STATE", q, None if i < 3 else 5.0, None if i < 3 else 5))
        rows.append(("CAPITAL", "CAPITAL TERRITORY", q, 100.0, 100))
    return _rbi(rows)
