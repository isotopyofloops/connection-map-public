#!/usr/bin/env python3
"""Pre-compute force-directed layout positions for graph-data.json.

Stores x/y on each node so the explorer can skip the expensive cose computation.
Uses networkx spring_layout (Fruchterman-Reingold) which produces similar results
to Cytoscape's cose algorithm.
"""
import json
import networkx as nx

with open("graph-data.json") as f:
    data = json.load(f)

G = nx.Graph()
for node in data["nodes"]:
    G.add_node(node["id"])

# Only use curated+structural edges for layout (matching explorer.html which skips cosine_similarity)
for edge in data["edges"]:
    if edge.get("predicate") == "cosine_similarity":
        continue
    if edge["source"] in G and edge["target"] in G:
        G.add_edge(edge["source"], edge["target"])

print(f"Layout: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

pos = nx.spring_layout(G, k=0.15, iterations=200, seed=42, scale=500)

for node in data["nodes"]:
    nid = node["id"]
    if nid in pos:
        node["x"] = round(float(pos[nid][0]), 2)
        node["y"] = round(float(pos[nid][1]), 2)
    else:
        node["x"] = 0.0
        node["y"] = 0.0

with open("graph-data.json", "w") as f:
    json.dump(data, f, separators=(",", ":"))

print("Done — positions written to graph-data.json")
