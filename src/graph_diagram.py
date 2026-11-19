import os
import textwrap
from dataclasses import dataclass
import math
from typing import Dict, Iterable, List, Optional, Set, Tuple

COLOR_GOLD = '#FFCC00'
COLOR_BLACK = '#000000'
COLOR_WHITE = '#FFFFFF'
COLOR_PINK = '#FF99CC'
COLOR_BLUE = '#00CCFF'
COLOR_RED = '#FF0000'
NODE_WRAP_CHAR_THRESHOLD = 18


def format_graph_node_label(label: str, max_chars_per_line: int = NODE_WRAP_CHAR_THRESHOLD) -> str:
	"""
	Formats a graph node label for visual rendering:
	- Any '→' starts on a new line beginning with '→'.
	- Lines longer than `max_chars_per_line` wrap cleanly.
	"""
	text = str(label or "").strip()
	if not text:
		return ""

	segments: List[str] = []
	if '→' in text:
		parts = text.split('→')
		first = parts[0].strip()
		if first:
			segments.append(first)
		for part in parts[1:]:
			part_clean = part.strip()
			segments.append(f"→ {part_clean}" if part_clean else "→")
	else:
		segments.append(text)

	wrapped_lines: List[str] = []
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


@dataclass
class DiagramEdge:
	source_id: str
	target_id: str
	correlation: int  # +1 -> black arrow, -1 -> red arrow
	color: str


@dataclass
class GraphDiagramData:
	title: str
	nodes: List[DiagramNode]
	edges: List[DiagramEdge]



@dataclass
class AnswerHighlight:
	node_ids: Set[str]
	edges: Set[Tuple[str, str]]
	is_cycle: bool = False
	cycle_polarity: Optional[int] = None  # +1 reinforcing (+), -1 balancing (-), None if ignored/neutral
	cycle_node_ids: Optional[List[str]] = None
	diagram: Optional[GraphDiagramData] = None


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

def _make_diagram_node(
	node_id: str,
	label: str,
	target_ids: Set[str],
	common_source_ids: Set[str],
	common_effect_ids: Set[str],
) -> DiagramNode:
	if node_id in target_ids:
		return DiagramNode(node_id, label, 'target', COLOR_BLACK, COLOR_WHITE)
	if node_id in common_source_ids:
		return DiagramNode(node_id, label, 'common_source', COLOR_PINK, COLOR_BLACK)
	if node_id in common_effect_ids:
		return DiagramNode(node_id, label, 'common_effect', COLOR_BLUE, COLOR_BLACK)
	return DiagramNode(node_id, label, 'default', COLOR_GOLD, COLOR_BLACK)


def _compute_circular_order(
	node_ids: Iterable[str],
	edge_pairs: List[Tuple[str, str]],
	target_ids: Set[str],
	nodes_dict: Dict[str, str],
) -> List[str]:
	unique_ids = list(dict.fromkeys(node_ids))
	if len(unique_ids) <= 2:
		return unique_ids

	adj: Dict[str, List[str]] = {nid: [] for nid in unique_ids}
	for u, v in edge_pairs:
		if u in adj and v in adj and u != v:
			if v not in adj[u]:
				adj[u].append(v)
			if u not in adj[v]:
				adj[v].append(u)

	for nid in adj:
		adj[nid].sort(key=lambda x: str(nodes_dict.get(x, x)).lower())

	remaining = sorted(
		unique_ids,
		key=lambda x: (0 if x in target_ids else 1, str(nodes_dict.get(x, x)).lower()),
	)

	ordered: List[str] = []
	visited: Set[str] = set()

	def dfs(curr: str):
		visited.add(curr)
		ordered.append(curr)
		for nxt in adj[curr]:
			if nxt not in visited:
				dfs(nxt)

	for start in remaining:
		if start not in visited:
			dfs(start)

	return ordered


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
) -> GraphDiagramData:
	seen_edges: Set[Tuple[str, str]] = set()
	dedup_edges: List[Tuple[str, str]] = []
	all_node_ids = list(node_ids)

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
		)
		for nid in ordered_ids
	]

	diagram_edges: List[DiagramEdge] = []
	for u, v in dedup_edges:
		corr = 1 if ignore_edge_colors else edge_values.get((u, v), 1)
		arrow_color = COLOR_BLACK if corr > 0 else COLOR_RED
		diagram_edges.append(DiagramEdge(u, v, corr, arrow_color))

	return GraphDiagramData(title=title, nodes=diagram_nodes, edges=diagram_edges)


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
	ignore_edge_colors: bool = False,
	question_num: int = 0,
) -> GraphDiagramData:
	target_ids = {u, v}
	common_source_ids = set(shared_srcs) - target_ids
	common_effect_ids = set(shared_dsts) - target_ids

	edge_pairs: List[Tuple[str, str]] = []
	for s in shared_srcs:
		edge_pairs.append((s, u))
		edge_pairs.append((s, v))
	for d in shared_dsts:
		edge_pairs.append((u, d))
		edge_pairs.append((v, d))
	for path in paths_u_v + paths_v_u + pair_cycles:
		for k in range(len(path) - 1):
			edge_pairs.append((path[k], path[k + 1]))

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
	)


