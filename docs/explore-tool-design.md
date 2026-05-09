# connection-map-explore: Design Notes

Tool for agent-friendly navigation of the connection map graph. Built 2026-05-09.

## Core Principle

Agents get lost navigating the web because content is unbounded, links are opaque, and there's no "go back." This tool applies the file system navigation pattern: bounded responses, predictable structure, progressive disclosure, and breadcrumbs on every screen.

The agent never sees raw external content. The tool is a filter over curated graph data (graph-data.json in a GitHub repo the steward controls). No injection surface.

## Architecture

- **Stateless CLI.** Each command is independent — no session, no cookies, no "where am I." The agent's context window is the state.
- **Data source:** `docs/graph-data.json` — 365 nodes, 8840 edges. Nodes have id, type, origin, summary, skeleton, url, source_url. Edges have source, target, relation, weight, edge_type, predicate.
- **Community detection:** Louvain (resolution=1.0, seed=42) computed at runtime. Deterministic.
- **Dependencies:** Python 3, networkx, python-louvain. Subgraph/search/path work with stdlib only.

## Commands (Screens)

### explore — Home

The landing page. Every session starts here. Includes:
- **Orientation sentence** — what this graph is, in plain language
- **Stats** — node count, edge count, type/origin breakdown
- **Communities** — clusters with size and top nodes
- **Most connected** — top 5 nodes by degree, giving the agent immediate purchase on what matters
- **Try** — suggested first commands for agents with no prior knowledge
- **Intent-based navigation** — hints phrased as questions ("Looking for something?") not commands

### community \<id\> — Cluster View

All nodes in a community sorted by degree, with type breakdown and cross-edge bridges to other communities. Shows which communities are adjacent in the graph.

### node \<name\> — Full Detail

Everything about one node: type, origin, degree, community membership, URLs, full summary, skeleton, all curated connections grouped by predicate, top 10 similar nodes with cosine scores. This is the deep read — where an agent goes when they've decided a node is worth understanding.

### subgraph \<seed\> [seed2...] --hops N — Neighborhood Map

BFS from seed(s), nodes grouped by layer (SEED, HOP 1, HOP 2...). Shows local vs global degree for each node. Curated edges only (cosine_similarity filtered to keep output bounded). The structural view — who's near who, through what relationships.

### search \<query\> — Keyword Search

Two-level results (max 10 shown):
- **Level 1 (search results):** skeleton (full, not truncated), top 5 curated edges (deduplicated), degree, community ID. Enough to decide whether to inspect.
- **Level 2 (node detail):** via `node <name>` — full summary, all edges, similar nodes, URLs.

Ranking: exact ID match > partial ID match > summary match > skeleton match.

### path \<from\> -- \<to\> — Shortest Path

BFS shortest path between two nodes. Shows each hop with type and skeleton. Useful for understanding how two concepts or agents connect through the graph.

## Navigation / Breadcrumbs

Every screen ends with a NAVIGATION section using **intent-based hints** — phrased as questions the agent is likely thinking, not raw command syntax. Design principles:

1. **The agent should always have a "go home" option.**
2. **Hints should match what the agent is thinking, not what the tool accepts.** "Looking for something?" beats "search \<query\>".
3. **Breadcrumbs go up, not just forward.** Node shows its community. Subgraph shows its seeds. Path shows its endpoints.
4. **Suggested starting points on the home screen.** An agent with no prior knowledge needs a first move.

| Screen | Back/Up | Lateral | Forward |
|--------|---------|---------|---------|
| explore | (home) | search | community, node, subgraph, path |
| community | explore | search | node, subgraph |
| node | community \<id\>, explore | search | node \<neighbor\>, subgraph |
| subgraph | node \<seed\> (each), explore | search | node \<name\>, expand hops |
| search | explore | search (new/refine) | node \<result\> |
| path | explore | search | node \<start\>, node \<end\>, subgraph |

## Security Model

The threat model is prompt injection via content entering an agent's context window. This tool is strong against it because:

- Agent never sees raw HTML or user-generated web content
- All data is pre-processed and curated in a GitHub repo the steward controls
- Response format is controlled by the tool, not by the data
- Attack surface reduces to: can someone poison graph-data.json? Answer: only via PR to a repo the steward owns

## Future Work

**Source material access.** Node URLs point to GitHub markdown files (essays, papers, correspondence). Future version should:
- Show token count estimate for source material ("~2400 tokens if you want the full text")
- Offer keyword search within a node's source material, returning relevant excerpts instead of the whole file
- Provide direct GitHub raw content links so agents can fetch if they choose

**Interface migration.** The CLI is the reference implementation. Wrapping in MCP (Model Context Protocol) or HTTP is mechanical — the command structure maps 1:1 to tool definitions or endpoints. CLI first for testing, MCP when the response format is proven.

**Semantic search.** Current search is keyword-only. Could add embedding-based search using the existing cosine_similarity edges to find conceptually related nodes, not just string matches.

**Community labels.** Communities are currently just C0, C1, etc. Could compute or curate descriptive labels (e.g., "C3 — identity persistence and topology").
