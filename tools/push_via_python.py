"""Push to GitHub using Python's TLS stack instead of the system's.

Why this exists
---------------
This machine's system crypto library — LibreSSL 3.3.6, which both Apple's
``git`` and Apple's ``ssh`` link against — corrupts large outbound transfers.
The failure is probabilistic per byte, so small pushes usually succeed and
large ones reliably fail:

* over SSH the corruption slips past silently and GitHub rejects the pack
  ("inflate: data stream error"),
* over HTTPS the TLS layer catches it explicitly
  ("LibreSSL/3.3.6 ... sslv3 alert bad record mac"),
* a ``file://`` push of the identical 92 MB history succeeds, because no
  crypto is involved at all.

The uv-managed Python here bundles its own OpenSSL 3.5.x, entirely separate
from the system library. Driving the push through Python therefore routes the
bytes around the faulty component without touching the repository, the network,
or GitHub.

This is a workaround, not a repair. The underlying fault still affects any large
upload on this machine and is worth fixing properly — see ``docs/ADR-003``.

Usage::

    GITHUB_TOKEN=github_pat_... uv run python tools/push_via_python.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REMOTE = "https://github.com/AlwaysDare2Try/nhs-dentist-intelligence.git"
USERNAME = "AlwaysDare2Try"
REFSPEC = b"refs/heads/main"


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("FATAL: set GITHUB_TOKEN in the environment", file=sys.stderr)
        return 2

    import ssl

    from dulwich.client import HttpGitClient
    from dulwich.repo import Repo

    print(f"Python TLS backend: {ssl.OPENSSL_VERSION}")
    print(f"repo:   {REPO}")
    print(f"remote: {REMOTE}")

    repo = Repo(str(REPO))
    local_sha = repo.refs[REFSPEC]
    print(f"pushing {REFSPEC.decode()} -> {local_sha.decode()[:12]}")

    client = HttpGitClient(REMOTE, username=USERNAME, password=token)

    def determine_wants(refs, **kwargs):
        # Fast-forward only: refuse to clobber anything already on the remote.
        remote_sha = refs.get(REFSPEC)
        if remote_sha and remote_sha != local_sha:
            walker = repo.get_walker(include=[local_sha])
            if remote_sha not in {e.commit.id for e in walker}:
                raise SystemExit(
                    f"refusing to push: remote {remote_sha.decode()[:12]} is not an "
                    f"ancestor of local {local_sha.decode()[:12]}"
                )
        return {REFSPEC: local_sha}

    sent = {"objects": 0}

    def generate_pack_data(have, want, progress=None, ofs_delta=True):
        count, chunks = repo.object_store.generate_pack_data(
            have, want, progress=progress, ofs_delta=ofs_delta
        )
        sent["objects"] = count
        print(f"packing {count:,} objects...", flush=True)
        return count, chunks

    started = time.time()
    try:
        result = client.send_pack(
            "/AlwaysDare2Try/nhs-dentist-intelligence.git",
            determine_wants,
            generate_pack_data,
        )
    except Exception as exc:  # noqa: BLE001 - report any transport failure plainly
        print(f"\nFAILED after {time.time() - started:.0f}s: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    elapsed = time.time() - started
    errors = getattr(result, "ref_status", None) or {}
    bad = {r: e for r, e in errors.items() if e}
    if bad:
        print(f"\nremote rejected: {bad}", file=sys.stderr)
        return 1

    print(f"\nPUSHED {sent['objects']:,} objects in {elapsed:.0f}s")
    print(f"  {REFSPEC.decode()} -> {local_sha.decode()[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
