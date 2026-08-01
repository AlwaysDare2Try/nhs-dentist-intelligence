// Reading the published data contract (schema v1 from analysis/build.py).
//
// The files are columnar — a `fields` array and `rows` of arrays — so key names
// are not repeated 6,400 times. We zip them once on load.
//
// Constraint C1 governs everything rendered from this module: a practice's
// status is what it *reported on a date*, never a statement of current fact.
// `describe()` is the single place that wording is produced.

export const ACCEPTING = "accepting";
export const NOT_ACCEPTING = "not_accepting";
export const NOT_CONFIRMED = "not_confirmed";
export const REFERRAL_ONLY = "referral_only";

const EARTH_RADIUS_KM = 6371.0088;

export function zip(payload) {
  const { fields, rows } = payload;
  const idx = Object.fromEntries(fields.map((f, i) => [f, i]));
  return rows.map((r) => {
    const o = {};
    for (const f of fields) o[f] = r[idx[f]];
    return o;
  });
}

export function haversineKm(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(Math.min(1, a)));
}

/** Nearest practices to a point, closest first. */
export function nearest(practices, lat, lon, limit = 25) {
  const out = [];
  for (const p of practices) {
    if (p.lat == null || p.lon == null) continue;
    out.push({ ...p, km: haversineKm(lat, lon, p.lat, p.lon) });
  }
  out.sort((a, b) => a.km - b.km);
  return out.slice(0, limit);
}

const MONTHS = ["January","February","March","April","May","June",
                "July","August","September","October","November","December"];

export function formatDate(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** Who a practice said it would take. Null cohort means it did not say. */
export function cohorts(p) {
  const out = [];
  if (p.adults === 1) out.push("adults 18 and over");
  if (p.free_care === 1) out.push("adults entitled to free care");
  if (p.children === 1) out.push("children 17 and under");
  return out;
}

/**
 * C1-compliant sentence. Never asserts a current fact — always what was
 * reported, and when. This is the only place this wording is generated.
 */
export function describe(p) {
  const on = formatDate(p.confirmed);
  switch (p.status) {
    case ACCEPTING: {
      const who = cohorts(p);
      const list = who.length ? who.join(", ") : "new NHS patients";
      return on
        ? `Reported accepting ${list}, confirmed ${on}`
        : `Reported accepting ${list}`;
    }
    case NOT_ACCEPTING:
      return on
        ? `Reported not accepting new NHS patients, confirmed ${on}`
        : "Reported not accepting new NHS patients";
    case REFERRAL_ONLY:
      return "Specialist care by referral from another dentist only";
    case NOT_CONFIRMED:
    default:
      // Phrased to avoid the words "accepting"/"currently" entirely. The
      // practice has made no claim, so nothing here should read like one.
      return "Has made no statement about taking new NHS patients";
  }
}

/**
 * How much weight the reader should give it.
 *
 * nhs.uk clears a practice's declaration once it reaches 90 days old, so a
 * declared status is always recent by construction. The interesting signal is
 * the other population: practices that have said nothing, where the only age
 * available is when their profile last changed at all.
 */
export function trust(p) {
  if (p.status === NOT_CONFIRMED || p.age_evidence === "page_lastmod") {
    const days = p.age_days;
    if (days == null) return { tone: "unknown", label: "No information" };
    if (days > 730)
      return { tone: "bad", label: `Nothing published for over ${Math.floor(days / 365)} years` };
    if (days > 365) return { tone: "bad", label: "Nothing published for over a year" };
    if (days > 180) return { tone: "warn", label: "Nothing published for over 6 months" };
    return { tone: "warn", label: "No current statement" };
  }
  if (p.confirmed) {
    const days = p.age_days ?? 0;
    if (days <= 30) return { tone: "good", label: `Confirmed ${days} days ago` };
    return { tone: "ok", label: `Confirmed ${days} days ago` };
  }
  return { tone: "unknown", label: "No information" };
}

/** Postcode → coordinates, via postcodes.io (ONS data, OGL). */
export async function geocodePostcode(postcode) {
  const clean = postcode.trim().replace(/\s+/g, "");
  if (!clean) throw new Error("Enter a postcode");
  const res = await fetch(
    `https://api.postcodes.io/postcodes/${encodeURIComponent(clean)}`
  );
  if (res.status === 404) throw new Error(`No such postcode as "${postcode.trim()}"`);
  if (!res.ok) throw new Error("Postcode lookup is unavailable — try again shortly");
  const body = await res.json();
  const r = body.result;
  if (r.country !== "England") {
    throw new Error(
      `${r.postcode} is in ${r.country}. This service covers England only — dental services elsewhere in the UK are run separately.`
    );
  }
  return { lat: r.latitude, lon: r.longitude, postcode: r.postcode, area: r.admin_district };
}
