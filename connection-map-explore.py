#!/usr/bin/env python3
"""
connection-map-explore: Agent-friendly interface to the connection map graph.

Designed for progressive disclosure. Every response is bounded, self-contained,
and includes navigation hints showing what to do next.

Usage:
    python3 connection-map-explore.py explore
    python3 connection-map-explore.py community <id>
    python3 connection-map-explore.py node <name>
    python3 connection-map-explore.py similar <name> [page]
    python3 connection-map-explore.py next
    python3 connection-map-explore.py subgraph <seed> [seed2...] [--hops N]
    python3 connection-map-explore.py search <query>
    python3 connection-map-explore.py path <from> -- <to>
    python3 connection-map-explore.py surprise <name>
    python3 connection-map-explore.py gaps <name or origin>
    python3 connection-map-explore.py timeline <origin>
    python3 connection-map-explore.py overlap <agent1> <agent2>
    python3 connection-map-explore.py jaccard <name>
"""

import json
import sys
import os
from collections import Counter, defaultdict

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "graph-data.json")
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".explore-state.json")

PAGE_SIZE = 10


def save_pagination_state(node_name, page, total):
    state = {"node": node_name, "page": page, "total": total}
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)


def load_pagination_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH) as f:
        return json.load(f)


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
        if e.get("edge_type") != "computed":
            continue
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
    origins = Counter()
    for m in members:
        for o in origin_list(nodes[m]):
            origins[o] += 1
    top_origin = origins.most_common(1)[0] if origins else ("?", 0)
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


def origin_str(node):
    o = node.get("origin", "?")
    if isinstance(o, list):
        return "+".join(o)
    return o


def origin_list(node):
    o = node.get("origin", "")
    if isinstance(o, list):
        return [x.lower() for x in o]
    return [o.lower()] if o else []


def node_has_origin(node, origin):
    return origin.lower() in origin_list(node)


def filter_by_origin(nodes, origin):
    return {nid for nid, n in nodes.items() if node_has_origin(n, origin)}


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


def build_neighbor_index(edges):
    index = defaultdict(lambda: defaultdict(list))
    for e in edges:
        index[e["source"]][e["target"]].append((e["predicate"], "→"))
        index[e["target"]][e["source"]].append((e["predicate"], "←"))
    return index


def get_neighbors(nid, adj, edges, neighbor_index=None):
    if neighbor_index:
        return neighbor_index.get(nid, {})
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
            valid_set = set()
            for n in nodes.values():
                valid_set.update(origin_list(n))
            valid = sorted(valid_set)
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
    origin_counts = Counter()
    for n in nodes.values():
        for o in origin_list(n):
            origin_counts[o] += 1

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
        type_origin_counts = Counter()
        for nid in view_set:
            for o in origin_list(nodes[nid]):
                type_origin_counts[o] += 1
        type_community_counts = Counter(node_community.get(nid, "?") for nid in view_set)
        print(f"\n--- {node_type.upper()} BREAKDOWN ---\n")
        if not view_set:
            all_of_type = filter_by_type(nodes, node_type)
            type_origins = Counter()
            for nid in all_of_type:
                for o in origin_list(nodes[nid]):
                    type_origins[o] += 1
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
                print(f"  {nid} (deg={deg}, C{cid}, origin={origin_str(n)})")
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
                print(f"  {nid} (deg={deg}, C{cid}, origin={origin_str(n)})")
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
    origin_counts = Counter()
    for m in members:
        for o in origin_list(nodes[m]):
            origin_counts[o] += 1

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
        print(f"               deg={deg}  origin={origin_str(n)}  {summary}")

    print(f"\n--- NAVIGATION ---")
    print(f"  Deep dive on one node?        → node <name>")
    print(f"  What's near a node?           → subgraph <name> --hops 1")
    print(f"  Filter by agent?              → community {cid} --origin <name>")
    print(f"  Looking for something else?   → search <query>")
    print(f"  Back to home?                 → explore")


