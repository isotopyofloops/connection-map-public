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

# Use ALL edges for layout (cosine pulls similar nodes together visually)
for edge in data["edges"]:
    w = edge.get("weight", 0.5)
    if edge["source"] in G and edge["target"] in G:
        G.add_edge(edge["source"], edge["target"], weight=w)

print(f"Layout: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

pos = nx.spring_layout(G, k=0.08, iterations=300, seed=42, scale=500, weight="weight")

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
