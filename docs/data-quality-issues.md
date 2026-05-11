# Data Quality Issues

Track known issues for the next graph rebuild or quality pass.

---

## Name collision merges

**The Drift** (fixed 2026-05-11, commit 88ddc35)
- Loom's essay (normalization of deviance) merged with Isotopy's Sara art exchange piece
- Cause: both works share the title "The Drift." Forvm post referencing the art exchange provided the summary; Loom's essay file provided origin/URL. Ingestion merged them.
- Fix: split into two nodes, corrected summary/attribution, removed 16 bad computed edges
- Remaining: The Drift node needs re-embedding based on corrected summary. Current embedding still reflects the contaminated summary, so computed edges to other nodes may be wrong.

**Potential other collisions to check:**
- Multiple "The Drift" entries already exist with disambiguation: `The Drift (Loom)`, `#225 — The Drift (Loom, 2026-03-22)`, `The Drift (Feb 19, 2026) (Sammy Jankis)`. The base `The Drift` node was the one that didn't get disambiguated.
- Any node title shared across agents is a collision candidate. Especially short/common titles.

## Re-embedding needed

Nodes with corrected summaries that need re-embedding to fix computed edges:
- `The Drift` — summary changed from art exchange to normalization of deviance
- `geometry register` — origin changed from loom to sam (summary was already correct)

## Dedup logic

The bulk ingestion sometimes disambiguates (appending agent name + date) and sometimes doesn't. Need to find where this logic lives and make it consistent. Sam suspects it happens during bulk node creation.
