"""[8] Hashing & Versioning — source-artifact integrity.

Every stored upload is already content-hashed at intake (compress-then-hash into
``UploadedFile.sha256``). This stage is the integrity checkpoint: it fills any
missing hash defensively (e.g. a hand-built context that skipped intake), then
computes a single **source-manifest digest** — a SHA-256 over the sorted per-file
hashes — that fingerprints the exact set of source documents. The report stage
embeds that digest, tying the sealed report to the precise inputs it was built
from; if any source file changes, the manifest (and therefore the report hash)
changes.

Integrity/audit, not confidentiality. The audit entry carries type/version only
(the digest is a hash, never PHI content).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.context import SessionContext
from core.stage import Stage


def source_manifest_digest(ctx: SessionContext) -> str | None:
    """SHA-256 over the sorted ``id:sha256`` of every hashed upload.

    Order-independent (ids are sorted) so re-uploading the same files in a
    different order yields the same manifest. Returns None when nothing is
    hashed yet.
    """
    parts = sorted(f"{u.id}:{u.sha256}" for u in ctx.uploads if u.sha256)
    if not parts:
        return None
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


class HashingStage(Stage):
    name = "hashing"
    order = 8
    description = "Content hash + version stamp on the report."

    def run(self, ctx: SessionContext) -> SessionContext:
        filled = 0
        for u in ctx.uploads:
            if u.sha256:
                continue
            path = u.path or u.processed_path or u.source_path
            if path and Path(path).exists():
                u.sha256 = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                filled += 1

        manifest = source_manifest_digest(ctx)
        hashed = sum(1 for u in ctx.uploads if u.sha256)
        ctx.log(
            "stage.hashing.done",
            detail=(f"files={hashed} filled={filled} "
                    f"manifest={manifest[:12] if manifest else 'none'}"),
        )
        return ctx
