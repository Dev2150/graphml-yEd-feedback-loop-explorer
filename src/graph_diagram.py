import os
import textwrap
import math
from dataclasses import dataclass, field
from collections import deque
from typing import Dict, Iterable, List, Optional, Set, Tuple
from src.io_graphml import detect_gender


COLOR_GOLD = '#FFCC00'
COLOR_BLACK = '#000000'
COLOR_WHITE = '#FFFFFF'
COLOR_PINK = '#FF99CC'
COLOR_BLUE = '#00CCFF'
COLOR_RED = '#FF0000'
COLOR_SPOUSE_GREEN = '#77DD77'
COLOR_DARK_GREEN = '#006400'
NODE_WRAP_CHAR_THRESHOLD = 18


def format_graph_node_label(label: str, max_chars_per_line: int = NODE_WRAP_CHAR_THRESHOLD) -> str:
	"""
	Formats a graph node label for visual rendering:
	- Preserves existing line breaks.
	- Any '→' starts on a new line beginning with '→'.
	- Lines longer than `max_chars_per_line` wrap cleanly.
	"""
	text = str(label or "").strip()
	if not text:
		return ""

	wrapped_lines: List[str] = []
	for raw_line in text.splitlines():
		raw_line = raw_line.strip()
		if not raw_line:
			continue

		segments: List[str] = []
		if '→' in raw_line:
			parts = raw_line.split('→')
			first = parts[0].strip()
			if first:
				segments.append(first)
			for part in parts[1:]:
				part_clean = part.strip()
				segments.append(f"→ {part_clean}" if part_clean else "→")
		else:
			segments.append(raw_line)

		for seg in segments:
			if len(seg) > max_chars_per_line:
				wrapped = textwrap.wrap(
					seg,
					width=max_chars_per_line,
					break_long_words=True,
					break_on_hyphens=True,
				)
				wrapped_lines.extend(wrapped if wrapped else [seg])
			else:
				wrapped_lines.append(seg)

	return "\n".join(wrapped_lines)


@dataclass
class DiagramNode:
	node_id: str
	label: str
	role: str  # 'target', 'common_source', 'common_effect', 'default'
	fill_color: str
	text_color: str
	outline_color: str = COLOR_BLACK

@dataclass
class DiagramEdge:
	source_id: str
	target_id: str
	correlation: int  # +1 -> black arrow, -1 -> red arrow
	color: str
	bidirectional: bool = False

@dataclass
class DiagramCycle:
	node_ids: List[str]
	edges: Set[Tuple[str, str]]
	polarity: Optional[int]  # +1 reinforcing (+), -1 balancing (-), None if ignored/neutral
	is_secondary: bool = False

@dataclass
class GraphDiagramData:
	title: str
	nodes: List[DiagramNode]
	edges: List[DiagramEdge]
	cycles: List[DiagramCycle] = field(default_factory=list)
	default_highlight: Optional['AnswerHighlight'] = None
	merged_nodes: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class AnswerHighlight:
	node_ids: Set[str]
	edges: Set[Tuple[str, str]]
	is_cycle: bool = False
	cycle_polarity: Optional[int] = None  # +1 reinforcing (+), -1 balancing (-), None if ignored/neutral
	cycle_node_ids: Optional[List[str]] = None
	diagram: Optional[GraphDiagramData] = None
	first_node_id: Optional[str] = None
	first_node_ids: Set[str] = field(default_factory=set)


def blend_hex_with_white(hex_color: str, alpha: float) -> str:
	h = hex_color.lstrip('#')
	if len(h) != 6:
		return '#CCCCCC'
	r = int(h[0:2], 16)
	g = int(h[2:4], 16)
	b = int(h[4:6], 16)
	r_out = max(0, min(255, round(r * alpha + 255.0 * (1.0 - alpha))))
	g_out = max(0, min(255, round(g * alpha + 255.0 * (1.0 - alpha))))
	b_out = max(0, min(255, round(b * alpha + 255.0 * (1.0 - alpha))))
	return f"#{r_out:02X}{g_out:02X}{b_out:02X}"


def compute_cycle_center(
	highlight: Optional[AnswerHighlight],
	rects: Dict[str, Tuple[float, float, float, float]],
) -> Optional[Tuple[float, float]]:
	if highlight is None or not highlight.is_cycle:
		return None
	ids = highlight.cycle_node_ids if highlight.cycle_node_ids else list(highlight.node_ids)
	coords = [rects[nid] for nid in ids if nid in rects]
	if not coords:
		return None
	cx = sum(c[0] for c in coords) / len(coords)
	cy = sum(c[1] for c in coords) / len(coords)
	return cx, cy


