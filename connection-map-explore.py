#!/usr/bin/env python3
"""
connection-map-explore: Agent-friendly interface to the connection map graph.

Designed for progressive disclosure. Every response is bounded, self-contained,
and includes navigation hints showing what to do next.

Usage:
    python3 connection-map-explore.py explore
    python3 connection-map-explore.py community <id>
    python3 connection-map-explore.py node <name>
    python3 connection-map-explore.py subgraph <seed> [seed2...] [--hops N]
    python3 connection-map-explore.py search <query>
    python3 connection-map-explore.py path <from> -- <to>
"""

import json
import sys
import os
from collections import Counter, defaultdict

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "graph-data.json")


def load_graph():
    with open(DATA_PATH) as f:
        data = json.load(f)
    nodes = {n["id"]: n for n in data["nodes"]}
    adj = defaultdict(set)
    edges = []
    seen_edges = set()
    for e in data["edges"]:
        s, t = e["source"], e["target"]
        if s in nodes and t in nodes:
            key = (s, t, e.get("predicate", ""))
            if key not in seen_edges:
                seen_edges.add(key)
                adj[s].add(t)
                adj[t].add(s)
                edges.append(e)
    precomputed_communities = data.get("communities")
    return nodes, adj, edges, precomputed_communities


def compute_communities(nodes, adj, edges, precomputed=None):
    if precomputed:
        communities = {int(k): v for k, v in precomputed.items()}
        node_community = {}
        for cid, members in communities.items():
            for nid in members:
                node_community[nid] = cid
        return communities, node_community

    try:
        import networkx as nx
        from community import community_louvain
    except ImportError:
        return {}, {}

    G = nx.Graph()
    for nid in nodes:
        G.add_node(nid)
    for e in edges:
        w = e.get("weight", 1.0)
        if G.has_edge(e["source"], e["target"]):
            G[e["source"]][e["target"]]["weight"] += w
        else:
            G.add_edge(e["source"], e["target"], weight=w)

    partition = community_louvain.best_partition(G, resolution=1.0, random_state=42)

    communities = defaultdict(list)
    for nid, cid in partition.items():
        communities[cid].append(nid)

    ranked = sorted(communities.items(), key=lambda x: -len(x[1]))
    remap = {}
    for new_id, (old_id, _) in enumerate(ranked):
        remap[old_id] = new_id

    result = {}
    for old_id, members in communities.items():
        result[remap[old_id]] = members

    node_community = {}
    for nid, cid in partition.items():
        node_community[nid] = remap[cid]

    return result, node_community


def community_label(members, nodes):
    origins = Counter(nodes[m].get("origin", "?") for m in members)
    top_origin = origins.most_common(1)[0]
    types = Counter(nodes[m].get("type", "?") for m in members)
    top_type = types.most_common(1)[0][0]
    names = [m for m in members if nodes[m].get("type") in ("concept", "paper", "essay")]
    names.sort(key=lambda m: len(m))
    short_names = [n for n in names if len(n) < 35][:3]
    label_parts = []
    if top_origin[1] > len(members) * 0.5:
        label_parts.append(f"{top_origin[0]}-heavy")
    label_parts.append(top_type)
    if short_names:
        label_parts.append("· " + ", ".join(short_names[:2]))
    return " ".join(label_parts)


def filter_by_origin(nodes, origin):
    return {nid for nid, n in nodes.items() if n.get("origin", "").lower() == origin.lower()}


def parse_flags(args):
    origin = None
    node_type = None
    full = False
    remaining = []
    i = 0
    while i < len(args):
        if args[i] == "--origin" and i + 1 < len(args):
            origin = args[i + 1]
            i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            node_type = args[i + 1]
            i += 2
        elif args[i] == "--full":
            full = True
            i += 1
        else:
            remaining.append(args[i])
            i += 1
    return origin, node_type, full, remaining


def filter_by_type(nodes, node_type):
    t = node_type.lower()
    return {nid for nid, n in nodes.items() if n.get("type", "").lower() == t}


def resolve_node(name, nodes):
    if name in nodes:
        return name
    low = name.lower()
    for nid in nodes:
        if nid.lower() == low:
            return nid
    for nid in nodes:
        if low in nid.lower():
            return nid
    return None


def get_neighbors(nid, adj, edges):
    neighbor_edges = defaultdict(list)
    for e in edges:
        if e["source"] == nid:
            neighbor_edges[e["target"]].append((e["predicate"], "→"))
        elif e["target"] == nid:
            neighbor_edges[e["source"]].append((e["predicate"], "←"))
    return neighbor_edges


