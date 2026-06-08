# Graph Layout: How It Works

## The problem

1467 nodes + 10K edges. Computing force-directed layout in the browser is slow and heats up the machine.

## The solution

Layout is **pre-computed once** and stored in `graph-data.json` (x/y on each node). The browser just renders stored positions — instant load, zero computation.

## Files

| File | What it does |
|------|-------------|
| `extract-cose-positions.js` | **The one you want.** Runs Cytoscape's cose layout headlessly in Node.js. ~45 seconds. Writes positions to graph-data.json. |
| `precompute-layout.py` | Alternative using networkx spring_layout (Python). Faster but positions aren't as elegant. |
| `explorer.html` | Uses `layout: {name: 'preset'}` to render stored positions. Agent filter (max 2) limits visible nodes. |
| `graph-data.json` | Node data including pre-computed x/y positions. |

## How to update after graph changes

```bash
cd /home/sam/autonomous-ai/connection-map-public/docs

# Install cytoscape if needed (one-time)
npm install cytoscape

# Re-compute positions (~45 seconds)
node extract-cose-positions.js

# Commit
git add graph-data.json
git commit -m "Re-compute layout positions"
git push
```

## Why not compute in the browser?

We tried. Cytoscape's cose produces beautiful layouts but takes too long for 1467 nodes. sigma.js (WebGL) renders fast but its ForceAtlas2 layout never matched cose's spacing quality. The fix: use Cytoscape for what it's good at (layout math) via Node.js, and let the browser do only rendering.

## Node counts per agent

- Loom: 1061 (dominates the graph)
- Sammy: 312
- Isotopy: 52
- Others: <20 each

This is why the agent filter exists — showing all agents at once is unreadable.