def compute_diagram_cycle_centers(
	cycles: List[DiagramCycle],
	rects: Dict[str, Tuple[float, float, float, float]],
	min_sep: float = 40.0,
) -> Dict[int, Tuple[float, float]]:
	"""
	Computes (cx, cy) icon positions for each cycle in `cycles`, gently separating
	cycles whose node centroids overlap (e.g. opposite-direction cycles on the same nodes).
	"""
	raw: Dict[int, List[float]] = {}
	for idx, cyc in enumerate(cycles):
		if cyc.polarity not in (1, -1):
			continue
		coords = [rects[nid] for nid in cyc.node_ids if nid in rects]
		if not coords:
			continue
		raw[idx] = [
			sum(c[0] for c in coords) / len(coords),
			sum(c[1] for c in coords) / len(coords),
		]

	if len(raw) <= 1:
		return {idx: (pos[0], pos[1]) for idx, pos in raw.items()}

	keys = list(raw.keys())

	# Pre-spread exact/near-identical centroids deterministically
	groups: List[List[int]] = []
	assigned: Set[int] = set()
	for i in keys:
		if i in assigned:
			continue
		grp = [i]
		assigned.add(i)
		xi, yi = raw[i]
		for j in keys:
			if j in assigned:
				continue
			xj, yj = raw[j]
			if math.hypot(xj - xi, yj - yi) < 2.0:
				grp.append(j)
				assigned.add(j)
		groups.append(grp)

	for grp in groups:
		if len(grp) == 2:
			off = min_sep * 0.55
			raw[grp[0]][0] -= off
			raw[grp[1]][0] += off
		elif len(grp) > 2:
			rad = min_sep * 0.65
			for k, idx in enumerate(grp):
				ang = (2.0 * math.pi * k) / len(grp)
				raw[idx][0] += rad * math.cos(ang)
				raw[idx][1] += rad * math.sin(ang)

	# Repulsion pass for close non-identical centers
	for _ in range(10):
		moved = False
		for a_i in range(len(keys)):
			i = keys[a_i]
			for b_i in range(a_i + 1, len(keys)):
				j = keys[b_i]
				dx = raw[j][0] - raw[i][0]
				dy = raw[j][1] - raw[i][1]
				dist = math.hypot(dx, dy)
				if dist < min_sep:
					moved = True
					if dist < 1e-3:
						ux, uy = 1.0, 0.0
					else:
						ux, uy = dx / dist, dy / dist
					push = (min_sep - dist) / 2.0
					raw[i][0] -= ux * push
					raw[i][1] -= uy * push
					raw[j][0] += ux * push
					raw[j][1] += uy * push
		if not moved:
			break

	return {idx: (pos[0], pos[1]) for idx, pos in raw.items()}

def find_cycle_icon_path(polarity: Optional[int]) -> Optional[str]:
	if polarity not in (1, -1):
		return None
	src_dir = os.path.dirname(os.path.abspath(__file__))
	root_dir = os.path.dirname(src_dir)
	names = ('plus.png', 'cycle_plus.png', 'plus.jpg') if polarity > 0 else ('minus.png', 'cycle_minus.png', 'minus.jpg')
	for base_dir in (os.path.join(src_dir, 'assets'), os.path.join(root_dir, 'assets')):
		for name in names:
			candidate = os.path.join(base_dir, name)
			if os.path.isfile(candidate):
				return candidate
	return None

def _normalize_hex_color(color: Optional[str], fallback: str = COLOR_WHITE) -> str:
	if not color:
		return fallback
	c = str(color).strip()
	if c.startswith('#'):
		c = c[1:]
	if len(c) == 6:
		try:
			int(c, 16)
			return f"#{c.upper()}"
		except ValueError:
			return fallback
	return fallback


def _contrasting_text_color(hex_color: str) -> str:
	h = hex_color.lstrip('#')
	if len(h) != 6:
		return COLOR_BLACK
	try:
		r = int(h[0:2], 16)
		g = int(h[2:4], 16)
		b = int(h[4:6], 16)
	except ValueError:
		return COLOR_BLACK
	luminance = 0.299 * r + 0.587 * g + 0.114 * b
	return COLOR_WHITE if luminance < 128.0 else COLOR_BLACK


def _make_diagram_node(
	node_id: str,
	label: str,
	target_ids: Set[str],
	common_source_ids: Set[str],
	common_effect_ids: Set[str],
	node_colors: Optional[Dict[str, str]] = None,
) -> DiagramNode:
	if node_colors is not None and node_id in node_colors:
		fill_color = _normalize_hex_color(node_colors.get(node_id), fallback=COLOR_WHITE)
	else:
		fill_color = COLOR_GOLD
	text_color = _contrasting_text_color(fill_color)

	if node_id in target_ids:
		return DiagramNode(node_id, label, 'target', fill_color, text_color, outline_color=COLOR_BLACK)
	if node_id in common_source_ids:
		return DiagramNode(node_id, label, 'common_source', fill_color, text_color, outline_color=COLOR_PINK)
	if node_id in common_effect_ids:
		return DiagramNode(node_id, label, 'common_effect', fill_color, text_color, outline_color=COLOR_BLUE)
	return DiagramNode(node_id, label, 'default', fill_color, text_color, outline_color=COLOR_BLACK)

def _score_circular_order(
	order: List[int],
	undirected_edges: List[Tuple[int, int]],
	n: int,
) -> Tuple[int, int]:
	pos = [0] * n
	for idx, node in enumerate(order):
		pos[node] = idx

	ep: List[Tuple[int, int]] = []
	total_dist = 0
	for u, v in undirected_edges:
		pu, pv = pos[u], pos[v]
		if pu > pv:
			pu, pv = pv, pu
		ep.append((pu, pv))
		d = pv - pu
		total_dist += d if d <= n - d else n - d

	ep.sort()
	crossings = 0
	m = len(ep)
	for i in range(m):
		a, b = ep[i]
		for j in range(i + 1, m):
			c, d = ep[j]
			if c >= b:
				break
			if a < c and b < d:
				crossings += 1
	return crossings, total_dist


def _normalize_cycle_order(order: List[int], anchor: int = 0) -> List[int]:
	if not order or anchor not in order:
		return list(order)
	idx = order.index(anchor)
	rotated = order[idx:] + order[:idx]
	if len(rotated) >= 3 and rotated[1] > rotated[-1]:
		rotated = [rotated[0]] + list(reversed(rotated[1:]))
	return rotated