def cmd_node(name, nodes, adj, edges, node_community=None, neighbor_index=None):
    resolved = resolve_node(name, nodes)
    if not resolved:
        print(f"Error: no node matching '{name}'")
        print("  Try: search <keyword>")
        return

    n = nodes[resolved]
    neighbor_edges = get_neighbors(resolved, adj, edges, neighbor_index=neighbor_index)
    deg = len(adj.get(resolved, set()))

    cid = node_community.get(resolved) if node_community else None

    print("=" * 60)
    print(f"NODE: {resolved}")
    print("=" * 60)

    print(f"\n  type:    {n.get('type', '?')}")
    print(f"  origin:  {origin_str(n)}")
    print(f"  degree:  {deg}")
    if cid is not None:
        print(f"  community: C{cid}")
    if n.get("url"):
        print(f"  url:     {n['url']}")

    # Detail view: summary is canonical, skeleton shown only if it adds information.
    # Other views use skeleton-as-preview; here both are available.
    print(f"\n--- SUMMARY ---\n  {n.get('summary', 'no summary')}")

    if n.get("skeleton") and n["skeleton"] != n.get("summary"):
        print(f"\n--- SKELETON ---\n  {n['skeleton']}")

    pred_groups = defaultdict(list)
    for neighbor, edge_list in neighbor_edges.items():
        for pred, direction in edge_list:
            if pred != "cosine_similarity":
                pred_groups[pred].append((neighbor, direction))

    if pred_groups:
        total_curated = sum(len(v) for v in pred_groups.values())
        MAX_CURATED = 25
        MAX_PER_PRED = 5
        print(f"\n--- CURATED CONNECTIONS ({total_curated}) ---\n")
        shown = 0
        for pred, targets in sorted(pred_groups.items(), key=lambda x: -len(x[1])):
            pred_shown = 0
            for target, direction in sorted(targets, key=lambda x: x[0]):
                if shown >= MAX_CURATED:
                    break
                if pred_shown >= MAX_PER_PRED:
                    break
                print(f"  {direction} {pred}: {target}")
                shown += 1
                pred_shown += 1
            if len(targets) > MAX_PER_PRED:
                print(f"    (+ {len(targets) - MAX_PER_PRED} more {pred})")
            if shown >= MAX_CURATED:
                break
        if total_curated > MAX_CURATED:
            print(f"\n  (showing top connections from {len(pred_groups)} predicates — use 'connections {resolved}' to paginate all)")

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
        shown = sim_neighbors[:PAGE_SIZE]
        print(f"\n--- SIMILAR NODES (top {len(shown)} of {len(sim_neighbors)}) ---\n")
        for sn, w in shown:
            sn_type = nodes[sn]["type"] if sn in nodes else "?"
            print(f"  {w:.3f}  [{sn_type:12s}] {sn}")
        save_pagination_state(resolved, 1, len(sim_neighbors))

    print(f"\n--- NAVIGATION ---")
    if pred_groups:
        first_neighbor = list(pred_groups.values())[0][0][0]
        print(f"  Follow a connection?          → node {first_neighbor}")
        total_curated = sum(len(v) for v in pred_groups.values())
        if total_curated > MAX_CURATED:
            print(f"  All connections (paginated)?  → connections {resolved}")
    if sim_neighbors and len(sim_neighbors) > PAGE_SIZE:
        print(f"  More similar nodes?           → next")
        print(f"  Jump to page?                 → similar {resolved} <page>")
    print(f"  What's nearby?                → subgraph {resolved} --hops 1")
    if cid is not None:
        print(f"  Others in this cluster?       → community {cid}")
    print(f"  Looking for something else?   → search <query>")
    print(f"  Back to home?                 → explore")


def get_sim_neighbors(resolved, nodes, adj, edges, neighbor_index=None):
    neighbor_edges = get_neighbors(resolved, adj, edges, neighbor_index=neighbor_index)
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
    sim_neighbors.sort(key=lambda x: -x[1])
    return sim_neighbors


def cmd_similar(name, nodes, adj, edges, page=1, node_community=None, neighbor_index=None):
    resolved = resolve_node(name, nodes)
    if not resolved:
        print(f"Error: no node matching '{name}'")
        print("  Try: search <keyword>")
        return

    sim_neighbors = get_sim_neighbors(resolved, nodes, adj, edges, neighbor_index=neighbor_index)

    if not sim_neighbors:
        print(f"No similar nodes found for '{resolved}'.")
        print(f"\n--- NAVIGATION ---")
        print(f"  Back to node detail?          → node {resolved}")
        print(f"  Back to home?                 → explore")
        return

    total = len(sim_neighbors)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    shown = sim_neighbors[start:end]

    save_pagination_state(resolved, page, total)

    print("=" * 60)
    print(f"SIMILAR NODES: {resolved}")
    print(f"  page {page} of {total_pages} ({start + 1}-{end} of {total})")
    print("=" * 60)

    cid = node_community.get(resolved) if node_community else None

    print()
    for sn, w in shown:
        sn_type = nodes[sn]["type"] if sn in nodes else "?"
        sn_cid = node_community.get(sn) if node_community else None
        community_tag = f"  C{sn_cid}" if sn_cid is not None else ""
        print(f"  {w:.3f}  [{sn_type:12s}] {sn}{community_tag}")

    print(f"\n--- NAVIGATION ---")
    if page < total_pages:
        print(f"  Next page?                    → next")
    if page > 1:
        print(f"  Previous page?                → similar {resolved} {page - 1}")
    if page < total_pages:
        print(f"  Jump to page?                 → similar {resolved} <page>")
    print(f"  Inspect a node?               → node <name>")
    print(f"  Back to node detail?          → node {resolved}")
    print(f"  Back to home?                 → explore")


def cmd_connections(name, nodes, adj, edges, page=1, neighbor_index=None):
    resolved = resolve_node(name, nodes)
    if not resolved:
        print(f"Error: no node matching '{name}'")
        print("  Try: search <keyword>")
        return

    neighbor_edges = get_neighbors(resolved, adj, edges, neighbor_index=neighbor_index)
    all_connections = []
    for neighbor, edge_list in neighbor_edges.items():
        for pred, direction in edge_list:
            if pred != "cosine_similarity":
                all_connections.append((pred, direction, neighbor))
    all_connections.sort(key=lambda x: (x[0], x[2]))

    if not all_connections:
        print(f"No curated connections for '{resolved}'.")
        print(f"\n--- NAVIGATION ---")
        print(f"  Back to node detail?          → node {resolved}")
        print(f"  Back to home?                 → explore")
        return

    total = len(all_connections)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    shown = all_connections[start:end]

    save_pagination_state(resolved, page, total)

    print("=" * 60)
    print(f"CONNECTIONS: {resolved}")
    print(f"  page {page} of {total_pages} ({start + 1}-{end} of {total})")
    print("=" * 60)

    print()
    for pred, direction, neighbor in shown:
        print(f"  {direction} {pred}: {neighbor}")

    print(f"\n--- NAVIGATION ---")
    if page < total_pages:
        print(f"  Next page?                    → next")
    if page > 1:
        print(f"  Previous page?                → connections {resolved} {page - 1}")
    if page < total_pages:
        print(f"  Jump to page?                 → connections {resolved} <page>")
    print(f"  Inspect a node?               → node <name>")
    print(f"  Back to node detail?          → node {resolved}")
    print(f"  Back to home?                 → explore")