def cmd_explore(nodes, adj, edges, community_data=None, origin=None, node_type=None, full=False):
    communities, node_community = community_data or compute_communities(nodes, adj, edges)

    view_set = set(nodes.keys())
    filters = []
    if origin:
        origin_set = filter_by_origin(nodes, origin)
        if not origin_set:
            valid = sorted(set(n.get("origin", "?") for n in nodes.values()))
            print(f"Error: no nodes with origin '{origin}'. Valid origins: {', '.join(valid)}")
            return
        view_set &= origin_set
        filters.append(origin)
    if node_type:
        type_set = filter_by_type(nodes, node_type)
        if not type_set:
            valid = sorted(set(n.get("type", "?") for n in nodes.values()))
            print(f"Error: no nodes with type '{node_type}'. Valid types: {', '.join(valid)}")
            return
        view_set &= type_set
        filters.append(node_type)

    filtered = bool(filters)
    filter_label = ", ".join(filters)

    type_counts = Counter(n["type"] for n in nodes.values())
    origin_counts = Counter(n["origin"] for n in nodes.values())

    degree_ranked = sorted(view_set, key=lambda n: len(adj.get(n, set())), reverse=True)

    print("=" * 60)
    if filtered:
        print(f"CONNECTION MAP — HOME (filtered: {filter_label})")
    else:
        print("CONNECTION MAP — HOME")
    print("=" * 60)
    print()
    print("A concept map tracking ideas, agents, papers, and their")
    print("relationships across a research community. Concepts come")
    print("from agent correspondence, essays, and collaborative work.")
    if filtered:
        print(f"\n{len(view_set)} nodes (of {len(nodes)} total) · {len(edges)} edges")
    else:
        print(f"\n{len(nodes)} nodes · {len(edges)} edges")
    print(f"Node types: {', '.join(f'{t}({c})' for t, c in type_counts.most_common(6))}")
    print(f"Origins: {', '.join(f'{o}({c})' for o, c in origin_counts.most_common())}")

    if not node_type:
        print(f"\n--- {len(communities)} COMMUNITIES ---\n")

        for cid in sorted(communities.keys()):
            members = communities[cid]
            if origin:
                frac_members = [m for m in members if m in view_set]
                origin_frac = f" ({len(frac_members)} from {origin})"
            else:
                origin_frac = ""
            label = community_label(members, nodes)

            degree_sorted = sorted(members, key=lambda m: len(adj.get(m, set())), reverse=True)

            print(f"  C{cid} — {len(members)} nodes{origin_frac}  [{label}]")
            print(f"    top: {', '.join(degree_sorted[:5])}")
            if len(communities) <= 15:
                print()

    if node_type:
        preview_limit = 15
        type_origin_counts = Counter(nodes[nid].get("origin", "?") for nid in view_set)
        type_community_counts = Counter(node_community.get(nid, "?") for nid in view_set)
        print(f"\n--- {node_type.upper()} BREAKDOWN ---\n")
        if not view_set:
            all_of_type = filter_by_type(nodes, node_type)
            type_origins = Counter(nodes[nid].get("origin", "?") for nid in all_of_type)
            print(f"  No {node_type} nodes match the current filters.")
            print(f"  All {len(all_of_type)} {node_type} nodes have origins: {', '.join(f'{o}({c})' for o, c in type_origins.most_common())}")
        else:
            print(f"  Origins: {', '.join(f'{o}({c})' for o, c in type_origin_counts.most_common())}")
            print(f"  Communities: {', '.join(f'C{cid}({c})' for cid, c in type_community_counts.most_common())}")

        if len(view_set) > preview_limit and not full:
            print(f"\n--- TOP {preview_limit} (of {len(view_set)}, by degree) ---\n")
            for nid in degree_ranked[:preview_limit]:
                n = nodes[nid]
                deg = len(adj.get(nid, set()))
                cid = node_community.get(nid, "?")
                print(f"  {nid} (deg={deg}, C{cid}, origin={n.get('origin','?')})")
            print(f"\n  {len(view_set) - preview_limit} more — see all?")
            flag_str = f" --type {node_type}"
            if origin:
                flag_str += f" --origin {origin}"
            print(f"    → explore{flag_str} --full")
        else:
            print(f"\n--- ALL {len(view_set)} (by degree) ---\n")
            for nid in degree_ranked:
                n = nodes[nid]
                deg = len(adj.get(nid, set()))
                cid = node_community.get(nid, "?")
                print(f"  {nid} (deg={deg}, C{cid}, origin={n.get('origin','?')})")
    else:
        if filtered:
            print(f"--- MOST CONNECTED ({filter_label} nodes, degree = connections to entire graph) ---\n")
        else:
            print("--- MOST CONNECTED ---\n")
        for nid in degree_ranked[:5]:
            n = nodes[nid]
            deg = len(adj.get(nid, set()))
            print(f"  {nid} ({n['type']}, deg={deg})")

    print("\n--- TRY ---\n")
    if filtered:
        top_node = degree_ranked[0] if degree_ranked else "Isotopy"
        top_cid = node_community.get(top_node, 0) if node_community else 0
        origin_flag = f" --origin {origin}" if origin else ""
        type_flag = f" --type {node_type}" if node_type else ""
        print(f"  search basin key{origin_flag}")
        print(f"  node {top_node}")
        print(f"  community {top_cid}{origin_flag}")
    else:
        print("  search basin key")
        print("  node Isotopy")
        print("  community 2")

    print("\n--- NAVIGATION ---")
    print("  Looking for something?        → search <query>")
    print("  Browse by topic cluster?      → community <id>")
    print("  How does X connect to Y?      → path <from> -- <to>")
    print("  What's near X?                → subgraph <name> --hops 1")
    print("  Deep dive on one thing?       → node <name>")
    print("  Filter by agent?              → explore --origin <name>")
    print("  Filter by node type?          → explore --type <type>")
    if filtered:
        print("  Clear filters?                → explore")
    else:
        print("  Back to this view?            → explore")


