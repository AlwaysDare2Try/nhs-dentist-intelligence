# ADR-003 — TCP Segmentation Offload corrupting outbound data

- **Status:** Accepted — **root cause found and fixed 2026-07-30**
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

**Root cause — found 2026-07-30.** **TCP Segmentation Offload on the Wi-Fi interface.**

```
en1: options=6460<TSO4,TSO6,CHANNEL_IO,PARTIAL_CSUM,ZEROINVERT_CSUM>
net.inet.tcp.tso: 1
net.link.generic.system.hwcksum_tx: 1
```

With TSO enabled the kernel hands large buffers to the NIC, which segments them **and computes the TCP checksum itself, after segmenting**. A driver that corrupts a segment then stamps a *valid* checksum onto the damage, so TCP never detects it. TLS and SSH compute their MACs in software over the original bytes, so the far end sees the corruption and reports `bad record mac` or a bad pack.

That accounts for every observation in the table above: downloads unaffected (receive path), `file://` unaffected (no NIC involved), both crypto libraries failing identically (the damage happens *below* them), IPv4 and IPv6 both failing (TSO4 and TSO6 both enabled), and failure probability scaling with transfer size.

**The fix:**

```bash
sudo ifconfig en1 -tso
sudo sysctl -w net.inet.tcp.tso=0
sudo sysctl -w net.link.generic.system.hwcksum_tx=0
```

**Verified:** 1 MB, 8 MB and 32 MB pushes all succeed, where 256 KB had failed consistently an hour earlier. The full 88 MiB repository then pushed in **4.8 seconds**.

**Superseded conclusion.** The original text below said "something on the network path damages large uploads" and treated it as unfixable from this machine. That was wrong — it was a local NIC offload setting, one command away. The diagnosis stopped one layer too high: every test above examined git, crypto and routing, but none looked at `ifconfig` options. Recorded because the lesson generalises — when a checksum-protected layer reports corruption that a lower checksum did not catch, suspect hardware offload. Over SSH the damage slipped through and GitHub rejected the pack (`inflate: data stream error`); over HTTPS, TLS caught it explicitly (`sslv3 alert bad record mac`). Downloads are unaffected — 92 MB of NHSBSA data pulled without incident.

Two conclusions reached along the way were **wrong**, and are recorded so they are not repeated: that the sandbox was at fault (the same failure occurred from the user's own terminal), and that a ~128 KB *network* cap existed (that measurement came from httpbin.org, which was returning 503 to everything including 10 KB uploads — a broken control producing a confident, false result).

## Decision

**1. Publish a code-only history. Let the captured data accrue on GitHub.**

The repository was 92 MB, almost entirely raw captures. Individual objects (a 43 MB night, a 41 MB NHSBSA archive) exceed the upload ceiling and cannot be split — git cannot chunk below a single object.

The published history therefore excludes `data/snapshots/` and `data/reference/`. Everything else — all 26 commits, code, tests, ADRs, the session journal — is intact and unaltered in message or order.

**2. Push commit-by-commit.** *(No longer required — retained as history.)*

Each commit's incremental pack is under 64 KB (largest: 61.2 KB), which fits beneath the ceiling. 26 sequential pushes with retry succeeded where one 92 MB push had failed for two days.

**3. Move capture to GitHub's runners, permanently.**

This is the substantive win. The nightly workflow now runs on GitHub infrastructure and commits its own captures there. Accrual no longer depends on this machine, its network, or anyone remembering to run a command — which is what cost the night of 2026-07-27.

## Consequences

**Positive.** Automation is live and gate DG2 can close. The differentiating asset accrues unattended. The broken upload path stops mattering: the machine only needs to *download*, which works.

**Resolved 2026-07-30.** Four nights of capture (2026-07-25, 26, 28, 29) briefly existed only on this machine. They are preserved at `~/nhs-dentist-data-backup-2026-07-29/` (97 MB, 6,486 blobs) and in the local branch `local-full-history-with-data`. Once TSO was disabled they were pushed in full and now sit on GitHub alongside the 2026-07-30 capture that GitHub's own runner produced. **The risk is closed.**

Their analytical content is not lost: the parsed findings, the 90-day reset discovery, and the observed status changes are all recorded in `Documenting the Journey/`.

**Accepted risk.** GitHub's history will begin from the first Actions run, so there is a discontinuity between local captures and published ones. When the upload path is fixed, the four nights can be merged in — the store is content-addressed and append-only, so a later merge is well-defined rather than a reconciliation problem.

## Outstanding: the fix is not yet persistent

`ifconfig` flags and these sysctls **reset on reboot**. Until persistence is installed, a restart silently reinstates the corruption.

Two pieces are needed — a boot-time `sysctl` and a `LaunchDaemon` to reapply the interface flag (`sysctl.conf` cannot set `ifconfig` options). Installing a system daemon was deliberately not automated here; it is a persistent root-level change and belongs to the machine's owner.

Also worth noting: this fault silently corrupted **any** large upload from this machine, not just git — backups, cloud sync and file transfers were all affected for as long as it was present.

## Revisit when

A reboot occurs without persistence installed — check `ifconfig en1 | grep options` before trusting a large push. Longer term, reconsider whether committing raw captures to git remains the right storage decision at all — ADR-001 chose it for zero infrastructure, and that reasoning still holds, but the repository will grow by roughly 100 KB per night indefinitely.
