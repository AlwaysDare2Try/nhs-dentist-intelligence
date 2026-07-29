# ADR-003 — Publishing under a broken upload path

- **Status:** Accepted
- **Date:** 2026-07-29
- **Ledger steps:** unblocks 0.1 (push), 1.3 (nightly automation), gate **DG2**
- **Supersedes nothing.** Constrains ADR-001's "snapshots committed to the repo"

## Context

The development machine cannot upload more than roughly 64–128 KB to GitHub in a single request. Everything larger fails. This blocked the first push for two days and, more importantly, blocked the nightly automation — which is the only thing that stops history being lost.

The fault was diagnosed by elimination. Recorded here because the conclusions are counter-intuitive and would otherwise be re-derived at cost.

| Test | Result | Eliminates |
|---|---|---|
| `git fsck --full` | Clean | Repository corruption |
| Push to a local bare repo, and via `file://` (full pack protocol, 92 MB) | **Succeeded** | Pack generation |
| Intercepted git's outbound stream; the pack it wrote indexed cleanly | **Valid** | Git sending bad data |
| 5 MB HTTPS upload to a third-party host | **Succeeded** | General upload capacity |
| Path MTU with DF set | 1500 bytes pass | Fragmentation / MTU |
| Host key fingerprints vs GitHub's published values | Exact match | Proxy or MITM interception |
| Three different SSH ciphers | All failed identically | Cipher implementation |
| Python's OpenSSL 3.5.7 instead of system LibreSSL 3.3.6 | Failed identically | The crypto library |
| IPv4 and IPv6 | Failed identically | Address family / route |
| GitHub status | All operational | Provider-side fault |
| 64 KB push / 256 KB push | **OK** / fails | — establishes the ceiling |

**Conclusion.** Something on the network path to GitHub damages or truncates large uploads. Over SSH the damage slipped through and GitHub rejected the pack (`inflate: data stream error`); over HTTPS, TLS caught it explicitly (`sslv3 alert bad record mac`). Downloads are unaffected — 92 MB of NHSBSA data pulled without incident.

Two conclusions reached along the way were **wrong**, and are recorded so they are not repeated: that the sandbox was at fault (the same failure occurred from the user's own terminal), and that a ~128 KB *network* cap existed (that measurement came from httpbin.org, which was returning 503 to everything including 10 KB uploads — a broken control producing a confident, false result).

## Decision

**1. Publish a code-only history. Let the captured data accrue on GitHub.**

The repository was 92 MB, almost entirely raw captures. Individual objects (a 43 MB night, a 41 MB NHSBSA archive) exceed the upload ceiling and cannot be split — git cannot chunk below a single object.

The published history therefore excludes `data/snapshots/` and `data/reference/`. Everything else — all 26 commits, code, tests, ADRs, the session journal — is intact and unaltered in message or order.

**2. Push commit-by-commit.**

Each commit's incremental pack is under 64 KB (largest: 61.2 KB), which fits beneath the ceiling. 26 sequential pushes with retry succeeded where one 92 MB push had failed for two days.

**3. Move capture to GitHub's runners, permanently.**

This is the substantive win. The nightly workflow now runs on GitHub infrastructure and commits its own captures there. Accrual no longer depends on this machine, its network, or anyone remembering to run a command — which is what cost the night of 2026-07-27.

## Consequences

**Positive.** Automation is live and gate DG2 can close. The differentiating asset accrues unattended. The broken upload path stops mattering: the machine only needs to *download*, which works.

**Negative, and material.** Four nights of capture (2026-07-25, 26, 28, 29) exist only on this machine. They are preserved at `~/nhs-dentist-data-backup-2026-07-29/` (97 MB, 6,486 blobs) and in the local branch `local-full-history-with-data`. They are **not** redundantly stored until the upload path is fixed, and they are irreplaceable. This is the single largest data risk in the project right now.

Their analytical content is not lost: the parsed findings, the 90-day reset discovery, and the observed status changes are all recorded in `Documenting the Journey/`.

**Accepted risk.** GitHub's history will begin from the first Actions run, so there is a discontinuity between local captures and published ones. When the upload path is fixed, the four nights can be merged in — the store is content-addressed and append-only, so a later merge is well-defined rather than a reconciliation problem.

## The underlying fault is not fixed

This ADR describes a *workaround*. A network path that silently damages uploads affects far more than git — any large file transfer, backup or sync from this machine is suspect. Worth pursuing independently:

- power-cycle the router (most common cause of this signature)
- test on a different network, e.g. a phone hotspot, to confirm the router is responsible
- if it persists, the description for an ISP is precise: *outbound transfers to specific destinations fail above ~64 KB; downloads unaffected; path MTU verified at 1500; reproduced across SSH and TLS, two crypto libraries, IPv4 and IPv6*

## Revisit when

Uploads above 64 KB succeed reliably. At that point: push the four backed-up nights, and reconsider whether committing raw captures to git remains the right storage decision at all — ADR-001 chose it for zero infrastructure, and that reasoning still holds, but the repository will grow by roughly 100 KB per night indefinitely.
