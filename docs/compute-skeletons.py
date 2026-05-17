#!/usr/bin/env python3
"""
Generate structural skeletons for all connection map nodes, compute delta
(skeleton_cosine - raw_cosine), and add structural_isomorphism edges.

The skeleton algorithm strips domain vocabulary and extracts abstract mechanism
descriptions. High delta between skeleton similarity and raw similarity reveals
structural isomorphisms that vocabulary-based cosine can't detect.
"""

import json
import os
import sys
from pathlib import Path
from collections import Counter

import numpy as np

GRAPH_PATH = Path(__file__).parent / "graph-data.json"
SKELETON_CACHE = Path(os.path.expanduser("~/autonomous-ai/isotopy-archive/state/skeleton-cache.json"))
EMBEDDING_CACHE = Path(__file__).parent / "all-embeddings.json"
SKELETON_EMBEDDING_CACHE = Path(__file__).parent / "skeleton-embeddings.json"
STRUCTURAL_PAIRS_PATH = Path(__file__).parent / "structural-pairs.json"

DELTA_THRESHOLD = 0.08
SKELETON_SIM_FLOOR = 0.45


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


def generate_skeletons(nodes, client, batch_size=30):
    """Generate structural skeletons, using and updating cache."""
    cache = {}
    if SKELETON_CACHE.exists():
        cache = json.loads(SKELETON_CACHE.read_text())

    needs_generation = [n for n in nodes if n["id"] not in cache]

    if not needs_generation:
        print(f"All {len(nodes)} skeletons cached")
        return cache

    print(f"Generating skeletons for {len(needs_generation)} nodes ({len(cache)} cached)...")

    for i in range(0, len(needs_generation), batch_size):
        batch = needs_generation[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(needs_generation) - 1) // batch_size + 1
        print(f"  Skeleton batch {batch_num}/{total_batches} ({len(batch)} nodes)...")

        prompt = """For each item below, write a ONE-LINE structural skeleton that describes ONLY the abstract mechanism or pattern — no domain-specific vocabulary, no proper nouns, no AI/agent/memory/consciousness terminology. Describe the shape, dynamic, or structural relationship in the most general terms possible.

Format: exactly one line per item, starting with the item name in quotes exactly as given, then |||, then the skeleton.

Items:
"""
        for n in batch:
            summary = n.get("summary", n["id"])[:250]
            prompt += f'\n- "{n["id"]}": {summary}'

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=4000,
            )

            content = response.choices[0].message.content.strip()
            for line in content.split("\n"):
                if "|||" in line:
                    parts = line.split("|||", 1)
                    name_part = parts[0].strip().strip("-").strip().strip('"').strip()
                    skeleton = parts[1].strip()
                    for n in batch:
                        if n["id"] == name_part or n["id"].lower() == name_part.lower():
                            cache[n["id"]] = skeleton
                            break
                    else:
                        for n in batch:
                            if name_part.lower() in n["id"].lower() or n["id"].lower() in name_part.lower():
                                if n["id"] not in cache:
                                    cache[n["id"]] = skeleton
                                    break
        except Exception as e:
            print(f"  ERROR on batch {batch_num}: {e}")
            continue

        if batch_num % 5 == 0:
            SKELETON_CACHE.write_text(json.dumps(cache, indent=2))

    SKELETON_CACHE.write_text(json.dumps(cache, indent=2))
    print(f"Cache updated: {len(cache)} skeletons total")
    return cache


def embed_skeletons(nodes, skeletons, client):
    """Embed skeleton texts, using and updating cache."""
    cache = {}
    if SKELETON_EMBEDDING_CACHE.exists():
        cache = json.loads(SKELETON_EMBEDDING_CACHE.read_text())

    valid_nodes = [n for n in nodes if n["id"] in skeletons]
    needs_embedding = [n for n in valid_nodes if n["id"] not in cache]

    if not needs_embedding:
        print(f"All {len(valid_nodes)} skeleton embeddings cached")
        return cache

    print(f"Embedding {len(needs_embedding)} skeletons ({len(cache)} cached)...")
    texts = [skeletons[n["id"]] for n in needs_embedding]

    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(texts) - 1) // batch_size + 1
        print(f"  Embedding batch {batch_num}/{total_batches} ({len(batch)} skeletons)...")
        response = client.embeddings.create(model="text-embedding-3-large", input=batch)
        for j, d in enumerate(response.data):
            node_id = needs_embedding[i + j]["id"]
            cache[node_id] = d.embedding

    SKELETON_EMBEDDING_CACHE.write_text(json.dumps(cache))
    print(f"Skeleton embedding cache: {len(cache)} total")
    return cache