def _improve_circular_order(
	initial_order: List[int],
	undirected_edges: List[Tuple[int, int]],
	n: int,
) -> Tuple[Tuple[int, int], List[int]]:
	order = list(initial_order)
	best_score = _score_circular_order(order, undirected_edges, n)
	max_passes = 20 if n <= 30 else 5

	for _ in range(max_passes):
		improved = False

		# Relocate single node to best position
		for i in range(n):
			node = order[i]
			base = order[:i] + order[i + 1:]
			best_cand = None
			for j in range(n):
				if j == i:
					continue
				cand = base[:j] + [node] + base[j:]
				sc = _score_circular_order(cand, undirected_edges, n)
				if sc < best_score:
					best_score = sc
					best_cand = cand
			if best_cand is not None:
				order = best_cand
				improved = True

		# 2-opt segment reversals
		for i in range(n - 1):
			for j in range(i + 1, n):
				cand = order[:i] + list(reversed(order[i:j + 1])) + order[j + 1:]
				sc = _score_circular_order(cand, undirected_edges, n)
				if sc < best_score:
					best_score = sc
					order = cand
					improved = True

		if not improved:
			break

	return best_score, _normalize_cycle_order(order, 0)


def _compute_circular_order(
	node_ids: Iterable[str],
	edge_pairs: List[Tuple[str, str]],
	target_ids: Set[str],
	nodes_dict: Dict[str, str],
) -> List[str]:
	unique_ids = list(dict.fromkeys(node_ids))
	n = len(unique_ids)
	if n <= 2:
		return unique_ids

	base_nodes = sorted(
		unique_ids,
		key=lambda x: (0 if x in target_ids else 1, str(nodes_dict.get(x, x)).lower(), str(x)),
	)
	id_to_idx = {nid: idx for idx, nid in enumerate(base_nodes)}

	edge_set: Set[Tuple[int, int]] = set()
	adj: List[List[int]] = [[] for _ in range(n)]
	for u, v in edge_pairs:
		if u in id_to_idx and v in id_to_idx and u != v:
			iu, iv = id_to_idx[u], id_to_idx[v]
			pair = (iu, iv) if iu < iv else (iv, iu)
			if pair not in edge_set:
				edge_set.add(pair)
				adj[iu].append(iv)
				adj[iv].append(iu)

	for lst in adj:
		lst.sort()

	undirected_edges = sorted(edge_set)
	if len(undirected_edges) <= 1:
		return base_nodes

	# Candidate 1: DFS order
	dfs_order: List[int] = []
	visited: Set[int] = set()

	def dfs(curr: int):
		visited.add(curr)
		dfs_order.append(curr)
		for nxt in adj[curr]:
			if nxt not in visited:
				dfs(nxt)

	for start in range(n):
		if start not in visited:
			dfs(start)

	# Candidate 2: BFS order
	bfs_order: List[int] = []
	visited_bfs: Set[int] = set()
	for start in range(n):
		if start in visited_bfs:
			continue
		visited_bfs.add(start)
		q = deque([start])
		while q:
			curr = q.popleft()
			bfs_order.append(curr)
			for nxt in adj[curr]:
				if nxt not in visited_bfs:
					visited_bfs.add(nxt)
					q.append(nxt)

	# Candidate 3: Greedy min-crossing insertion
	deg_order = sorted(range(n), key=lambda x: (-len(adj[x]), x))
	greedy_order = [0]
	for node in deg_order:
		if node == 0:
			continue
		placed_set = set(greedy_order) | {node}
		sub_edges = [(u, v) for (u, v) in undirected_edges if u in placed_set and v in placed_set]
		best_pos = len(greedy_order)
		best_sub_score = None
		cur_len = len(greedy_order) + 1
		for pos_idx in range(cur_len):
			cand = greedy_order[:pos_idx] + [node] + greedy_order[pos_idx:]
			remap = {nid: idx for idx, nid in enumerate(cand)}
			remapped_edges = [(remap[u], remap[v]) for u, v in sub_edges]
			sc = _score_circular_order(list(range(cur_len)), remapped_edges, cur_len)
			if best_sub_score is None or sc < best_sub_score:
				best_sub_score = sc
				best_pos = pos_idx
		greedy_order.insert(best_pos, node)

	best_score = None
	best_order = list(range(n))
	seen_starts: Set[Tuple[int, ...]] = set()
	for start_cand in (greedy_order, dfs_order, bfs_order, list(range(n))):
		norm_start = tuple(_normalize_cycle_order(start_cand, 0))
		if norm_start in seen_starts:
			continue
		seen_starts.add(norm_start)
		sc, imp = _improve_circular_order(list(norm_start), undirected_edges, n)
		if best_score is None or sc < best_score:
			best_score = sc
			best_order = imp

	# Exact branch-and-bound for small graphs (fixes node 0 at index 0, breaks mirror symmetry)
	if 3 <= n <= 10 and best_score > (0, len(undirected_edges)):
		steps = 0
		steps_limit = 60000
		order = [0] * n
		pos = [-1] * n
		pos[0] = 0
		rem_deg = [len(adj[i]) for i in range(n)]
		for nb in adj[0]:
			rem_deg[nb] -= 1
		completed_edges: List[Tuple[int, int]] = []

		def bnb(k: int, cross_so_far: int):
			nonlocal steps, best_score, best_order
			if steps >= steps_limit:
				return
			if k == n:
				sc = _score_circular_order(order, undirected_edges, n)
				if sc < best_score:
					best_score = sc
					best_order = list(order)
				return

			for w in range(1, n):
				if pos[w] != -1:
					continue
				if k == 1 and w == n - 1:
					continue
				if k == n - 1 and w <= order[1]:
					continue

				steps += 1
				if steps > steps_limit:
					return

				placed_nbr_pos = [pos[nb] for nb in adj[w] if pos[nb] != -1]
				added_cross = 0
				for p in placed_nbr_pos:
					for a, b in completed_edges:
						if a < p < b:
							added_cross += 1

				next_cross = cross_so_far + added_cross
				if next_cross > best_score[0]:
					continue

				order[k] = w
				pos[w] = k
				for nb in adj[w]:
					rem_deg[nb] -= 1

				new_edges = [(p, k) for p in placed_nbr_pos]
				pref = [0] * (k + 2)
				for x in range(k + 1):
					pref[x + 1] = pref[x] + rem_deg[order[x]]

				lb_future = 0
				for a, b in completed_edges:
					lb_future += pref[b] - pref[a + 1]
				for p, _k in new_edges:
					lb_future += pref[k] - pref[p + 1]

				if next_cross + lb_future <= best_score[0]:
					completed_edges.extend(new_edges)
					bnb(k + 1, next_cross)
					if new_edges:
						del completed_edges[-len(new_edges):]

				for nb in adj[w]:
					rem_deg[nb] += 1
				pos[w] = -1

		bnb(1, 0)
		best_order = _normalize_cycle_order(best_order, 0)

	return [base_nodes[i] for i in best_order]