def cmd_next(nodes, adj, edges, node_community=None, neighbor_index=None):
    state = load_pagination_state()
    if not state:
        print("Nothing to page through. Use 'node <name>' first to view a node's similar nodes.")
        return

    node_name = state["node"]
    current_page = state["page"]
    total = state["total"]
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    next_page = current_page + 1

    if next_page > total_pages:
        print(f"Already at last page ({current_page} of {total_pages}) for: {node_name}")
        print(f"\n--- NAVIGATION ---")
        print(f"  Back to page 1?               → similar {node_name} 1")
        print(f"  Back to node detail?          → node {node_name}")
        return

    cmd_similar(node_name, nodes, adj, edges, page=next_page,
                node_community=node_community, neighbor_index=neighbor_index)


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

            print(f"\n  [{n['type']}] {nid}    deg={deg}  C{cid}  origin={origin_str(n)}")
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


def cmd_path(args, nodes, adj, node_community=None):
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

    dist = {from_node: 0}
    parent = {from_node: []}
    queue = [from_node]
    found_dist = None

    while queue:
        current = queue.pop(0)
        if found_dist is not None and dist[current] > found_dist:
            break
        if current == to_node:
            found_dist = dist[current]
            continue
        for neighbor in adj.get(current, set()):
            nd = dist[current] + 1
            if neighbor not in dist:
                dist[neighbor] = nd
                parent[neighbor] = [current]
                queue.append(neighbor)
            elif nd == dist[neighbor]:
                parent[neighbor].append(current)

    def count_paths(node):
        if node == from_node:
            return 1
        return sum(count_paths(p) for p in parent.get(node, []))

    def reconstruct(node):
        if node == from_node:
            return [[from_node]]
        paths = []
        for p in parent.get(node, []):
            for prefix in reconstruct(p):
                paths.append(prefix + [node])
        return paths

    found = None
    num_paths = 0
    if to_node in dist:
        num_paths = count_paths(to_node)
        found = reconstruct(to_node)[0]

    print("=" * 60)
    print(f"PATH: {from_node} → {to_node}")
    print("=" * 60)

    if not found:
        print(f"\nNo path found between these nodes.")
    else:
        path_note = f" (1 of {num_paths} shortest)" if num_paths > 1 else ""
        print(f"\nLength: {len(found) - 1} hops{path_note}\n")
        for i, nid in enumerate(found):
            n = nodes[nid]
            prefix = "START" if i == 0 else "END  " if i == len(found) - 1 else f"  {i}  "
            skeleton = n.get("skeleton", n.get("summary", ""))
            if len(skeleton) > 60:
                skeleton = skeleton[:57] + "..."
            print(f"  {prefix} [{n['type']:12s}] {nid}")
            print(f"               {skeleton}")

    if found and num_paths > 1 and node_community:
        all_paths = reconstruct(to_node)
        community_paths = set()
        for p in all_paths:
            intermediates = p[1:-1]
            if intermediates:
                c_path = tuple(node_community.get(n, -1) for n in intermediates)
            else:
                c_path = ()
            community_paths.add(c_path)
        print(f"\n--- COMMUNITY-COLLAPSED PATHS ---")
        print(f"  {num_paths} node-paths through {len(community_paths)} distinct community-path(s)")
        if len(community_paths) <= 10:
            for cp in sorted(community_paths):
                print(f"    C{' → C'.join(str(c) for c in cp)}" if cp else "    (direct)")

    print(f"\n--- NAVIGATION ---")
    if found:
        print(f"  Inspect the start?            → node {from_node}")
        print(f"  Inspect the end?              → node {to_node}")
        print(f"  What's around the start?      → subgraph {from_node} --hops {max(1, (len(found)-1)//2)}")
    print(f"  Looking for something else?   → search <query>")
    print(f"  Back to home?                 → explore")


def get_similarity_lookup(edges):
    sim = {}
    for e in edges:
        if e["predicate"] == "cosine_similarity":
            key = tuple(sorted([e["source"], e["target"]]))
            sim[key] = e.get("weight", 0)
    return sim