def compute_structural_edges(nodes, raw_embeddings, skeleton_embeddings, skeletons):
    """Find pairs where skeleton similarity >> raw similarity (structural isomorphisms)."""
    valid = [n for n in nodes if n["id"] in skeleton_embeddings and n["id"] in raw_embeddings]
    print(f"Computing deltas for {len(valid)} nodes with both embeddings...")

    raw_mat = np.array([raw_embeddings[n["id"]] for n in valid])
    skel_mat = np.array([skeleton_embeddings[n["id"]] for n in valid])

    raw_norms = np.linalg.norm(raw_mat, axis=1, keepdims=True)
    raw_norms[raw_norms == 0] = 1
    raw_normed = raw_mat / raw_norms

    skel_norms = np.linalg.norm(skel_mat, axis=1, keepdims=True)
    skel_norms[skel_norms == 0] = 1
    skel_normed = skel_mat / skel_norms

    print("  Computing raw cosine matrix...")
    raw_sim = raw_normed @ raw_normed.T
    print("  Computing skeleton cosine matrix...")
    skel_sim = skel_normed @ skel_normed.T

    n = len(valid)
    structural_edges = []
    origin_map = {}
    for node in valid:
        o = node.get("origin", "?")
        if isinstance(o, list):
            o = tuple(sorted(o))
        origin_map[node["id"]] = o

    print(f"  Scanning {n*(n-1)//2} pairs (delta>{DELTA_THRESHOLD}, skel_sim>{SKELETON_SIM_FLOOR})...")

    for i in range(n):
        for j in range(i + 1, n):
            s_sim = float(skel_sim[i, j])
            if s_sim < SKELETON_SIM_FLOOR:
                continue

            r_sim = float(raw_sim[i, j])
            delta = s_sim - r_sim
            if delta < DELTA_THRESHOLD:
                continue

            id_i = valid[i]["id"].lower()
            id_j = valid[j]["id"].lower()
            if id_i in id_j or id_j in id_i:
                continue

            src_o = origin_map[valid[i]["id"]]
            tgt_o = origin_map[valid[j]["id"]]

            structural_edges.append({
                "source": valid[i]["id"],
                "target": valid[j]["id"],
                "predicate": "structural_isomorphism",
                "weight": round(delta, 4),
                "skeleton_sim": round(s_sim, 4),
                "raw_sim": round(r_sim, 4),
                "edge_type": "computed",
                "cross_agent": src_o != tgt_o,
            })

    structural_edges.sort(key=lambda x: x["weight"], reverse=True)
    return structural_edges, valid, skeletons


def main():
    with open(GRAPH_PATH) as f:
        graph = json.load(f)
    nodes = graph["nodes"]
    print(f"Loaded {len(nodes)} nodes from graph")

    nodes_with_summary = [n for n in nodes if n.get("summary")]
    print(f"Nodes with summaries: {len(nodes_with_summary)}")

    client = get_openai_client()

    # Step 1: Generate skeletons
    skeletons = generate_skeletons(nodes_with_summary, client)
    covered = sum(1 for n in nodes_with_summary if n["id"] in skeletons)
    print(f"Skeleton coverage: {covered}/{len(nodes_with_summary)}")

    # Step 2: Embed skeletons
    skel_embeddings = embed_skeletons(nodes_with_summary, skeletons, client)

    # Step 3: Load raw embeddings
    if not EMBEDDING_CACHE.exists():
        print("Error: all-embeddings.json not found — run recompute-cosine.py first")
        sys.exit(1)
    raw_embeddings = json.loads(EMBEDDING_CACHE.read_text())
    print(f"Raw embeddings loaded: {len(raw_embeddings)}")

    # Step 4: Compute structural edges
    edges, valid_nodes, skel_texts = compute_structural_edges(
        nodes_with_summary, raw_embeddings, skel_embeddings, skeletons
    )

    print(f"\nStructural isomorphism edges found: {len(edges)}")
    if edges:
        cross = sum(1 for e in edges if e["cross_agent"])
        print(f"  Cross-agent: {cross}, Intra-agent: {len(edges) - cross}")
        deltas = [e["weight"] for e in edges]
        print(f"  Delta range: {min(deltas):.3f} - {max(deltas):.3f}, mean: {np.mean(deltas):.3f}")

        print("\nTop 15 structural isomorphisms:")
        for e in edges[:15]:
            print(f"  [delta +{e['weight']:.3f}] {e['source']}")
            print(f"       ↔ {e['target']}")
            skel_a = skeletons.get(e["source"], "?")[:80]
            skel_b = skeletons.get(e["target"], "?")[:80]
            print(f"       A: {skel_a}")
            print(f"       B: {skel_b}")
            print()

    # Save structural pairs
    STRUCTURAL_PAIRS_PATH.write_text(json.dumps(edges[:500], indent=2))
    print(f"Top 500 pairs saved to {STRUCTURAL_PAIRS_PATH}")

    # Step 5: Add to graph
    non_struct = [e for e in graph["edges"] if e.get("predicate") != "structural_isomorphism"]
    graph["edges"] = non_struct + edges
    print(f"Graph edges: {len(non_struct)} existing + {len(edges)} structural = {len(graph['edges'])} total")

    with open(GRAPH_PATH, "w") as f:
        json.dump(graph, f, separators=(",", ":"))
    print(f"Written to {GRAPH_PATH}")


if __name__ == "__main__":
    main()