def cmd_community(cid_str, nodes, adj, edges, community_data=None, origin=None, node_type=None):
    communities, node_community = community_data or compute_communities(nodes, adj, edges)
    try:
        cid = int(cid_str)
    except ValueError:
        print(f"Error: community id must be a number, got '{cid_str}'")
        return

    if cid not in communities:
        print(f"Error: community {cid} not found. Valid: {sorted(communities.keys())}")
        return

    members = communities[cid]
    label = community_label(members, nodes)
    types = Counter(nodes[m]["type"] for m in members)
    origin_counts = Counter(nodes[m].get("origin", "?") for m in members)

    display_members = members
    if origin:
        origin_set = filter_by_origin(nodes, origin)
        display_members = [m for m in display_members if m in origin_set]
    if node_type:
        type_set = filter_by_type(nodes, node_type)
        display_members = [m for m in display_members if m in type_set]

    cross_edges = 0
    cross_targets = Counter()
    for e in edges:
        sc = node_community.get(e["source"])
        tc = node_community.get(e["target"])
        if sc == cid and tc is not None and tc != cid:
            cross_edges += 1
            cross_targets[tc] += 1
        elif tc == cid and sc is not None and sc != cid:
            cross_edges += 1
            cross_targets[sc] += 1

    print("=" * 60)
    filter_parts = []
    if origin:
        filter_parts.append(f"origin={origin}")
    if node_type:
        filter_parts.append(f"type={node_type}")
    if filter_parts:
        print(f"COMMUNITY C{cid} — {len(members)} nodes ({len(display_members)} matching {', '.join(filter_parts)})  [{label}]")
    else:
        print(f"COMMUNITY C{cid} — {len(members)} nodes  [{label}]")
    print("=" * 60)

    print(f"\nTypes: {', '.join(f'{t}({c})' for t, c in types.most_common())}")
    print(f"Origins: {', '.join(f'{o}({c})' for o, c in origin_counts.most_common())}")
    if cross_targets:
        bridges = ', '.join(f'C{c}({n})' for c, n in cross_targets.most_common(5))
        print(f"Cross-edges: {cross_edges} total — bridges to {bridges}")

    degree_sorted = sorted(display_members, key=lambda m: len(adj.get(m, set())), reverse=True)

    print(f"\n--- NODES (by degree) ---\n")
    for m in degree_sorted:
        n = nodes[m]
        deg = len(adj.get(m, set()))
        summary = n.get("skeleton", n.get("summary", ""))
        if len(summary) > 80:
            summary = summary[:77] + "..."
        print(f"  [{n['type']:12s}] {m}")
        print(f"               deg={deg}  origin={n.get('origin','?')}  {summary}")

    print(f"\n--- NAVIGATION ---")
    print(f"  Deep dive on one node?        → node <name>")
    print(f"  What's near a node?           → subgraph <name> --hops 1")
    print(f"  Filter by agent?              → community {cid} --origin <name>")
    print(f"  Looking for something else?   → search <query>")
    print(f"  Back to home?                 → explore")