def _assemble_diagram(
	title: str,
	node_ids: Iterable[str],
	edge_pairs: List[Tuple[str, str]],
	target_ids: Set[str],
	common_source_ids: Set[str],
	common_effect_ids: Set[str],
	nodes_dict: Dict[str, str],
	edge_values: Dict[Tuple[str, str], int],
	ignore_edge_colors: bool = False,
	cycles: Optional[List[DiagramCycle]] = None,
	bidirectional_edges: Optional[Set[Tuple[str, str]]] = None,
	default_highlight: Optional[AnswerHighlight] = None,
	node_colors: Optional[Dict[str, str]] = None,
	merged_nodes: Optional[Dict[str, List[str]]] = None,
) -> GraphDiagramData:
	seen_edges: Set[Tuple[str, str]] = set()
	dedup_edges: List[Tuple[str, str]] = []
	all_node_ids = list(node_ids)
	bidir_set = set(bidirectional_edges or ())

	for u, v in edge_pairs:
		if u == v:
			continue
		if u not in all_node_ids:
			all_node_ids.append(u)
		if v not in all_node_ids:
			all_node_ids.append(v)
		if (u, v) not in seen_edges:
			seen_edges.add((u, v))
			dedup_edges.append((u, v))

	ordered_ids = _compute_circular_order(all_node_ids, dedup_edges, target_ids, nodes_dict)
	diagram_nodes = [
		_make_diagram_node(
			nid,
			str(nodes_dict.get(nid, nid)),
			target_ids,
			common_source_ids,
			common_effect_ids,
			node_colors
		)
		for nid in ordered_ids
	]

	diagram_edges: List[DiagramEdge] = []
	for u, v in dedup_edges:
		corr = 1 if ignore_edge_colors else edge_values.get((u, v), 1)
		is_bidir = (u, v) in bidir_set
		arrow_color = COLOR_DARK_GREEN if is_bidir else (COLOR_BLACK if corr > 0 else COLOR_RED)
		diagram_edges.append(DiagramEdge(u, v, corr, arrow_color, bidirectional=is_bidir))

	return GraphDiagramData(
		title=title,
		nodes=diagram_nodes,
		edges=diagram_edges,
		cycles=list(cycles or []),
		default_highlight=default_highlight,
		merged_nodes=dict(merged_nodes or {}),
	)


def build_cycle_diagram(
	paths: List[List[str]],
	answer_node_ids: Set[str],
	nodes_dict: Dict[str, str],
	edge_values: Dict[Tuple[str, str], int],
	ignore_edge_colors: bool = False,
	question_num: int = 0,
	node_colors: Optional[Dict[str, str]] = None
) -> GraphDiagramData:
	edge_pairs: List[Tuple[str, str]] = []
	node_ids: List[str] = []
	diagram_cycles: List[DiagramCycle] = []
	seen_edge_sets: Set[frozenset] = set()

	for path in paths:
		for nid in path:
			if nid not in node_ids:
				node_ids.append(nid)
		for k in range(len(path) - 1):
			edge_pairs.append((path[k], path[k + 1]))
		if len(path) >= 3 and path[0] == path[-1]:
			dc = _build_diagram_cycle(path, edge_values, ignore_edge_colors, is_secondary=False)
			key = frozenset(dc.edges)
			if key not in seen_edge_sets:
				seen_edge_sets.add(key)
				diagram_cycles.append(dc)

	prefix = f"Q{question_num}: " if question_num else ""
	ans_names = ", ".join(str(nodes_dict.get(nid, nid)) for nid in sorted(answer_node_ids, key=lambda x: str(nodes_dict.get(x, x)).lower()))
	title = f"{prefix}Cycle ({ans_names})"

	return _assemble_diagram(
		title=title,
		node_ids=node_ids,
		edge_pairs=edge_pairs,
		target_ids=set(answer_node_ids),
		common_source_ids=set(),
		common_effect_ids=set(),
		nodes_dict=nodes_dict,
		edge_values=edge_values,
		ignore_edge_colors=ignore_edge_colors,
		cycles=diagram_cycles,
		node_colors=node_colors
	)


