"""Tests for the supply-vs-demand / dental-desert model (ledger 4.2)."""

from __future__ import annotations

import pytest
from desert import (
    DemandPoint,
    SupplyPoint,
    compute_access,
    format_summary,
    haversine_km,
    summarise,
)

# Roughly 1 km apart at this latitude.
LAT, LON = 51.5, -0.1
KM_IN_DEGREES_LAT = 1 / 111.0


def lsoa(code, km_north=0.0, population=1000):
    return DemandPoint(code, LAT + km_north * KM_IN_DEGREES_LAT, LON, population)


def practice(org, km_north=0.0, uda=10_000.0):
    return SupplyPoint(org, LAT + km_north * KM_IN_DEGREES_LAT, LON, uda)


# -- distance --------------------------------------------------------------


def test_haversine_known_distance():
    """London to Paris is ~344 km."""
    assert haversine_km(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(344, abs=5)


def test_haversine_zero_for_same_point():
    assert haversine_km(51.5, -0.1, 51.5, -0.1) == pytest.approx(0, abs=1e-6)


# -- 2SFCA behaviour -------------------------------------------------------


def test_single_practice_serving_single_lsoa():
    """10,000 UDAs, 1,000 people ⇒ 10 UDAs per person ⇒ 10,000 per 1,000."""
    results = compute_access([lsoa("E01")], [practice("V1", uda=10_000)], radius_km=10)
    assert results[0].uda_per_1000 == pytest.approx(10_000, rel=1e-3)
    assert results[0].practices_within_radius == 1
    assert results[0].nearest_practice_km == pytest.approx(0, abs=0.01)


def test_capacity_is_shared_between_lsoas_in_reach():
    """A practice serving twice the population supplies half as much each — this
    is what stops a large urban practice looking generous."""
    results = compute_access(
        [lsoa("E01"), lsoa("E02", km_north=1)], [practice("V1", uda=10_000)], radius_km=10
    )
    assert all(r.uda_per_1000 == pytest.approx(5_000, rel=1e-3) for r in results)


def test_two_practices_in_reach_accumulate():
    results = compute_access(
        [lsoa("E01")],
        [practice("V1", uda=10_000), practice("V2", km_north=1, uda=10_000)],
        radius_km=10,
    )
    assert results[0].uda_per_1000 == pytest.approx(20_000, rel=1e-3)
    assert results[0].practices_within_radius == 2


def test_practice_beyond_the_radius_contributes_nothing():
    results = compute_access([lsoa("E01")], [practice("V1", km_north=50)], radius_km=10)
    assert results[0].uda_per_1000 == 0.0
    assert results[0].practices_within_radius == 0
    assert results[0].has_no_practice_in_reach
    assert results[0].nearest_practice_km == pytest.approx(50, rel=0.02)


def test_lsoa_without_a_practice_inside_it_is_not_automatically_a_desert():
    """The whole reason for a catchment model: 80.6% of English LSOAs contain no
    practice, but most are well within reach of one."""
    results = compute_access([lsoa("E01")], [practice("V1", km_north=3)], radius_km=10)
    assert not results[0].has_no_practice_in_reach
    assert results[0].uda_per_1000 > 0


def test_no_supply_at_all_yields_infinite_distance_not_a_crash():
    results = compute_access([lsoa("E01")], [], radius_km=10)
    assert results[0].practices_within_radius == 0
    assert results[0].uda_per_1000 == 0.0
    assert results[0].nearest_practice_km == float("inf")


def test_no_demand_yields_no_rows():
    assert compute_access([], [practice("V1")], radius_km=10) == []


def test_practice_with_nobody_in_reach_contributes_zero_not_infinity():
    """Dividing UDAs by a zero population must not produce an infinite ratio
    that then floods every other LSOA."""
    results = compute_access(
        [lsoa("E01")], [practice("V1"), practice("V2", km_north=500)], radius_km=10
    )
    assert results[0].uda_per_1000 == pytest.approx(10_000, rel=1e-3)


def test_zero_population_lsoa_does_not_break_the_ratio():
    results = compute_access([lsoa("E01", population=0)], [practice("V1")], radius_km=10)
    assert results[0].uda_per_1000 == 0.0


def test_chunking_produces_the_same_answer_as_one_pass():
    """Results must not depend on the batch boundary."""
    import desert

    demand = [lsoa(f"E{i:05d}", km_north=i * 0.1) for i in range(50)]
    supply = [practice("V1", km_north=2.5, uda=50_000)]

    original = desert.CHUNK
    try:
        desert.CHUNK = 1000
        one_pass = compute_access(demand, supply, radius_km=10)
        desert.CHUNK = 7
        chunked = compute_access(demand, supply, radius_km=10)
    finally:
        desert.CHUNK = original

    assert [r.lsoa_code for r in one_pass] == [r.lsoa_code for r in chunked]
    assert [r.uda_per_1000 for r in one_pass] == [r.uda_per_1000 for r in chunked]


# -- reporting -------------------------------------------------------------


def test_summarise_is_population_weighted():
    """A tiny remote LSOA must not drag the headline as hard as a city."""
    results = compute_access(
        [lsoa("E01", population=100_000), lsoa("E02", km_north=100, population=100)],
        [practice("V1", uda=100_000)],
        radius_km=10,
    )
    stats = summarise(results, 10)

    assert stats["lsoas"] == 2
    assert stats["population"] == 100_100
    assert stats["lsoas_with_no_practice_in_reach"] == 1
    assert stats["population_with_no_practice_in_reach"] == 100
    # The well-served LSOA holds ~99.9% of people, so the weighted mean sits
    # near its value, not halfway to zero.
    assert stats["mean_uda_per_1000_pop_weighted"] > 900


def test_summarise_reports_distance_spread():
    results = compute_access(
        [lsoa("E01"), lsoa("E02", km_north=20)], [practice("V1")], radius_km=10
    )
    stats = summarise(results, 10)
    assert stats["median_nearest_km"] == pytest.approx(10, abs=0.5)
    assert stats["max_nearest_km"] == pytest.approx(20, rel=0.02)


def test_summarise_handles_empty():
    assert summarise([])["lsoas"] == 0
    assert format_summary(summarise([])) == "No LSOAs to report."


def test_format_summary_mentions_the_radius():
    results = compute_access([lsoa("E01")], [practice("V1")], radius_km=10)
    assert "10 km catchment" in format_summary(summarise(results, 10))