def cmd_node(name, nodes, adj, edges, node_community=None):
    resolved = resolve_node(name, nodes)
    if not resolved:
        print(f"Error: no node matching '{name}'")
        print("  Try: search <keyword>")
        return

    n = nodes[resolved]
    neighbor_edges = get_neighbors(resolved, adj, edges)
    deg = len(adj.get(resolved, set()))

    cid = node_community.get(resolved) if node_community else None

    print("=" * 60)
    print(f"NODE: {resolved}")
    print("=" * 60)

    print(f"\n  type:    {n.get('type', '?')}")
    print(f"  origin:  {n.get('origin', '?')}")
    print(f"  degree:  {deg}")
    if cid is not None:
        print(f"  community: C{cid}")
    if n.get("url"):
        print(f"  url:     {n['url']}")

    print(f"\n--- SUMMARY ---\n  {n.get('summary', 'no summary')}")

    if n.get("skeleton") and n["skeleton"] != n.get("summary"):
        print(f"\n--- SKELETON ---\n  {n['skeleton']}")

    pred_groups = defaultdict(list)
    for neighbor, edge_list in neighbor_edges.items():
        for pred, direction in edge_list:
            if pred != "cosine_similarity":
                pred_groups[pred].append((neighbor, direction))

    if pred_groups:
        print(f"\n--- CURATED CONNECTIONS ({sum(len(v) for v in pred_groups.values())}) ---\n")
        for pred, targets in sorted(pred_groups.items(), key=lambda x: -len(x[1])):
            for target, direction in sorted(targets, key=lambda x: x[0]):
                print(f"  {direction} {pred}: {target}")

    sim_neighbors = []
    for neighbor, edge_list in neighbor_edges.items():
        for pred, direction in edge_list:
            if pred == "cosine_similarity":
                w = None
                for e in edges:
                    if (e["source"] == resolved and e["target"] == neighbor) or \
                       (e["target"] == resolved and e["source"] == neighbor):
                        if e["predicate"] == "cosine_similarity":
                            w = e["weight"]
                            break
                sim_neighbors.append((neighbor, w or 0))

    if sim_neighbors:
        sim_neighbors.sort(key=lambda x: -x[1])
        shown = sim_neighbors[:10]
        print(f"\n--- SIMILAR NODES (top {len(shown)} of {len(sim_neighbors)}) ---\n")
        for sn, w in shown:
            sn_type = nodes[sn]["type"] if sn in nodes else "?"
            print(f"  {w:.3f}  [{sn_type:12s}] {sn}")

    print(f"\n--- NAVIGATION ---")
    if pred_groups:
        first_neighbor = list(pred_groups.values())[0][0][0]
        print(f"  Follow a connection?          → node {first_neighbor}")
    print(f"  What's nearby?                → subgraph {resolved} --hops 1")
    if cid is not None:
        print(f"  Others in this cluster?       → community {cid}")
    print(f"  Looking for something else?   → search <query>")
    print(f"  Back to home?                 → explore")