def build_cycle_diagram(
	paths: List[List[str]],
	answer_node_ids: Set[str],
	nodes_dict: Dict[str, str],
	edge_values: Dict[Tuple[str, str], int],
	ignore_edge_colors: bool = False,
	question_num: int = 0,
) -> GraphDiagramData:
	edge_pairs: List[Tuple[str, str]] = []
	node_ids: List[str] = []
	for path in paths:
		for nid in path:
			if nid not in node_ids:
				node_ids.append(nid)
		for k in range(len(path) - 1):
			edge_pairs.append((path[k], path[k + 1]))

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
	)


def build_leaf_diagram(
	anchor_node: str,
	leaf_nodes: List[str],
	is_source_question: bool,
	nodes_dict: Dict[str, str],
	edge_values: Dict[Tuple[str, str], int],
	ignore_edge_colors: bool = False,
	question_num: int = 0,
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
	)


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
) -> GraphDiagramData:
	target_ids = {u, v}
	common_source_ids: Set[str] = set()
	common_effect_ids: Set[str] = set()
	edge_pairs: List[Tuple[str, str]] = []

	def add_graph_edge(a: str, b: str):
		if graph.has_edge(a, b):
			edge_pairs.append((a, b))
		elif graph.has_edge(b, a):
			edge_pairs.append((b, a))
		else:
			edge_pairs.append((a, b))

	dist_u = ancestor_dist.get(u, {})
	dist_v = ancestor_dist.get(v, {})
	common_anc = set(dist_u.keys()).intersection(dist_v.keys())
	if common_anc:
		mrcas = [a for a in common_anc if not any(c in common_anc for c in children_map.get(a, []))]
		mrcas.sort(key=lambda a: (dist_u[a] + dist_v[a], str(nodes_dict.get(a, a))))
		for a in mrcas[:2]:
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
		add_graph_edge(u, v)

	if not edge_pairs:
		for s_v in spouses_map.get(v, set()):
			s_dist = ancestor_dist.get(s_v, {})
			s_ca = set(dist_u.keys()).intersection(s_dist.keys())
			if s_ca:
				add_graph_edge(s_v, v)
				s_mrcas = [a for a in s_ca if not any(c in s_ca for c in children_map.get(a, []))]
				for a in s_mrcas[:1]:
					for p in ancestor_paths[u][a][:1] + ancestor_paths[s_v][a][:1]:
						for k in range(len(p) - 1):
							edge_pairs.append((p[k], p[k + 1]))
				break

	if not edge_pairs:
		for s_u in spouses_map.get(u, set()):
			s_dist = ancestor_dist.get(s_u, {})
			s_ca = set(dist_v.keys()).intersection(s_dist.keys())
			if s_ca:
				add_graph_edge(u, s_u)
				s_mrcas = [a for a in s_ca if not any(c in s_ca for c in children_map.get(a, []))]
				for a in s_mrcas[:1]:
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
					add_graph_edge(c_u, c_v)

	if not edge_pairs:
		for p_u in parents_map.get(u, []):
			for p_v in parents_map.get(v, []):
				if p_v in spouses_map.get(p_u, set()):
					edge_pairs.append((p_u, u))
					edge_pairs.append((p_v, v))
					add_graph_edge(p_u, p_v)

	u_name = nodes_dict.get(u, str(u))
	v_name = nodes_dict.get(v, str(v))
	prefix = f"Q{question_num}: " if question_num else ""
	title = f"{prefix}{u_name} ↔ {v_name}"

	return _assemble_diagram(
		title=title,
		node_ids=[u, v],
		edge_pairs=edge_pairs,
		target_ids=target_ids,
		common_source_ids=common_source_ids - target_ids,
		common_effect_ids=common_effect_ids - target_ids,
		nodes_dict=nodes_dict,
		edge_values={},
		ignore_edge_colors=True,
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

		x1, y1 = _ray_rect_exit(ox1, oy1, ux, uy, cx1, cy1, w1 / 2.0, h1 / 2.0)
		x2, y2 = _ray_rect_exit(ox2, oy2, -ux, -uy, cx2, cy2, w2 / 2.0 + target_pad, h2 / 2.0 + target_pad)

		# Skip inverted arrows if boxes overlap on a tiny viewport
		if (x2 - x1) * ux + (y2 - y1) * uy <= 2.0:
			continue

		result.append((edge, x1, y1, x2, y2, ux, uy))

	return result