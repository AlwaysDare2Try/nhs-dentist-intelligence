"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ACCEPTING,
  NOT_CONFIRMED,
  cohorts,
  describe,
  geocodePostcode,
  nearest,
  trust,
  zip,
} from "./lib/practices";

const RESULT_COUNT = 25;

export default function Home() {
  const [practices, setPractices] = useState(null);
  const [meta, setMeta] = useState(null);
  const [loadError, setLoadError] = useState(null);

  const [postcode, setPostcode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState(null);
  const [origin, setOrigin] = useState(null);
  const [openOnly, setOpenOnly] = useState(false);
  const resultsRef = useRef(null);

  useEffect(() => {
    Promise.all([
      fetch("data/practices.json").then((r) => r.json()),
      fetch("data/meta.json").then((r) => r.json()),
    ])
      .then(([p, m]) => {
        setPractices(zip(p));
        setMeta(m);
      })
      .catch(() => setLoadError("Could not load the practice data. Please reload the page."));
  }, []);

  const search = useCallback(
    async (e) => {
      e.preventDefault();
      if (!practices) return;
      setBusy(true);
      setError(null);
      try {
        const where = await geocodePostcode(postcode);
        setOrigin(where);
        setResults(nearest(practices, where.lat, where.lon, RESULT_COUNT));
        requestAnimationFrame(() =>
          resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
        );
      } catch (err) {
        setError(err.message);
        setResults(null);
      } finally {
        setBusy(false);
      }
    },
    [postcode, practices]
  );

  const shown = results
    ? openOnly
      ? results.filter((p) => p.status === ACCEPTING)
      : results
    : null;

  const acceptingCount = results ? results.filter((p) => p.status === ACCEPTING).length : 0;
  const silentCount = results ? results.filter((p) => p.status === NOT_CONFIRMED).length : 0;

  return (
    <>
      <section className="hero">
        <div className="wrap">
          <h1>
            The NHS dentist list tells you what a practice said.
            <br />
            It does not tell you <em>when</em> they said it.
          </h1>
          <p className="lede">
            This does. Search any English postcode to see the nearest NHS dental practices,
            what each one reported about taking new patients, and how long ago that was.
          </p>

          <form className="search" onSubmit={search}>
            <label htmlFor="postcode">Your postcode</label>
            <div className="row">
              <input
                id="postcode"
                name="postcode"
                type="text"
                autoComplete="postal-code"
                placeholder="e.g. SW1A 1AA"
                value={postcode}
                onChange={(e) => setPostcode(e.target.value)}
                aria-describedby={error ? "search-error" : undefined}
                spellCheck="false"
              />
              <button type="submit" disabled={!practices || busy}>
                {busy ? "Searching…" : practices ? "Find dentists" : "Loading…"}
              </button>
            </div>
            {error && (
              <p className="error" id="search-error" role="alert">
                {error}
              </p>
            )}
            {loadError && (
              <p className="error" role="alert">
                {loadError}
              </p>
            )}
          </form>
        </div>
      </section>

      <section className="results" ref={resultsRef}>
        <div className="wrap">
          {shown && origin && (
            <>
              <div className="summary">
                <h2>
                  {results.length} nearest practices to {origin.postcode}
                </h2>
                <p className="counts">
                  <strong>{acceptingCount}</strong> reported taking new NHS patients ·{" "}
                  <strong>{silentCount}</strong> have said nothing at all
                </p>
                {acceptingCount === 0 && (
                  <p className="note">
                    None of the nearest {results.length} reported taking new NHS patients. That
                    is normal — across England only about 28% of practices say they take adults.
                    The dates below still tell you which are worth phoning first.
                  </p>
                )}
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={openOnly}
                    onChange={(e) => setOpenOnly(e.target.checked)}
                  />
                  Show only those reporting they take new patients
                </label>
              </div>

              {shown.length === 0 ? (
                <p className="empty">
                  None of the nearest {results.length} practices reported taking new NHS
                  patients. Clear the filter to see them all with their dates.
                </p>
              ) : (
                <ol className="list">
                  {shown.map((p) => (
                    <PracticeCard key={p.id} p={p} />
                  ))}
                </ol>
              )}
            </>
          )}

          {!shown && meta && (
            <div className="standing">
              <h2>What this is</h2>
              <p>
                Practices are supposed to confirm whether they are taking new NHS patients at
                least every 90 days. The NHS website shows the answer but keeps no record of
                when it changed, so nobody can see how long a practice has been closed, or
                whether it has said anything for years.
              </p>
              <p>
                This service records the answer every night and keeps the history. It covers{" "}
                <strong>{meta.practices.toLocaleString()}</strong> practices across England.
              </p>
              <dl className="facts">
                <div>
                  <dt>Practices tracked</dt>
                  <dd>{meta.practices.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Nights recorded</dt>
                  <dd>
                    {meta.history.nights_captured}
                    <span className="sub">since {meta.history.first}</span>
                  </dd>
                </div>
                <div>
                  <dt>Changes seen</dt>
                  <dd>{meta.history.changes_observed}</dd>
                </div>
                <div>
                  <dt>Last updated</dt>
                  <dd>{meta.as_of}</dd>
                </div>
              </dl>
              {meta.history.nights_missing?.length > 0 && (
                <p className="gap">
                  We are missing {meta.history.nights_missing.length} night
                  {meta.history.nights_missing.length > 1 ? "s" : ""} of our own record (
                  {meta.history.nights_missing.join(", ")}). Changes either side of a gap cannot
                  be dated precisely, and we say so rather than pretending otherwise.
                </p>
              )}
            </div>
          )}
        </div>
      </section>
    </>
  );
}

function PracticeCard({ p }) {
  const t = trust(p);
  const who = cohorts(p);
  return (
    <li className={`card status-${p.status}`}>
      <div className="card-head">
        <h3>{p.name || p.id}</h3>
        <span className="distance">{p.km.toFixed(1)} km</span>
      </div>
      <p className="reported">{describe(p)}</p>
      {who.length > 0 && (
        <ul className="cohorts">
          {who.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <div className="card-foot">
        <span className={`trust tone-${t.tone}`}>{t.label}</span>
        {p.postcode && <span className="pc">{p.postcode}</span>}
      </div>
    </li>
  );
}