def build_leaf_diagram(
	anchor_node: str,
	leaf_nodes: List[str],
	is_source_question: bool,
	nodes_dict: Dict[str, str],
	edge_values: Dict[Tuple[str, str], int],
	ignore_edge_colors: bool = False,
	question_num: int = 0,
	node_colors: Optional[Dict[str, str]] = None
) -> GraphDiagramData:
	if is_source_question:
		edge_pairs = [(s, anchor_node) for s in leaf_nodes]
	else:
		edge_pairs = [(anchor_node, d) for d in leaf_nodes]

	anchor_name = nodes_dict.get(anchor_node, str(anchor_node))
	prefix = f"Q{question_num}: " if question_num else ""
	title = f"{prefix}{'[?] → ' + anchor_name if is_source_question else anchor_name + ' → [?]'}"

	return _assemble_diagram(
		title=title,
		node_ids=[anchor_node] + list(leaf_nodes),
		edge_pairs=edge_pairs,
		target_ids={anchor_node},
		common_source_ids=set(),
		common_effect_ids=set(),
		nodes_dict=nodes_dict,
		edge_values=edge_values,
		ignore_edge_colors=ignore_edge_colors,
		node_colors=node_colors
	)


def compute_earliest_generation_nodes(
	node_ids: Iterable[str],
	parents_map: Dict[str, List[str]],
	spouses_map: Dict[str, Set[str]],
	merged_nodes: Optional[Dict[str, List[str]]] = None,
) -> Set[str]:
	node_set = set(node_ids)
	if not node_set:
		return set()

	merged = merged_nodes or {}
	orig_to_diag: Dict[str, str] = {}
	for nid in node_set:
		for orig_id in merged.get(nid, [nid]):
			orig_to_diag[orig_id] = nid

	adj: Dict[str, Set[Tuple[str, int]]] = {nid: set() for nid in node_set}
	for diag_child in node_set:
		for orig_child in merged.get(diag_child, [diag_child]):
			for orig_parent in parents_map.get(orig_child, []):
				diag_parent = orig_to_diag.get(orig_parent)
				if diag_parent in node_set and diag_parent != diag_child:
					adj[diag_parent].add((diag_child, 1))
					adj[diag_child].add((diag_parent, -1))
			for orig_spouse in spouses_map.get(orig_child, set()):
				diag_spouse = orig_to_diag.get(orig_spouse)
				if diag_spouse in node_set and diag_spouse != diag_child:
					adj[diag_child].add((diag_spouse, 0))
					adj[diag_spouse].add((diag_child, 0))

	gen: Dict[str, int] = {}
	for start in node_set:
		if start in gen:
			continue
		gen[start] = 0
		q = deque([start])
		while q:
			curr = q.popleft()
			for nxt, delta in adj[curr]:
				if nxt not in gen:
					gen[nxt] = gen[curr] + delta
					q.append(nxt)

	min_gen = min(gen.values())
	return {nid for nid, g_val in gen.items() if g_val == min_gen}