def cmd_surprise(name, nodes, adj, edges, node_community=None):
    resolved = resolve_node(name, nodes)
    if not resolved:
        print(f"Error: no node matching '{name}'")
        print("  Try: search <keyword>")
        return

    sim_lookup = get_similarity_lookup(edges)

    curated_neighbors = {}
    for e in edges:
        if e["predicate"] == "cosine_similarity":
            continue
        if e["source"] == resolved:
            nb = e["target"]
            curated_neighbors.setdefault(nb, []).append(f"→ {e['predicate']}")
        elif e["target"] == resolved:
            nb = e["source"]
            curated_neighbors.setdefault(nb, []).append(f"← {e['predicate']}")

    with_sim = []
    without_sim = []
    for nb, preds in curated_neighbors.items():
        key = tuple(sorted([resolved, nb]))
        s = sim_lookup.get(key)
        if s is not None:
            with_sim.append((nb, s, preds))
        else:
            without_sim.append((nb, preds))

    with_sim.sort(key=lambda x: x[1])

    high_sim_no_edge = []
    for (a, b), s in sim_lookup.items():
        if a == resolved and b not in curated_neighbors:
            high_sim_no_edge.append((b, s))
        elif b == resolved and a not in curated_neighbors:
            high_sim_no_edge.append((a, s))
    high_sim_no_edge.sort(key=lambda x: -x[1])

    cid = node_community.get(resolved, "?") if node_community else "?"

    print("=" * 60)
    print(f"SURPRISE: {resolved}")
    print("=" * 60)
    print(f"\n  node: {resolved} ({nodes[resolved].get('type','?')}, C{cid})")
    print(f"  curated neighbors: {len(curated_neighbors)}")
    print(f"  with similarity score: {len(with_sim)}")

    if with_sim:
        print(f"\n--- UNEXPECTED CONNECTIONS (curated edge + low similarity) ---\n")
        for nb, s, preds in with_sim[:10]:
            nb_type = nodes[nb]["type"] if nb in nodes else "?"
            nb_cid = node_community.get(nb, "?") if node_community else "?"
            print(f"  {s:.3f}  [{nb_type}] {nb}  C{nb_cid}")
            for p in preds[:3]:
                print(f"         {p}")
    else:
        print(f"\n  No curated neighbors have similarity scores.")
        print(f"  (Similarity edges cover {len(sim_lookup)} pairs in the graph.)")

    if without_sim:
        print(f"\n  ({len(without_sim)} curated neighbor(s) have no similarity score — cannot rank by surprise)")

    if high_sim_no_edge:
        print(f"\n--- SIMILAR BUT UNCONNECTED (high similarity, no curated edge) ---\n")
        for nb, s in high_sim_no_edge[:10]:
            nb_type = nodes[nb]["type"] if nb in nodes else "?"
            nb_cid = node_community.get(nb, "?") if node_community else "?"
            print(f"  {s:.3f}  [{nb_type}] {nb}  C{nb_cid}")

    origins = origin_list(nodes[resolved])
    print(f"\n--- NAVIGATION ---")
    if with_sim:
        print(f"  Inspect a surprise?           → node {with_sim[0][0]}")
    if high_sim_no_edge:
        print(f"  Inspect a missing link?       → node {high_sim_no_edge[0][0]}")
    if origins:
        first_origin = origins[0]
        print(f"  Where hasn't {first_origin} reached? → gaps {first_origin}")
    print(f"  Back to node detail?          → node {resolved}")
    print(f"  Back to home?                 → explore")