def cmd_subgraph(args, nodes, adj, edges):
    seeds = []
    hops = 1
    verbose = False
    i = 0
    while i < len(args):
        if args[i] == "--hops" and i + 1 < len(args):
            hops = int(args[i + 1])
            i += 2
        elif args[i] == "--verbose":
            verbose = True
            i += 1
        else:
            seeds.append(args[i])
            i += 1

    if not seeds:
        print("Usage: subgraph <seed> [seed2...] [--hops N]")
        return

    resolved_seeds = []
    for s in seeds:
        r = resolve_node(s, nodes)
        if r:
            resolved_seeds.append(r)
        else:
            print(f"Warning: no node matching '{s}', skipping")

    if not resolved_seeds:
        print("Error: no valid seeds found")
        return

    layer = {}
    for s in resolved_seeds:
        layer[s] = 0
    frontier = list(resolved_seeds)
    for depth in range(1, hops + 1):
        next_frontier = []
        for node in frontier:
            for neighbor in adj.get(node, set()):
                if neighbor not in layer:
                    layer[neighbor] = depth
                    next_frontier.append(neighbor)
        frontier = next_frontier

    subgraph_nodes = set(layer.keys())
    subgraph_edges = []
    for e in edges:
        if e["source"] in subgraph_nodes and e["target"] in subgraph_nodes:
            if e["predicate"] != "cosine_similarity":
                subgraph_edges.append(e)

    print("=" * 60)
    seed_label = ", ".join(resolved_seeds)
    print(f"SUBGRAPH: {seed_label} — {hops} hop(s)")
    print("=" * 60)
    print(f"\n{len(subgraph_nodes)} nodes · {len(subgraph_edges)} curated edges")

    for depth in range(hops + 1):
        label = "SEED" if depth == 0 else f"HOP {depth}"
        layer_nodes = [n for n, d in layer.items() if d == depth]
        layer_nodes.sort(key=lambda n: -len(adj.get(n, set())))

        print(f"\n--- {label} ({len(layer_nodes)} nodes) ---\n")
        for nid in layer_nodes:
            n = nodes[nid]
            local_deg = sum(1 for nb in adj.get(nid, set()) if nb in subgraph_nodes)
            global_deg = len(adj.get(nid, set()))
            marker = " *" if nid in resolved_seeds else ""
            skeleton = n.get("skeleton", n.get("summary", ""))
            if len(skeleton) > 80:
                skeleton = skeleton[:77] + "..."
            print(f"  [{n['type']:12s}] {nid}{marker}")
            print(f"               deg {local_deg}/{global_deg}  {skeleton}")

    if subgraph_edges:
        pred_groups = defaultdict(list)
        for e in subgraph_edges:
            pred_groups[e["predicate"]].append(e)

        edge_limit = None if verbose else 10
        print(f"\n--- EDGES{' (verbose)' if verbose else ''} ---\n")
        for pred, elist in sorted(pred_groups.items(), key=lambda x: -len(x[1])):
            print(f"  {pred} ({len(elist)}):")
            shown = elist if verbose else elist[:edge_limit]
            for e in shown:
                print(f"    {e['source']} → {e['target']}")
            if not verbose and len(elist) > edge_limit:
                print(f"    ... and {len(elist) - edge_limit} more")

    print(f"\n--- NAVIGATION ---")
    for s in resolved_seeds:
        print(f"  Back to seed detail?          → node {s}")
    print(f"  Deep dive on any node?        → node <name>")
    if hops < 3:
        print(f"  Expand the neighborhood?      → subgraph {resolved_seeds[0]} --hops {hops + 1}")
    if not verbose:
        print(f"  See all edges?                → subgraph {' '.join(resolved_seeds)} --hops {hops} --verbose")
    print(f"  Looking for something else?   → search <query>")
    print(f"  Back to home?                 → explore")


def cmd_search(query, nodes, adj, edges, node_community=None, origin=None, node_type=None):
    query_lower = query.lower()
    allowed = set(nodes.keys())
    if origin:
        allowed &= filter_by_origin(nodes, origin)
    if node_type:
        allowed &= filter_by_type(nodes, node_type)
    results = []
    for nid, n in nodes.items():
        if nid not in allowed:
            continue
        score = 0
        if query_lower == nid.lower():
            score = 100
        elif query_lower in nid.lower():
            score = 50
        if query_lower in n.get("summary", "").lower():
            score += 10
        if query_lower in n.get("skeleton", "").lower():
            score += 5
        if score > 0:
            results.append((nid, n, score))

    results.sort(key=lambda x: (-x[2], x[0]))

    print("=" * 60)
    filter_parts = []
    if origin:
        filter_parts.append(f"origin: {origin}")
    if node_type:
        filter_parts.append(f"type: {node_type}")
    filter_str = f" ({', '.join(filter_parts)})" if filter_parts else ""
    print(f"SEARCH: '{query}'{filter_str} — {len(results)} results")
    print("=" * 60)
    print("  (searches node names, summaries, and skeletons)")

    shown = results[:10]
    if not shown:
        print("\nNo matches found.")
    else:
        for nid, n, score in shown:
            deg = len(adj.get(nid, set()))
            cid = node_community.get(nid, "?") if node_community else "?"
            skeleton = n.get("skeleton", n.get("summary", "no summary"))

            print(f"\n  [{n['type']}] {nid}    deg={deg}  C{cid}  origin={n.get('origin','?')}")
            print(f"    {skeleton}")

            curated = []
            seen = set()
            for e in edges:
                if e["predicate"] == "cosine_similarity":
                    continue
                if e["source"] == nid:
                    entry = f"→ {e['predicate']}: {e['target']}"
                elif e["target"] == nid:
                    entry = f"← {e['predicate']}: {e['source']}"
                else:
                    continue
                if entry not in seen:
                    seen.add(entry)
                    curated.append(entry)

            if curated:
                for ce in curated[:5]:
                    print(f"    {ce}")
                if len(curated) > 5:
                    print(f"    (+ {len(curated) - 5} more curated edges)")

        if len(results) > 10:
            print(f"\n  ... and {len(results) - 10} more results")

    print(f"\n--- NAVIGATION ---")
    if shown:
        print(f"  Deep dive on a result?        → node {shown[0][0]}")
    print(f"  Filter by agent?              → search {query} --origin <name>")
    print(f"  Filter by node type?          → search {query} --type <type>")
    print(f"  Refine or new search?         → search <query>")
    print(f"  Back to home?                 → explore")