def build_family_pair_diagram(
	u: str,
	v: str,
	graph,
	nodes_dict: Dict[str, str],
	parents_map: Dict[str, List[str]],
	children_map: Dict[str, List[str]],
	spouses_map: Dict[str, Set[str]],
	ancestor_paths: dict,
	ancestor_dist: dict,
	question_num: int = 0,
	node_colors: Optional[Dict[str, str]] = None,
) -> GraphDiagramData:
	target_ids = {u, v}
	common_source_ids: Set[str] = set()
	common_effect_ids: Set[str] = set()
	edge_pairs: List[Tuple[str, str]] = []
	spouse_pairs: Set[Tuple[str, str]] = set()

	def add_spouse_edge(a: str, b: str):
		if (a, b) in spouse_pairs or (b, a) in spouse_pairs:
			return
		pair = (b, a) if (graph.has_edge(b, a) and not graph.has_edge(a, b)) else (a, b)
		spouse_pairs.add(pair)
		edge_pairs.append(pair)

	dist_u = ancestor_dist.get(u, {})
	dist_v = ancestor_dist.get(v, {})
	common_anc = set(dist_u.keys()).intersection(dist_v.keys())
	if common_anc:
		mrcas = [a for a in common_anc if not any(c in common_anc for c in children_map.get(a, []))]
		mrcas.sort(key=lambda a: (dist_u[a] + dist_v[a], str(nodes_dict.get(a, a))))
		for a in mrcas:
			if dist_u[a] == 1 and dist_v[a] == 1:
				common_source_ids.add(a)
			for p in ancestor_paths[u][a][:1] + ancestor_paths[v][a][:1]:
				for k in range(len(p) - 1):
					edge_pairs.append((p[k], p[k + 1]))

	shared_children = set(children_map.get(u, [])).intersection(children_map.get(v, []))
	for c in shared_children:
		common_effect_ids.add(c)
		edge_pairs.append((u, c))
		edge_pairs.append((v, c))

	if v in spouses_map.get(u, set()):
		add_spouse_edge(u, v)

	if not edge_pairs:
		for s_v in spouses_map.get(v, set()):
			s_dist = ancestor_dist.get(s_v, {})
			s_ca = set(dist_u.keys()).intersection(s_dist.keys())
			if s_ca:
				add_spouse_edge(s_v, v)
				s_mrcas = [a for a in s_ca if not any(c in s_ca for c in children_map.get(a, []))]
				s_mrcas.sort(key=lambda a: (dist_u[a] + s_dist[a], str(nodes_dict.get(a, a))))
				for a in s_mrcas:
					for p in ancestor_paths[u][a][:1] + ancestor_paths[s_v][a][:1]:
						for k in range(len(p) - 1):
							edge_pairs.append((p[k], p[k + 1]))
				break

	if not edge_pairs:
		for s_u in spouses_map.get(u, set()):
			s_dist = ancestor_dist.get(s_u, {})
			s_ca = set(dist_v.keys()).intersection(s_dist.keys())
			if s_ca:
				add_spouse_edge(u, s_u)
				s_mrcas = [a for a in s_ca if not any(c in s_ca for c in children_map.get(a, []))]
				s_mrcas.sort(key=lambda a: (dist_v[a] + s_dist[a], str(nodes_dict.get(a, a))))
				for a in s_mrcas:
					for p in ancestor_paths[v][a][:1] + ancestor_paths[s_u][a][:1]:
						for k in range(len(p) - 1):
							edge_pairs.append((p[k], p[k + 1]))
				break

	if not edge_pairs:
		for c_u in children_map.get(u, []):
			for c_v in children_map.get(v, []):
				if c_v in spouses_map.get(c_u, set()):
					edge_pairs.append((u, c_u))
					edge_pairs.append((v, c_v))
					add_spouse_edge(c_u, c_v)

	if not edge_pairs:
		for p_u in parents_map.get(u, []):
			for p_v in parents_map.get(v, []):
				if p_v in spouses_map.get(p_u, set()):
					edge_pairs.append((p_u, u))
					edge_pairs.append((p_v, v))
					add_spouse_edge(p_u, p_v)

	# Collect deduplicated nodes & directed/spouse connectivity before merging eligible spouses
	all_node_ids: List[str] = [u, v]
	dedup_edges: List[Tuple[str, str]] = []
	seen_edges: Set[Tuple[str, str]] = set()
	for src, dst in edge_pairs:
		if src == dst:
			continue
		if src not in all_node_ids:
			all_node_ids.append(src)
		if dst not in all_node_ids:
			all_node_ids.append(dst)
		if (src, dst) not in seen_edges:
			seen_edges.add((src, dst))
			dedup_edges.append((src, dst))

	out_map: Dict[str, Set[str]] = {nid: set() for nid in all_node_ids}
	in_map: Dict[str, Set[str]] = {nid: set() for nid in all_node_ids}
	bidir_map: Dict[str, Set[str]] = {nid: set() for nid in all_node_ids}
	for src, dst in dedup_edges:
		if (src, dst) in spouse_pairs:
			bidir_map[src].add(dst)
			bidir_map[dst].add(src)
		else:
			out_map[src].add(dst)
			in_map[dst].add(src)

	def _format_spouse_pair_label(a: str, b: str) -> str:
		name_a = str(nodes_dict.get(a, a))
		name_b = str(nodes_dict.get(b, b))
		ga = detect_gender((node_colors or {}).get(a, ''))
		gb = detect_gender((node_colors or {}).get(b, ''))
		if ga == 'F' and gb != 'F':
			first_name, second_name = name_b, name_a
		elif gb == 'F' and ga != 'F':
			first_name, second_name = name_a, name_b
		elif ga == 'M' and gb != 'M':
			first_name, second_name = name_a, name_b
		elif gb == 'M' and ga != 'M':
			first_name, second_name = name_b, name_a
		elif name_a.lower() <= name_b.lower():
			first_name, second_name = name_a, name_b
		else:
			first_name, second_name = name_b, name_a
		return f"{first_name}\n+ {second_name}"

	id_remap: Dict[str, str] = {}
	merged_nodes: Dict[str, List[str]] = {}
	effective_nodes_dict = dict(nodes_dict)
	effective_node_colors = dict(node_colors or {})

	for i in range(len(all_node_ids)):
		a = all_node_ids[i]
		if a in id_remap or a in target_ids:
			continue
		if not out_map[a]:
			continue
		for j in range(i + 1, len(all_node_ids)):
			b = all_node_ids[j]
			if b in id_remap or b in target_ids:
				continue
			if b not in spouses_map.get(a, set()):
				continue
			if (out_map[a] - {b}) != (out_map[b] - {a}):
				continue
			if (in_map[a] - {b}) != (in_map[b] - {a}):
				continue
			if (bidir_map[a] - {b}) or (bidir_map[b] - {a}):
				continue

			merged_id = f"{a}__spouse__{b}"
			id_remap[a] = merged_id
			id_remap[b] = merged_id
			merged_nodes[merged_id] = [a, b]
			effective_nodes_dict[merged_id] = _format_spouse_pair_label(a, b)
			effective_node_colors[merged_id] = COLOR_SPOUSE_GREEN
			break

	remapped_node_ids = list(dict.fromkeys(id_remap.get(nid, nid) for nid in all_node_ids))
	remapped_edges = [
		(id_remap.get(src, src), id_remap.get(dst, dst))
		for src, dst in dedup_edges
		if id_remap.get(src, src) != id_remap.get(dst, dst)
	]
	remapped_spouse_pairs = {
		(id_remap.get(src, src), id_remap.get(dst, dst))
		for src, dst in spouse_pairs
		if id_remap.get(src, src) != id_remap.get(dst, dst)
	}
	remapped_common_sources = (
		{id_remap.get(nid, nid) for nid in common_source_ids} - target_ids - set(merged_nodes.keys())
	)
	remapped_common_effects = (
		{id_remap.get(nid, nid) for nid in common_effect_ids} - target_ids - set(merged_nodes.keys())
	)

	u_name = nodes_dict.get(u, str(u))
	v_name = nodes_dict.get(v, str(v))
	prefix = f"Q{question_num}: " if question_num else ""
	title = f"{prefix}{u_name} ↔ {v_name}"

	return _assemble_diagram(
		title=title,
		node_ids=remapped_node_ids,
		edge_pairs=remapped_edges,
		target_ids=target_ids,
		common_source_ids=remapped_common_sources,
		common_effect_ids=remapped_common_effects,
		nodes_dict=effective_nodes_dict,
		edge_values={},
		ignore_edge_colors=True,
		bidirectional_edges=remapped_spouse_pairs,
		node_colors=effective_node_colors,
		merged_nodes=merged_nodes,
	)