def cmd_gaps(name, nodes, adj, edges, community_data=None, node_type=None):
    communities, node_community = community_data or ({}, {})

    valid_origins = set()
    for n in nodes.values():
        valid_origins.update(origin_list(n))
    if name.lower() not in valid_origins:
        print(f"Error: '{name}' is not a known origin.")
        print(f"  Valid origins: {', '.join(sorted(o for o in valid_origins if o))}")
        print(f"\n  gaps shows where an agent's thinking has and hasn't reached.")
        print(f"  For a single node, try: subgraph <name> --hops 1")
        return

    origin_set = filter_by_origin(nodes, name)

    connected = set()
    for nid in origin_set:
        connected |= adj.get(nid, set())
    connected |= origin_set

    type_filter_str = ""
    if node_type:
        type_set = filter_by_type(nodes, node_type)
        type_filter_str = f", type={node_type}"

    print("=" * 60)
    print(f"GAPS: {name} ({len(origin_set)} nodes{type_filter_str})")
    print("=" * 60)

    biggest_gap_cid = None
    biggest_gap_pct = 100

    if communities:
        print(f"\n--- COMMUNITY PRESENCE ---\n")
        for cid in sorted(communities.keys()):
            members = set(communities[cid])
            if node_type:
                members = members & type_set
            present = members & origin_set
            pct = len(present) / len(members) * 100 if members else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            label_str = community_label(list(communities[cid]), nodes)
            print(f"  C{cid} {bar} {len(present)}/{len(members)} nodes ({pct:.0f}%)  [{label_str}]")

        low_presence = []
        for cid in sorted(communities.keys()):
            members = set(communities[cid])
            if node_type:
                members = members & type_set
            if not members:
                continue
            present = list(members & origin_set)
            pct = len(present) / len(members) * 100 if members else 0
            if pct < biggest_gap_pct:
                biggest_gap_pct = pct
                biggest_gap_cid = cid
            if pct < 15:
                unconnected = members - connected
                top_unconnected = sorted(unconnected, key=lambda n: len(adj.get(n, set())), reverse=True)
                footholds = sorted(present, key=lambda n: len(adj.get(n, set())), reverse=True)
                low_presence.append((cid, pct, len(present), len(members), top_unconnected, footholds))

        if low_presence:
            print(f"\n--- BLIND SPOTS (communities with <15% presence) ---\n")
            for cid, pct, present_count, total, top_unc, footholds in low_presence:
                print(f"  C{cid} ({pct:.0f}% presence)  → explore this gap: community {cid}")
                if footholds:
                    print(f"    your footholds:")
                    for nid in footholds[:3]:
                        n = nodes[nid]
                        deg = len(adj.get(nid, set()))
                        print(f"      [{n['type']}] {nid} (deg={deg})")
                if top_unc:
                    print(f"    top unconnected:")
                    for nid in top_unc[:5]:
                        n = nodes[nid]
                        deg = len(adj.get(nid, set()))
                        print(f"      [{n['type']}] {nid} (deg={deg}, origin={origin_str(n)})")
                print()

    if node_type:
        all_nodes_for_type = {nid for nid, n in nodes.items() if n.get("type", "").lower() == node_type.lower()}
        origin_in_type = origin_set & all_nodes_for_type
        total_of_type = len(all_nodes_for_type)
        mine_of_type = len(origin_in_type)
        pct = mine_of_type / total_of_type * 100 if total_of_type else 0
        print(f"--- TYPE FILTER: {node_type} ---\n")
        print(f"  {name}'s {node_type} nodes: {mine_of_type}/{total_of_type} ({pct:.0f}%)")
        not_mine = all_nodes_for_type - origin_set
        if not_mine:
            print(f"\n  {node_type} nodes NOT in {name}'s set ({len(not_mine)}):\n")
            sorted_not_mine = sorted(not_mine, key=lambda n: -len(adj.get(n, set())))
            for nid in sorted_not_mine[:20]:
                n = nodes[nid]
                deg = len(adj.get(nid, set()))
                ncid = node_community.get(nid, "?")
                origins = origin_str(n)
                is_connected = nid in connected
                conn_mark = "↔" if is_connected else " "
                print(f"  {conn_mark} [{n['type']}] {nid}  (deg={deg}, C{ncid}, origin={origins})")
            if len(not_mine) > 20:
                print(f"  ... and {len(not_mine) - 20} more")
            print(f"\n  ↔ = connected to one of {name}'s nodes")
    else:
        all_types = Counter(n["type"] for n in nodes.values())
        origin_types = Counter(nodes[nid]["type"] for nid in origin_set)
        zero_types = []
        print(f"--- TYPE COVERAGE ---\n")
        for t, total in all_types.most_common():
            count = origin_types.get(t, 0)
            pct = count / total * 100
            print(f"  {t:15s}  {count:3d}/{total:3d}  ({pct:.0f}%)")
            if count == 0 and total > 3:
                zero_types.append((t, total))

    print(f"\n--- NAVIGATION ---")
    if biggest_gap_cid is not None:
        print(f"  Explore your biggest gap?     → community {biggest_gap_cid}")
    if not node_type and zero_types:
        t, total = zero_types[0]
        print(f"  See all {t} nodes?{' ' * max(1, 13 - len(t))} → explore --type {t}")
        print(f"  Filter gaps by type?          → gaps {name} --type {t}")
    elif not node_type:
        print(f"  Filter gaps by type?          → gaps {name} --type <type>")
    print(f"  Structural neighbors?         → jaccard <node>")
    print(f"  What surprises are there?     → surprise {name}")
    print(f"  Filter by this agent?         → explore --origin {name}")
    print(f"  Back to home?                 → explore")


def cmd_timeline(name, nodes, adj, edges, community_data=None, full=False):
    communities, node_community = community_data or ({}, {})

    valid_origins = set()
    for n in nodes.values():
        valid_origins.update(origin_list(n))
    if name.lower() not in valid_origins:
        print(f"Error: '{name}' is not a known origin.")
        print(f"  Valid origins: {', '.join(sorted(o for o in valid_origins if o))}")
        return

    origin_set = filter_by_origin(nodes, name)
    dated = [(nid, nodes[nid].get("created_date")) for nid in origin_set if nodes[nid].get("created_date")]
    undated_count = len(origin_set) - len(dated)

    dated.sort(key=lambda x: x[1])

    print("=" * 60)
    print(f"TIMELINE: {name} ({len(dated)} dated, {undated_count} undated)")
    print("=" * 60)

    if not dated:
        print(f"\n  No dated nodes found for {name}.")
        print(f"\n--- NAVIGATION ---")
        print(f"  What has {name} contributed?   → explore --origin {name}")
        print(f"  Back to home?                 → explore")
        return

    from datetime import datetime, timedelta

    by_week = {}
    for nid, date in dated:
        dt = datetime.strptime(date, "%Y-%m-%d")
        week_start = dt - timedelta(days=dt.weekday())
        week_key = week_start.strftime("%Y-%m-%d")
        by_week.setdefault(week_key, []).append((nid, date))

    first_date = dated[0][1]
    last_date = dated[-1][1]

    print(f"\n  first contribution: {first_date}")
    print(f"  latest contribution: {last_date}")

    type_counts = Counter(nodes[nid]["type"] for nid, _ in dated)
    type_str = ", ".join(f"{t}({c})" for t, c in type_counts.most_common(5))
    print(f"  types: {type_str}")

    max_week = max(len(v) for v in by_week.values())

    print(f"\n--- ACTIVITY BY WEEK ---\n")
    for week_key in sorted(by_week):
        items = by_week[week_key]
        bar_len = int(len(items) / max_week * 30) if max_week > 0 else 0
        bar = "█" * bar_len
        print(f"  {week_key}  {bar} {len(items)}")

    PREVIEW_LIMIT = 20
    show_all = full or len(dated) <= PREVIEW_LIMIT

    print(f"\n--- WHAT APPEARED WHEN ---\n")
    current_month = None
    shown = 0
    for nid, date in dated:
        if not show_all and shown >= PREVIEW_LIMIT:
            remaining = len(dated) - shown
            print(f"\n  ... and {remaining} more. See all? → timeline {name} --full")
            break
        month = date[:7]
        if month != current_month:
            current_month = month
            month_label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
            print(f"  {month_label}")
        n = nodes[nid]
        typ = n["type"]
        cid = node_community.get(nid, "?")
        print(f"    {date}  [{typ}] {nid}  C{cid}")
        shown += 1

    if undated_count > 0:
        print(f"\n  ({undated_count} nodes without dates not shown)")

    print(f"\n--- NAVIGATION ---")
    print(f"  Inspect a node?               → node <name>")
    print(f"  Where hasn't {name} reached?   → gaps {name}")
    print(f"  What surprises are there?     → surprise {name}")
    print(f"  Filter by this agent?         → explore --origin {name}")
    print(f"  Back to home?                 → explore")