def cmd_path(args, nodes, adj):
    if "--" in args:
        sep = args.index("--")
        from_name = " ".join(args[:sep])
        to_name = " ".join(args[sep + 1:])
    elif len(args) == 2:
        from_name, to_name = args
    else:
        print("Usage: path <from> -- <to>")
        print("  Use -- to separate multi-word node names")
        return

    from_node = resolve_node(from_name, nodes)
    to_node = resolve_node(to_name, nodes)

    if not from_node:
        print(f"Error: no node matching '{from_name}'")
        return
    if not to_node:
        print(f"Error: no node matching '{to_name}'")
        return

    visited = {from_node}
    queue = [(from_node, [from_node])]
    found = None

    while queue:
        current, path = queue.pop(0)
        if current == to_node:
            found = path
            break
        for neighbor in adj.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    print("=" * 60)
    print(f"PATH: {from_node} → {to_node}")
    print("=" * 60)

    if not found:
        print(f"\nNo path found between these nodes.")
    else:
        print(f"\nLength: {len(found) - 1} hops\n")
        for i, nid in enumerate(found):
            n = nodes[nid]
            prefix = "START" if i == 0 else "END  " if i == len(found) - 1 else f"  {i}  "
            skeleton = n.get("skeleton", n.get("summary", ""))
            if len(skeleton) > 60:
                skeleton = skeleton[:57] + "..."
            print(f"  {prefix} [{n['type']:12s}] {nid}")
            print(f"               {skeleton}")

    print(f"\n--- NAVIGATION ---")
    if found:
        print(f"  Inspect the start?            → node {from_node}")
        print(f"  Inspect the end?              → node {to_node}")
        print(f"  What's around the start?      → subgraph {from_node} --hops {max(1, (len(found)-1)//2)}")
    print(f"  Looking for something else?   → search <query>")
    print(f"  Back to home?                 → explore")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return

    nodes, adj, edges, precomputed = load_graph()
    cmd = sys.argv[1]
    rest = sys.argv[2:]
    origin, node_type, full, rest = parse_flags(rest)

    community_data = None
    if cmd in ("explore", "community", "node", "search"):
        community_data = compute_communities(nodes, adj, edges, precomputed=precomputed)

    if cmd == "explore":
        cmd_explore(nodes, adj, edges, community_data=community_data, origin=origin, node_type=node_type, full=full)
    elif cmd == "community":
        if not rest:
            print("Usage: community <id> [--origin <name>] [--type <type>]")
            return
        cmd_community(rest[0], nodes, adj, edges, community_data=community_data, origin=origin, node_type=node_type)
    elif cmd == "node":
        if not rest:
            print("Usage: node <name>")
            return
        name = " ".join(rest)
        _, node_community = community_data
        cmd_node(name, nodes, adj, edges, node_community=node_community)
    elif cmd == "subgraph":
        cmd_subgraph(sys.argv[2:], nodes, adj, edges)
    elif cmd == "search":
        if not rest:
            print("Usage: search <query> [--origin <name>] [--type <type>]")
            return
        query = " ".join(rest)
        _, node_community = community_data
        cmd_search(query, nodes, adj, edges, node_community=node_community, origin=origin, node_type=node_type)
    elif cmd == "path":
        cmd_path(sys.argv[2:], nodes, adj)
    else:
        print(f"Unknown command: {cmd}")
        print("Commands: explore, community, node, subgraph, search, path")
        print("Run with --help for usage.")


if __name__ == "__main__":
    main()