def compute_circular_layout(
	diagram: GraphDiagramData,
	width: float,
	height: float,
	node_sizes: Dict[str, Tuple[float, float]],
	margin: float = 16.0,
	flip_y: bool = False,
) -> Dict[str, Tuple[float, float, float, float]]:
	"""
	Positions nodes on a circle/ellipse centered in (width, height).
	Returns node_id -> (cx, cy, w, h).
	"""
	nodes = diagram.nodes
	n = len(nodes)
	if n == 0:
		return {}

	max_w = max(node_sizes[node.node_id][0] for node in nodes)
	max_h = max(node_sizes[node.node_id][1] for node in nodes)

	rx_avail = max(10.0, (width - max_w) / 2.0 - margin)
	ry_avail = max(10.0, (height - max_h) / 2.0 - margin)
	rx = min(rx_avail, ry_avail * 2.2)
	ry = ry_avail

	cx_center = width / 2.0
	cy_center = height / 2.0
	rects: Dict[str, Tuple[float, float, float, float]] = {}

	for idx, node in enumerate(nodes):
		nw, nh = node_sizes[node.node_id]
		if n == 1:
			cx, cy = cx_center, cy_center
		elif n == 2:
			angle = math.pi if idx == 0 else 0.0
			cx = cx_center + rx_avail * math.cos(angle)
			cy = cy_center
		else:
			angle = -math.pi / 2.0 + (2.0 * math.pi * idx) / n
			cx = cx_center + rx * math.cos(angle)
			dy = ry * math.sin(angle)
			cy = (cy_center - dy) if flip_y else (cy_center + dy)

		cx = max(nw / 2.0 + margin * 0.5, min(width - nw / 2.0 - margin * 0.5, cx))
		cy = max(nh / 2.0 + margin * 0.5, min(height - nh / 2.0 - margin * 0.5, cy))
		rects[node.node_id] = (cx, cy, nw, nh)

	# Resolve any remaining box overlaps on compact viewports
	if n >= 2:
		node_ids = [node.node_id for node in nodes]
		pad = 6.0
		for _ in range(12):
			moved = False
			for i in range(n):
				id1 = node_ids[i]
				cx1, cy1, w1, h1 = rects[id1]
				for j in range(i + 1, n):
					id2 = node_ids[j]
					cx2, cy2, w2, h2 = rects[id2]
					dx = cx2 - cx1
					dy = cy2 - cy1
					req_x = (w1 + w2) / 2.0 + pad
					req_y = (h1 + h2) / 2.0 + pad
					ox = req_x - abs(dx)
					oy = req_y - abs(dy)
					if ox > 0 and oy > 0:
						moved = True
						if ox <= oy * 1.4:
							sgn = 1.0 if dx >= 0 else -1.0
							shift = ox / 2.0
							cx1 -= sgn * shift
							cx2 += sgn * shift
						else:
							sgn = 1.0 if dy >= 0 else -1.0
							shift = oy / 2.0
							cy1 -= sgn * shift
							cy2 += sgn * shift
						cx1 = max(w1 / 2.0 + margin * 0.5, min(width - w1 / 2.0 - margin * 0.5, cx1))
						cy1 = max(h1 / 2.0 + margin * 0.5, min(height - h1 / 2.0 - margin * 0.5, cy1))
						cx2 = max(w2 / 2.0 + margin * 0.5, min(width - w2 / 2.0 - margin * 0.5, cx2))
						cy2 = max(h2 / 2.0 + margin * 0.5, min(height - h2 / 2.0 - margin * 0.5, cy2))
						rects[id1] = (cx1, cy1, w1, h1)
						rects[id2] = (cx2, cy2, w2, h2)
			if not moved:
				break

	return rects


def _ray_rect_exit(
	ox: float,
	oy: float,
	vx: float,
	vy: float,
	cx: float,
	cy: float,
	hw: float,
	hh: float,
) -> Tuple[float, float]:
	t_candidates: List[float] = []
	if vx > 1e-9:
		t_candidates.append((cx + hw - ox) / vx)
	elif vx < -1e-9:
		t_candidates.append((cx - hw - ox) / vx)
	if vy > 1e-9:
		t_candidates.append((cy + hh - oy) / vy)
	elif vy < -1e-9:
		t_candidates.append((cy - hh - oy) / vy)

	valid = [t for t in t_candidates if t >= 0.0]
	t = min(valid) if valid else 0.0
	return ox + t * vx, oy + t * vy