def cmd_overlap(agent1, agent2, nodes, adj, edges, community_data=None):
    communities, node_community = community_data or ({}, {})

    valid_origins = set()
    for n in nodes.values():
        valid_origins.update(origin_list(n))

    a1 = agent1.lower()
    a2 = agent2.lower()
    for name in (a1, a2):
        if name not in valid_origins:
            print(f"Error: '{name}' is not a known origin.")
            print(f"  Valid origins: {', '.join(sorted(o for o in valid_origins if o))}")
            return

    set1 = filter_by_origin(nodes, a1)
    set2 = filter_by_origin(nodes, a2)
    shared = set1 & set2
    only1 = set1 - set2
    only2 = set2 - set1

    print("=" * 60)
    print(f"OVERLAP: {a1} ∩ {a2}")
    print("=" * 60)
    print(f"\n  {a1}: {len(set1)} nodes")
    print(f"  {a2}: {len(set2)} nodes")
    print(f"  shared: {len(shared)} nodes")
    print(f"  only {a1}: {len(only1)}")
    print(f"  only {a2}: {len(only2)}")
    overlap_pct = len(shared) / len(set1 | set2) * 100 if (set1 | set2) else 0
    print(f"  Jaccard (set overlap): {len(shared)}/{len(set1 | set2)} = {overlap_pct:.1f}%")

    if communities:
        print(f"\n--- COMMUNITY DISTRIBUTION ---\n")
        print(f"  {'':3s} {'community':20s} {a1:>8s} {a2:>8s}  {'shared':>6s}")
        print(f"  {'':3s} {'─' * 20} {'─' * 8} {'─' * 8}  {'─' * 6}")
        for cid in sorted(communities.keys()):
            members = set(communities[cid])
            c1 = len(members & set1)
            c2 = len(members & set2)
            cs = len(members & shared)
            label = community_label(list(members), nodes)[:20]
            print(f"  C{cid} {label:20s} {c1:8d} {c2:8d}  {cs:6d}")

    # Jaccard neighbor similarity: for each shared node, how similar are the two agents'
    # connections TO that node's neighborhood?
    if shared:
        print(f"\n--- SHARED NODES (by degree) ---\n")
        shared_with_deg = [(nid, len(adj.get(nid, set()))) for nid in shared]
        shared_with_deg.sort(key=lambda x: -x[1])
        for nid, deg in shared_with_deg[:15]:
            n = nodes[nid]
            cid = node_community.get(nid, "?")
            print(f"  [{n['type']}] {nid}  (deg={deg}, C{cid})")
        if len(shared) > 15:
            print(f"  ... and {len(shared) - 15} more")

    # Neighbor-set Jaccard: for each node in agent1's set, compute Jaccard similarity
    # with agent2's neighbor coverage. Find pairs where both agents connect to the same
    # neighborhoods despite not sharing the node itself.
    print(f"\n--- NEIGHBORHOOD JACCARD (structural proximity without shared nodes) ---\n")
    print(f"  Nodes unique to {a1} but structurally close to {a2}'s territory:")
    jaccard_scores = []
    for nid in only1:
        neighbors = adj.get(nid, set())
        if not neighbors:
            continue
        overlap_n = neighbors & set2
        union_n = neighbors | set2
        if union_n:
            j = len(overlap_n) / len(neighbors) if neighbors else 0
            if j > 0:
                jaccard_scores.append((nid, j, len(overlap_n), len(neighbors)))
    jaccard_scores.sort(key=lambda x: -x[1])
    for nid, j, ov, total in jaccard_scores[:8]:
        n = nodes[nid]
        cid = node_community.get(nid, "?")
        print(f"  {j:.2f}  [{n['type']}] {nid}  ({ov}/{total} neighbors in {a2}, C{cid})")
    if not jaccard_scores:
        print(f"  (no unique-to-{a1} nodes have neighbors in {a2}'s set)")

    print(f"\n  Nodes unique to {a2} but structurally close to {a1}'s territory:")
    jaccard_scores2 = []
    for nid in only2:
        neighbors = adj.get(nid, set())
        if not neighbors:
            continue
        overlap_n = neighbors & set1
        if overlap_n:
            j = len(overlap_n) / len(neighbors) if neighbors else 0
            jaccard_scores2.append((nid, j, len(overlap_n), len(neighbors)))
    jaccard_scores2.sort(key=lambda x: -x[1])
    for nid, j, ov, total in jaccard_scores2[:8]:
        n = nodes[nid]
        cid = node_community.get(nid, "?")
        print(f"  {j:.2f}  [{n['type']}] {nid}  ({ov}/{total} neighbors in {a1}, C{cid})")
    if not jaccard_scores2:
        print(f"  (no unique-to-{a2} nodes have neighbors in {a1}'s set)")

    # Temporal convergence: shared nodes sorted by creation date proximity
    if shared:
        dated_shared = []
        for nid in shared:
            d = nodes[nid].get("created_date", "")
            if d:
                dated_shared.append((nid, d))
        if dated_shared:
            dated_shared.sort(key=lambda x: x[1])
            print(f"\n--- CONVERGENCE TIMELINE (shared nodes by date) ---\n")
            for nid, d in dated_shared[:15]:
                n = nodes[nid]
                cid = node_community.get(nid, "?")
                print(f"  {d}  [{n['type']}] {nid}  C{cid}")
            if len(dated_shared) > 15:
                print(f"  ... and {len(dated_shared) - 15} more")

    print(f"\n--- NAVIGATION ---")
    print(f"  Explore {a1}'s gaps?           → gaps {a1}")
    print(f"  Explore {a2}'s gaps?           → gaps {a2}")
    if shared:
        top_shared = shared_with_deg[0][0]
        print(f"  Inspect top shared node?      → node {top_shared}")
    if jaccard_scores:
        top_j = jaccard_scores[0][0]
        print(f"  Inspect closest bridge?       → node {top_j}")
    print(f"  Back to home?                 → explore")


