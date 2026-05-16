#!/usr/bin/env python3
"""
Recompute cosine_similarity edges across ALL 365 nodes in graph-data.json.

Embeds all node summaries via OpenAI text-embedding-3-large, computes pairwise
cosine similarity, and replaces existing cosine_similarity edges with the full
cross-agent set.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np

GRAPH_PATH = Path(__file__).parent / "graph-data.json"
THRESHOLD = 0.40

def load_credentials():
    cred_path = Path(os.path.expanduser("~/autonomous-ai/isotopy-archive/credentials.txt"))
    creds = {}
    if cred_path.exists():
        for line in cred_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    return creds

def get_openai_client():
    from openai import OpenAI
    creds = load_credentials()
    api_key = creds.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not found")
        sys.exit(1)
    return OpenAI(api_key=api_key)

def embed_summaries(nodes, client):
    texts = [n["summary"] for n in nodes]
    embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        print(f"  Embedding batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1} ({len(batch)} nodes)...")
        response = client.embeddings.create(model="text-embedding-3-large", input=batch)
        embeddings.extend([np.array(d.embedding) for d in response.data])
    return np.stack(embeddings)

def cosine_similarity_matrix(mat):
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normed = mat / norms
    return normed @ normed.T

CACHE_PATH = Path(__file__).parent / "all-embeddings.json"

def main():
    with open(GRAPH_PATH) as f:
        graph = json.load(f)

    nodes = graph["nodes"]
    print(f"Loaded {len(nodes)} nodes")

    # Check cache
    cache = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text())
        print(f"Loaded {len(cache)} cached embeddings")

    missing = [n for n in nodes if n["id"] not in cache]
    if missing:
        print(f"Embedding {len(missing)} nodes ({len(nodes) - len(missing)} cached)...")
        client = get_openai_client()
        new_embs = embed_summaries(missing, client)
        for i, n in enumerate(missing):
            cache[n["id"]] = new_embs[i].tolist() if hasattr(new_embs[i], 'tolist') else new_embs[i]
        CACHE_PATH.write_text(json.dumps(cache))
        print(f"Cache updated: {len(cache)} total embeddings")
    else:
        print("All nodes cached, skipping API calls")

    embeddings = np.array([cache[n["id"]] for n in nodes])
    print(f"Got {embeddings.shape[0]} embeddings of dimension {embeddings.shape[1]}")

    # Compute pairwise similarity
    print("Computing pairwise cosine similarity...")
    sim = cosine_similarity_matrix(embeddings)

    # Build new cosine_similarity edges
    new_cos_edges = []
    n = len(nodes)
    for i in range(n):
        for j in range(i + 1, n):
            score = float(sim[i, j])
            if score >= THRESHOLD:
                # Skip if node names are substrings of each other
                id_i = nodes[i]["id"].lower()
                id_j = nodes[j]["id"].lower()
                if id_i in id_j or id_j in id_i:
                    continue
                src_o = nodes[i].get("origin", "?")
                tgt_o = nodes[j].get("origin", "?")
                if isinstance(src_o, list): src_o = tuple(sorted(src_o))
                if isinstance(tgt_o, list): tgt_o = tuple(sorted(tgt_o))
                new_cos_edges.append({
                    "source": nodes[i]["id"],
                    "target": nodes[j]["id"],
                    "predicate": "cosine_similarity",
                    "weight": round(score, 4),
                    "edge_type": "computed",
                    "cross_agent": src_o != tgt_o
                })

    # Count by agent pair
    def origin_str(o):
        return "+".join(sorted(o)) if isinstance(o, list) else (o or "?")
    origin_map = {n["id"]: origin_str(n.get("origin", "?")) for n in nodes}
    from collections import Counter
    pair_counts = Counter()
    for e in new_cos_edges:
        pair = tuple(sorted([origin_map.get(e["source"], "?"), origin_map.get(e["target"], "?")]))
        pair_counts[pair] += 1

    print(f"\nNew cosine_similarity edges: {len(new_cos_edges)} (threshold={THRESHOLD})")
    print("By agent pair:")
    for k, v in sorted(pair_counts.items(), key=lambda x: -x[1]):
        print(f"  {k[0]} - {k[1]}: {v}")

    # Weight stats
    weights = [e["weight"] for e in new_cos_edges]
    print(f"Weight range: {min(weights):.3f} - {max(weights):.3f}, mean: {np.mean(weights):.3f}")

    # Replace cosine_similarity edges in graph
    non_cos_edges = [e for e in graph["edges"] if e.get("predicate") != "cosine_similarity"]
    print(f"\nKept {len(non_cos_edges)} non-cosine edges")

    graph["edges"] = non_cos_edges + new_cos_edges
    print(f"Total edges: {len(graph['edges'])}")

    # Write back
    with open(GRAPH_PATH, "w") as f:
        json.dump(graph, f, separators=(",", ":"))
    print(f"Written to {GRAPH_PATH}")

if __name__ == "__main__":
    main()