def compute_edge_geometry(
	diagram: GraphDiagramData,
	rects: Dict[str, Tuple[float, float, float, float]],
	parallel_offset: float = 7.0,
	target_pad: float = 1.0,
) -> List[Tuple[DiagramEdge, float, float, float, float, float, float]]:
	"""
	Computes clipped start/end points on rectangle boundaries for each edge.
	Returns list of (edge, x1, y1, x2, y2, ux, uy).
	"""
	edge_set = {(e.source_id, e.target_id) for e in diagram.edges}
	result: List[Tuple[DiagramEdge, float, float, float, float, float, float]] = []

	for edge in diagram.edges:
		if edge.source_id not in rects or edge.target_id not in rects:
			continue
		cx1, cy1, w1, h1 = rects[edge.source_id]
		cx2, cy2, w2, h2 = rects[edge.target_id]

		dx = cx2 - cx1
		dy = cy2 - cy1
		dist = math.hypot(dx, dy)
		if dist < 1e-3:
			continue

		ux = dx / dist
		uy = dy / dist

		if (edge.target_id, edge.source_id) in edge_set:
			shift = min(parallel_offset, 0.32 * min(w1, h1, w2, h2))
			px = -uy * shift
			py = ux * shift
		else:
			px = 0.0
			py = 0.0

		ox1, oy1 = cx1 + px, cy1 + py
		ox2, oy2 = cx2 + px, cy2 + py

		x1, y1 = _ray_rect_exit(
			ox1, oy1, ux, uy, cx1, cy1,
			w1 / 2.0 + (target_pad if edge.bidirectional else 0.0),
			h1 / 2.0 + (target_pad if edge.bidirectional else 0.0),
		)
		x2, y2 = _ray_rect_exit(ox2, oy2, -ux, -uy, cx2, cy2, w2 / 2.0 + target_pad, h2 / 2.0 + target_pad)

		# Skip inverted arrows if boxes overlap on a tiny viewport
		if (x2 - x1) * ux + (y2 - y1) * uy <= 2.0:
			continue

		result.append((edge, x1, y1, x2, y2, ux, uy))

	return result

def _build_diagram_cycle(
	cyc: List[str],
	edge_values: Dict[Tuple[str, str], int],
	ignore_edge_colors: bool,
	is_secondary: bool = False,
) -> DiagramCycle:
	cyc_edges = {(cyc[k], cyc[k + 1]) for k in range(len(cyc) - 1)}
	if ignore_edge_colors:
		polarity = None
	else:
		corr = 1
		for k in range(len(cyc) - 1):
			corr *= edge_values.get((cyc[k], cyc[k + 1]), 1)
		polarity = 1 if corr > 0 else -1
	return DiagramCycle(
		node_ids=list(dict.fromkeys(cyc)),
		edges=cyc_edges,
		polarity=polarity,
		is_secondary=is_secondary,
	)


def build_pair_diagram(
	u: str,
	v: str,
	nodes_dict: Dict[str, str],
	edge_values: Dict[Tuple[str, str], int],
	shared_srcs: List[str],
	shared_dsts: List[str],
	paths_u_v: List[List[str]],
	paths_v_u: List[List[str]],
	pair_cycles: List[List[str]],
	secondary_cycles: Optional[List[List[str]]] = None,
	ignore_edge_colors: bool = False,
	question_num: int = 0,
	node_colors: Optional[Dict[str, str]] = None,
) -> GraphDiagramData:
	target_ids = {u, v}
	common_source_ids = set(shared_srcs) - target_ids
	common_effect_ids = set(shared_dsts) - target_ids

	sec_cycles = secondary_cycles or []

	edge_pairs: List[Tuple[str, str]] = []
	for s in shared_srcs:
		edge_pairs.append((s, u))
		edge_pairs.append((s, v))
	for d in shared_dsts:
		edge_pairs.append((u, d))
		edge_pairs.append((v, d))
	for path in paths_u_v + paths_v_u + pair_cycles + sec_cycles:
		for k in range(len(path) - 1):
			edge_pairs.append((path[k], path[k + 1]))

	diagram_cycles: List[DiagramCycle] = []
	seen_edge_sets: Set[frozenset] = set()
	for cyc in pair_cycles:
		dc = _build_diagram_cycle(cyc, edge_values, ignore_edge_colors, is_secondary=False)
		key = frozenset(dc.edges)
		if key not in seen_edge_sets:
			seen_edge_sets.add(key)
			diagram_cycles.append(dc)
	for cyc in sec_cycles:
		dc = _build_diagram_cycle(cyc, edge_values, ignore_edge_colors, is_secondary=True)
		key = frozenset(dc.edges)
		if key not in seen_edge_sets:
			seen_edge_sets.add(key)
			diagram_cycles.append(dc)

	u_name = nodes_dict.get(u, str(u))
	v_name = nodes_dict.get(v, str(v))
	prefix = f"Q{question_num}: " if question_num else ""
	title = f"{prefix}{u_name} ↔ {v_name}"

	return _assemble_diagram(
		title=title,
		node_ids=[u, v] + list(shared_srcs) + list(shared_dsts),
		edge_pairs=edge_pairs,
		target_ids=target_ids,
		common_source_ids=common_source_ids,
		common_effect_ids=common_effect_ids,
		nodes_dict=nodes_dict,
		edge_values=edge_values,
		ignore_edge_colors=ignore_edge_colors,
		cycles=diagram_cycles,
		node_colors=node_colors
	)