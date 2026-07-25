"""Supply-versus-demand and the dental-desert model (ledger step 4.2, gate DG3).

This is the genuinely unoccupied ground the viability analysis identified. Anyone
can list practices. Almost nobody joins *delivered activity* to *population* and
says where provision is actually thin.

Why a catchment model rather than "practices in my LSOA"
--------------------------------------------------------
27,193 of England's 33,755 LSOAs — **80.6%** — contain no dental practice at all.
Counting practices inside each LSOA would therefore report four-fifths of the
country as a total desert, which is an artefact of drawing small boundaries, not
a finding about dentistry. People cross LSOA lines to see a dentist; the model
has to as well.

The method: two-step floating catchment area (2SFCA)
-----------------------------------------------------
Standard in health geography, and simple enough to explain in a paragraph —
which matters, because constraint C8 means publishing the method, not just the
map.

*Step 1.* For each practice, divide its delivered UDAs by the population living
within the catchment radius. That gives a supply-to-demand ratio: UDAs available
per person, from that practice's point of view.

*Step 2.* For each LSOA, add up the ratios of every practice within reach. That
gives UDAs accessible per resident — high where several well-resourced practices
overlap, low where one stretched practice serves a wide area.

Two properties make this honest. A practice serving a dense city shares its
capacity among many people, so raw size does not flatter it. And an LSOA with no
practice inside it is not automatically a desert — only one with no practice
*within reach* is.

Deliberate simplifications, recorded rather than hidden
-------------------------------------------------------
* **Straight-line distance**, as the build plan specifies ("by straight-line
  distance first, refined by drive time"). This understates isolation where
  rivers, estuaries and mountains force long detours — Cornwall and the Lake
  District will look better here than they are.
* **A hard catchment edge.** Someone 100 m outside the radius counts for nothing
  while someone 100 m inside counts fully. A distance-decay weighting is the
  standard refinement and is left for later.
* **Supply is measured as delivered UDAs, not capacity.** A practice that could
  do more but was not commissioned to looks identical to one at its limit. This
  measures the system as it operates, which is the honest reading of the data we
  have.

Nothing here predicts anything (constraint C9). It describes what was delivered
against who lives there.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Run directly as a script, `analysis/` is the only thing on sys.path, so the
# ingest modules this reads from would not import. pytest adds both already.
_INGEST = Path(__file__).resolve().parent.parent / "ingest"
if str(_INGEST) not in sys.path:
    sys.path.insert(0, str(_INGEST))

EARTH_RADIUS_KM = 6371.0088

# Catchment radius. 10 km is a reasonable default for routine dental care in
# England — far enough that urban residents genuinely have choice, tight enough
# that it does not paper over rural isolation. Reported alongside sensitivity.
DEFAULT_RADIUS_KM = 10.0
CHUNK = 512  # LSOAs per distance batch; keeps peak memory in the low hundreds of MB


@dataclass(slots=True)
class SupplyPoint:
    """A practice, with the activity it delivered."""

    org_id: str
    latitude: float
    longitude: float
    uda_delivered: float


@dataclass(slots=True)
class DemandPoint:
    """An LSOA, with the people who live there."""

    lsoa_code: str
    latitude: float
    longitude: float
    population: int


@dataclass(slots=True)
class LsoaAccess:
    lsoa_code: str
    population: int
    nearest_practice_km: float
    practices_within_radius: int
    uda_per_1000: float

    @property
    def has_no_practice_in_reach(self) -> bool:
        return self.practices_within_radius == 0


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. Vectorised over numpy arrays."""
    rlat1, rlat2 = np.radians(lat1), np.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(rlat1) * np.cos(rlat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _arrays(points, lat_attr="latitude", lon_attr="longitude"):
    lats = np.fromiter((getattr(p, lat_attr) for p in points), dtype=float, count=len(points))
    lons = np.fromiter((getattr(p, lon_attr) for p in points), dtype=float, count=len(points))
    return lats, lons


def compute_access(
    demand: list[DemandPoint],
    supply: list[SupplyPoint],
    radius_km: float = DEFAULT_RADIUS_KM,
) -> list[LsoaAccess]:
    """Run 2SFCA and return per-LSOA accessibility."""
    if not demand:
        return []

    d_lat, d_lon = _arrays(demand)
    pop = np.fromiter((p.population for p in demand), dtype=float, count=len(demand))

    if not supply:
        return [
            LsoaAccess(p.lsoa_code, p.population, float("inf"), 0, 0.0) for p in demand
        ]

    s_lat, s_lon = _arrays(supply)
    uda = np.fromiter((s.uda_delivered for s in supply), dtype=float, count=len(supply))

    # -- Step 1: each practice's supply-to-demand ratio ---------------------
    # Population within reach of each practice, accumulated over LSOA chunks so
    # the full (LSOA x practice) matrix never has to exist at once.
    pop_in_reach = np.zeros(len(supply), dtype=float)
    for start in range(0, len(demand), CHUNK):
        stop = min(start + CHUNK, len(demand))
        dist = haversine_km(
            d_lat[start:stop, None], d_lon[start:stop, None], s_lat[None, :], s_lon[None, :]
        )
        within = dist <= radius_km
        pop_in_reach += (within * pop[start:stop, None]).sum(axis=0)

    # A practice with nobody in reach has an undefined ratio, not an infinite
    # one. Zero is the honest value: it contributes nothing to anyone.
    ratio = np.divide(uda, pop_in_reach, out=np.zeros_like(uda), where=pop_in_reach > 0)

    # -- Step 2: sum reachable ratios for each LSOA ------------------------
    results: list[LsoaAccess] = []
    for start in range(0, len(demand), CHUNK):
        stop = min(start + CHUNK, len(demand))
        dist = haversine_km(
            d_lat[start:stop, None], d_lon[start:stop, None], s_lat[None, :], s_lon[None, :]
        )
        within = dist <= radius_km
        access = (within * ratio[None, :]).sum(axis=1) * 1000.0
        nearest = dist.min(axis=1)
        counts = within.sum(axis=1)

        for i, point in enumerate(demand[start:stop]):
            results.append(
                LsoaAccess(
                    lsoa_code=point.lsoa_code,
                    population=point.population,
                    nearest_practice_km=round(float(nearest[i]), 3),
                    practices_within_radius=int(counts[i]),
                    uda_per_1000=round(float(access[i]), 2),
                )
            )
    return results


def summarise(results: list[LsoaAccess], radius_km: float = DEFAULT_RADIUS_KM) -> dict:
    """Estate-wide picture, population-weighted where it matters.

    Averaging over LSOAs would over-weight sparsely populated rural areas; the
    headline figures are therefore weighted by the people actually affected.
    """
    if not results:
        return {"lsoas": 0}

    pop = np.array([r.population for r in results], dtype=float)
    access = np.array([r.uda_per_1000 for r in results], dtype=float)
    nearest = np.array([r.nearest_practice_km for r in results], dtype=float)
    finite = np.isfinite(nearest)

    total_pop = pop.sum()
    order = np.argsort(access)
    cumulative = np.cumsum(pop[order])
    # Population-weighted decile boundary: the access level below which the
    # worst-served 10% of people live.
    decile_idx = int(np.searchsorted(cumulative, total_pop * 0.10))
    worst_decile_threshold = float(access[order][min(decile_idx, len(order) - 1)])

    unserved = np.array([r.has_no_practice_in_reach for r in results])

    return {
        "lsoas": len(results),
        "radius_km": radius_km,
        "population": int(total_pop),
        "median_nearest_km": float(np.median(nearest[finite])) if finite.any() else None,
        "p95_nearest_km": float(np.percentile(nearest[finite], 95)) if finite.any() else None,
        "max_nearest_km": float(nearest[finite].max()) if finite.any() else None,
        "lsoas_with_no_practice_in_reach": int(unserved.sum()),
        "population_with_no_practice_in_reach": int(pop[unserved].sum()),
        "mean_uda_per_1000_pop_weighted": float((access * pop).sum() / total_pop),
        "median_uda_per_1000": float(np.median(access)),
        "worst_decile_threshold": worst_decile_threshold,
        "population_in_worst_decile": int(cumulative[min(decile_idx, len(cumulative) - 1)]),
    }


def format_summary(stats: dict) -> str:
    if not stats.get("lsoas"):
        return "No LSOAs to report."

    def km(value):
        return "—" if value is None else f"{value:.1f} km"

    return "\n".join(
        [
            (
                f"{stats['lsoas']:,} English LSOAs · {stats['population']:,} people "
                f"· {stats['radius_km']:.0f} km catchment"
            ),
            "",
            "  distance to nearest practice:",
            (
                f"    median {km(stats['median_nearest_km'])}   "
                f"95th pct {km(stats['p95_nearest_km'])}   "
                f"worst {km(stats['max_nearest_km'])}"
            ),
            "",
            (
                f"  LSOAs with no practice within {stats['radius_km']:.0f} km: "
                f"{stats['lsoas_with_no_practice_in_reach']:,}"
            ),
            f"  people living there: {stats['population_with_no_practice_in_reach']:,}",
            "",
            "  accessible NHS dental activity (UDAs per 1,000 people):",
            f"    population-weighted mean {stats['mean_uda_per_1000_pop_weighted']:,.0f}",
            f"    median LSOA             {stats['median_uda_per_1000']:,.0f}",
            (
                f"    worst-served 10% of the population live below "
                f"{stats['worst_decile_threshold']:,.0f}"
            ),
        ]
    )


def load_inputs(dist_dir: Path | str = "data/dist", months: int = 12):
    """Assemble demand and supply from the built pipeline outputs."""
    import polars as pl

    dist = Path(dist_dir)
    centroids = pl.read_parquet(dist / "lsoa_centroids.parquet")
    population = pl.read_parquet(dist / "lsoa_population.parquet")
    crosswalk = pl.read_parquet(dist / "contract_to_ods.parquet").filter(pl.col("org_id") != "")
    activity = pl.read_parquet(dist / "bsa_activity.parquet")
    postcodes = pl.read_parquet(dist / "postcodes.parquet")

    demand_frame = centroids.join(
        population.select(["lsoa_code", "total"]), on="lsoa_code", how="inner"
    )
    demand = [
        DemandPoint(r["lsoa_code"], r["latitude"], r["longitude"], int(r["total"]))
        for r in demand_frame.iter_rows(named=True)
    ]

    recent = sorted(activity["year_month"].unique().to_list())[-months:]
    per_contract = (
        activity.filter(pl.col("year_month").is_in(recent))
        .group_by("contract_number")
        .agg(pl.col("uda_delivered").sum().alias("uda"))
    )

    # Contract -> practice, then practice -> location. Several contracts can land
    # on one practice; their activity sums, which is the correct reading.
    from ods import load_register

    ods_postcode = {p.org_id: "".join(p.postcode.split()).upper() for p in load_register()}
    coords = {
        r["postcode"]: (r["latitude"], r["longitude"])
        for r in postcodes.filter(
            (pl.col("country") == "England") & pl.col("latitude").is_not_null()
        ).iter_rows(named=True)
    }

    uda_by_org: dict[str, float] = {}
    for row in crosswalk.join(per_contract, on="contract_number", how="inner").iter_rows(
        named=True
    ):
        uda_by_org[row["org_id"]] = uda_by_org.get(row["org_id"], 0.0) + (row["uda"] or 0.0)

    supply = []
    for org_id, uda in uda_by_org.items():
        pc = ods_postcode.get(org_id, "")
        if pc in coords and uda > 0:
            lat, lon = coords[pc]
            supply.append(SupplyPoint(org_id, lat, lon, uda))

    return demand, supply, recent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Supply-vs-demand / dental-desert model.")
    ap.add_argument("--dist", default="data/dist")
    ap.add_argument("--radius", type=float, default=DEFAULT_RADIUS_KM)
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--out", default="data/dist/lsoa_access.parquet")
    ap.add_argument("--sensitivity", action="store_true", help="also report other radii")
    args = ap.parse_args(argv)

    try:
        demand, supply, months = load_inputs(args.dist, args.months)
    except FileNotFoundError as exc:
        print(f"FATAL: missing pipeline output — {exc}", file=sys.stderr)
        return 1

    total_uda = sum(s.uda_delivered for s in supply)
    print(
        f"Demand: {len(demand):,} LSOAs · "
        f"Supply: {len(supply):,} located practices, "
        f"{total_uda:,.0f} UDAs over {len(months)} months "
        f"({months[0]}–{months[-1]})\n"
    )

    results = compute_access(demand, supply, args.radius)
    print(format_summary(summarise(results, args.radius)))

    if args.sensitivity:
        print("\n  sensitivity to catchment radius:")
        for radius in (5.0, 10.0, 20.0):
            stats = summarise(compute_access(demand, supply, radius), radius)
            print(
                f"    {radius:>4.0f} km  "
                f"{stats['lsoas_with_no_practice_in_reach']:>6,} LSOAs unreached  "
                f"{stats['population_with_no_practice_in_reach']:>9,} people  "
                f"mean {stats['mean_uda_per_1000_pop_weighted']:>6,.0f} UDAs/1k"
            )

    import polars as pl

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        [
            {
                "lsoa_code": r.lsoa_code,
                "population": r.population,
                "nearest_practice_km": (
                    None if math.isinf(r.nearest_practice_km) else r.nearest_practice_km
                ),
                "practices_within_radius": r.practices_within_radius,
                "uda_per_1000": r.uda_per_1000,
            }
            for r in results
        ]
    ).write_parquet(out, compression="zstd")
    print(f"\nWrote {len(results):,} LSOA rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