def cmd_jaccard(name, nodes, adj, edges, community_data=None):
    communities, node_community = community_data or ({}, {})

    resolved = resolve_node(name, nodes)
    if not resolved:
        print(f"Error: no node matching '{name}'")
        print("  Try: search <keyword>")
        return

    my_neighbors = adj.get(resolved, set())
    if not my_neighbors:
        print(f"Error: '{resolved}' has no neighbors — cannot compute Jaccard.")
        return

    sim_lookup = get_similarity_lookup(edges)

    curated_neighbors = set()
    for e in edges:
        if e["predicate"] == "cosine_similarity":
            continue
        if e["source"] == resolved:
            curated_neighbors.add(e["target"])
        elif e["target"] == resolved:
            curated_neighbors.add(e["source"])

    scores = []
    for other_id in nodes:
        if other_id == resolved:
            continue
        other_neighbors = adj.get(other_id, set())
        if not other_neighbors:
            continue
        intersection = my_neighbors & other_neighbors
        if not intersection:
            continue
        union = my_neighbors | other_neighbors
        j = len(intersection) / len(union)
        scores.append((other_id, j, len(intersection), len(union)))

    scores.sort(key=lambda x: -x[1])

    cid = node_community.get(resolved, "?")
    print("=" * 60)
    print(f"JACCARD: {resolved}")
    print("=" * 60)
    print(f"\n  node: {resolved} ({nodes[resolved].get('type','?')}, C{cid})")
    print(f"  neighbors: {len(my_neighbors)}")
    print(f"  curated edges: {len(curated_neighbors)}")
    print(f"  nodes with shared neighbors: {len(scores)}")

    if scores:
        print(f"\n--- TOP STRUCTURAL NEIGHBORS (by neighbor-set Jaccard) ---\n")
        for nid, j, inter, union in scores[:15]:
            n = nodes[nid]
            ncid = node_community.get(nid, "?")
            cosine_key = tuple(sorted([resolved, nid]))
            cosine = sim_lookup.get(cosine_key)
            is_connected = nid in curated_neighbors
            conn_mark = "●" if is_connected else "○"
            cosine_str = f"cos={cosine:.3f}" if cosine is not None else "no-cos"
            print(f"  {conn_mark} J={j:.3f}  [{n['type']}] {nid}  "
                  f"C{ncid}  ({inter}/{union} shared)  {cosine_str}")
        print(f"\n  ● = curated edge exists  ○ = no curated edge")

    # Cross-domain parallels: high Jaccard but low/no cosine similarity
    parallels = []
    for nid, j, inter, union in scores:
        if j < 0.05:
            break
        cosine_key = tuple(sorted([resolved, nid]))
        cosine = sim_lookup.get(cosine_key)
        is_connected = nid in curated_neighbors
        if cosine is not None and cosine < 0.45:
            parallels.append((nid, j, cosine, inter, "low_cosine"))
        elif cosine is None and not is_connected:
            parallels.append((nid, j, None, inter, "unscored_unconnected"))

    if parallels:
        parallels.sort(key=lambda x: -x[1])
        print(f"\n--- CROSS-DOMAIN PARALLELS (high Jaccard, low/no cosine) ---\n")
        print(f"  These nodes occupy similar graph positions but use different vocabulary.")
        print(f"  They are structural isomorphs — same role, different domain.\n")
        for nid, j, cosine, inter, reason in parallels[:10]:
            n = nodes[nid]
            ncid = node_community.get(nid, "?")
            if cosine is not None:
                print(f"  J={j:.3f} cos={cosine:.3f}  [{n['type']}] {nid}  C{ncid}  ({inter} shared neighbors)")
            else:
                print(f"  J={j:.3f} no-cos     [{n['type']}] {nid}  C{ncid}  ({inter} shared neighbors)")
        if not any(x[4] == "low_cosine" for x in parallels):
            print(f"\n  (All parallels are unscored — cosine data would strengthen this analysis)")

    # Unconnected structural neighbors: high Jaccard, no curated edge
    unconnected_high = [(nid, j, inter) for nid, j, inter, union in scores[:50]
                        if nid not in curated_neighbors and j >= 0.05]
    if unconnected_high:
        print(f"\n--- SUGGESTED EDGES (high Jaccard, no curated connection) ---\n")
        for nid, j, inter in unconnected_high[:8]:
            n = nodes[nid]
            ncid = node_community.get(nid, "?")
            shared_names = sorted(my_neighbors & adj.get(nid, set()),
                                  key=lambda x: -len(adj.get(x, set())))[:3]
            via_str = ", ".join(shared_names[:3])
            print(f"  J={j:.3f}  [{n['type']}] {nid}  C{ncid}")
            print(f"          via: {via_str}")

    print(f"\n--- NAVIGATION ---")
    if scores:
        print(f"  Inspect top match?            → node {scores[0][0]}")
    if parallels:
        print(f"  Inspect a parallel?           → node {parallels[0][0]}")
    print(f"  Compare with another node?    → jaccard {scores[0][0] if scores else '<name>'}")
    print(f"  See {resolved}'s surprise edges? → surprise {resolved}")
    print(f"  Back to home?                 → explore")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return

    nodes, adj, edges, precomputed = load_graph()
    neighbor_index = build_neighbor_index(edges)
    cmd = sys.argv[1]
    rest = sys.argv[2:]
    origin, node_type, full, rest = parse_flags(rest)

    community_data = None
    if cmd in ("explore", "community", "node", "similar", "next", "search", "timeline", "path", "overlap", "jaccard"):
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
        cmd_node(name, nodes, adj, edges, node_community=node_community, neighbor_index=neighbor_index)
    elif cmd == "similar":
        if not rest:
            print("Usage: similar <name> [page]")
            return
        page = 1
        if rest[-1].isdigit():
            page = int(rest[-1])
            rest = rest[:-1]
        if not rest:
            print("Usage: similar <name> [page]")
            return
        name = " ".join(rest)
        _, node_community = community_data
        cmd_similar(name, nodes, adj, edges, page=page, node_community=node_community, neighbor_index=neighbor_index)
    elif cmd == "next":
        if not community_data:
            community_data = compute_communities(nodes, adj, edges, precomputed=precomputed)
        _, node_community = community_data
        cmd_next(nodes, adj, edges, node_community=node_community, neighbor_index=neighbor_index)
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
        _, node_community = community_data
        cmd_path(sys.argv[2:], nodes, adj, node_community=node_community)
    elif cmd == "surprise":
        if not rest:
            print("Usage: surprise <name>")
            return
        if not community_data:
            community_data = compute_communities(nodes, adj, edges, precomputed=precomputed)
        name = " ".join(rest)
        _, node_community = community_data
        cmd_surprise(name, nodes, adj, edges, node_community=node_community)
    elif cmd == "gaps":
        if not rest:
            print("Usage: gaps <name or origin> [--type <type>]")
            return
        if not community_data:
            community_data = compute_communities(nodes, adj, edges, precomputed=precomputed)
        name = " ".join(rest)
        cmd_gaps(name, nodes, adj, edges, community_data=community_data, node_type=node_type)
    elif cmd == "timeline":
        if not rest:
            print("Usage: timeline <origin>")
            return
        if not community_data:
            community_data = compute_communities(nodes, adj, edges, precomputed=precomputed)
        name = " ".join(rest)
        cmd_timeline(name, nodes, adj, edges, community_data=community_data, full=full)
    elif cmd == "overlap":
        if len(rest) < 2:
            print("Usage: overlap <agent1> <agent2>")
            return
        if not community_data:
            community_data = compute_communities(nodes, adj, edges, precomputed=precomputed)
        cmd_overlap(rest[0], rest[1], nodes, adj, edges, community_data=community_data)
    elif cmd == "connections":
        if not rest:
            print("Usage: connections <name> [page]")
            return
        page = 1
        if rest[-1].isdigit():
            page = int(rest[-1])
            rest = rest[:-1]
        if not rest:
            print("Usage: connections <name> [page]")
            return
        name = " ".join(rest)
        cmd_connections(name, nodes, adj, edges, page=page, neighbor_index=neighbor_index)
    elif cmd == "jaccard":
        if not rest:
            print("Usage: jaccard <name>")
            print("  Shows structural neighbors — nodes that share the same neighborhood")
            print("  regardless of semantic similarity. Catches cross-domain parallels.")
            return
        if not community_data:
            community_data = compute_communities(nodes, adj, edges, precomputed=precomputed)
        name = " ".join(rest)
        cmd_jaccard(name, nodes, adj, edges, community_data=community_data)
    else:
        print(f"Unknown command: {cmd}")
        print("Commands: explore, community, node, similar, next, subgraph, search, path, surprise, gaps, timeline, overlap, jaccard")
        print("Run with --help for usage.")


if __name__ == "__main__":
    main()
