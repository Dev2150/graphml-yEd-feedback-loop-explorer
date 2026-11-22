from collections import defaultdict, deque
from typing import Dict, List, Tuple

import networkx as nx

from src.family.terminology import SPOUSE_KEYWORDS


def is_spouse_edge(u: str, v: str, edge_labels: Dict[Tuple[str, str], str]) -> bool:
	lbl = edge_labels.get((u, v), '').lower()
	return any(kw in lbl for kw in SPOUSE_KEYWORDS)


def build_family_structures(g: nx.DiGraph, edge_labels: Dict[Tuple[str, str], str]):
	parents_map = defaultdict(list)
	children_map = defaultdict(list)
	spouses_map = defaultdict(set)

	# 1. Classify edges into parent-child vs explicit spouse edges
	for u, v in g.edges():
		if is_spouse_edge(u, v, edge_labels) or is_spouse_edge(v, u, edge_labels):
			spouses_map[u].add(v)
			spouses_map[v].add(u)
		else:
			# u is parent of v
			parents_map[v].append(u)
			children_map[u].append(v)

	# 2. Co-parents (two people who share at least one child are partners/spouses)
	for _child, p_list in parents_map.items():
		for i in range(len(p_list)):
			for j in range(i + 1, len(p_list)):
				p1, p2 = p_list[i], p_list[j]
				spouses_map[p1].add(p2)
				spouses_map[p2].add(p1)

	return parents_map, children_map, spouses_map


def compute_all_ancestors(nodes: List[str], parents_map: Dict[str, List[str]]):
	"""
	For every node, precomputes:
	  ancestor_paths[node][ancestor] -> list of all shortest paths from ancestor to node [ancestor, ..., node]
	  ancestor_dist[node][ancestor] -> distance (generations)
	"""
	ancestor_paths = {}
	ancestor_dist = {}

	for n in nodes:
		paths_to_n = {n: [[n]]}
		dist_to_n = {n: 0}
		queue = deque([n])

		while queue:
			curr = queue.popleft()
			curr_d = dist_to_n[curr]
			for p in parents_map.get(curr, []):
				if p not in dist_to_n:
					dist_to_n[p] = curr_d + 1
					paths_to_n[p] = []
					queue.append(p)
				if dist_to_n[p] == curr_d + 1:
					for subpath in paths_to_n[curr]:
						paths_to_n[p].append([p] + subpath)

		ancestor_paths[n] = paths_to_n
		ancestor_dist[n] = dist_to_n

	return ancestor_paths, ancestor_dist