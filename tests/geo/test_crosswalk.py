"""Phase 1 B: RBI district names to Census 2011 districts (contract C1)."""

import numpy as np
import pandas as pd
import pytest
from toy_rbi import ALIASES, CFG, QUARTERS, _master, _rbi, _toy_rbi

from cri.geo.crosswalk import UnresolvedNames, build_crosswalk


def test_crosswalk_resolves_and_shares():
    xw = build_crosswalk(_toy_rbi(), _master(), CFG, ALIASES)
    # every label interval sums to one
    sums = xw.groupby(["rbi_state", "rbi_name", "valid_from"]).weight.sum()
    assert np.allclose(sums, 1.0)
    parent = xw[xw.rbi_name == "PARENT"].sort_values(["valid_from", "district_id"])
    early = parent[parent.valid_from == QUARTERS[0]]
    assert set(early.district_id) == {1, 2}
    assert early.set_index("district_id").weight.to_dict() == pytest.approx({1: 0.75, 2: 0.25})
    assert (early.valid_to == QUARTERS[1]).all() and (early.match_type == "split").all()
    late = parent[parent.valid_from == QUARTERS[2]]
    assert late.district_id.tolist() == [1] and late.weight.iloc[0] == 1.0
    assert late.valid_to.isna().all()  # still valid in the last quarter
    new = xw[xw.rbi_name == "NEWDIST"].iloc[0]
    assert new.district_id == 3 and new.weight == 1.0 and new.match_type == "manual"
    cap = xw[xw.rbi_name == "CAPITAL"].set_index("district_id").weight
    assert cap.to_dict() == pytest.approx({4: 0.6, 5: 0.4})
    other = xw[xw.rbi_name == "OTHR"].iloc[0]
    assert other.match_type == "fuzzy"


def test_unresolved_name_stops_the_build(tmp_path):
    rbi = pd.concat([_toy_rbi(), _rbi([("MYSTERY", "TOY STATE", QUARTERS[0], 1.0, 3)])])
    review = tmp_path / "review.csv"
    with pytest.raises(UnresolvedNames, match="MYSTERY"):
        build_crosswalk(rbi, _master(), CFG, ALIASES, review_path=review)
    assert "MYSTERY" in pd.read_csv(review).rbi_name.tolist()


def test_unknown_parent_is_an_error():
    cfg = {**CFG, "new_districts": {"Toy": {"NEWDIST": {"parent": "Nowhere"}}}}
    with pytest.raises(ValueError, match="Nowhere"):
        build_crosswalk(_toy_rbi(), _master(), cfg, ALIASES)
