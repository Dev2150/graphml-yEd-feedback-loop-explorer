from collections import deque
from typing import Dict, Iterable, List, Optional, Set, Tuple

from src.diagram.layout import compute_circular_order
from src.diagram.models import (
	COLOR_BLACK,
	COLOR_BLUE,
	COLOR_DARK_GREEN,
	COLOR_GOLD,
	COLOR_PINK,
	COLOR_RED,
	COLOR_SPOUSE_GREEN,
	COLOR_WHITE,
	AnswerHighlight,
	DiagramCycle,
	DiagramEdge,
	DiagramNode,
	GraphDiagramData,
)
from src.io_graphml import detect_gender

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

	ordered_ids = compute_circular_order(all_node_ids, dedup_edges, target_ids, nodes_dict)
	diagram_nodes = [
		_make_diagram_node(
			nid,
			str(nodes_dict.get(nid, nid)),
			target_ids,
			common_source_ids,
			common_effect_ids,
			node_colors,
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


def build_cycle_diagram(
	paths: List[List[str]],
	answer_node_ids: Set[str],
	nodes_dict: Dict[str, str],
	edge_values: Dict[Tuple[str, str], int],
	ignore_edge_colors: bool = False,
	question_num: int = 0,
	node_colors: Optional[Dict[str, str]] = None,
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
	ans_names = ", ".join(
		str(nodes_dict.get(nid, nid))
		for nid in sorted(answer_node_ids, key=lambda x: str(nodes_dict.get(x, x)).lower())
	)
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
		node_colors=node_colors,
	)


def build_leaf_diagram(
	anchor_node: str,
	leaf_nodes: List[str],
	is_source_question: bool,
	nodes_dict: Dict[str, str],
	edge_values: Dict[Tuple[str, str], int],
	ignore_edge_colors: bool = False,
	question_num: int = 0,
	node_colors: Optional[Dict[str, str]] = None,
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
		node_colors=node_colors,
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
		node_colors=node_colors,
	)

def build_family_shared_children_diagram(
	x: str,
	partners: List[str],
	children_ids: List[str],
	graph,
	nodes_dict: Dict[str, str],
	spouses_map: Dict[str, Set[str]],
	question_num: int = 0,
	node_colors: Optional[Dict[str, str]] = None,
) -> GraphDiagramData:
	edge_pairs: List[Tuple[str, str]] = []
	spouse_pairs: Set[Tuple[str, str]] = set()

	for c in children_ids:
		edge_pairs.append((x, c))
		for y in partners:
			edge_pairs.append((y, c))

	for y in partners:
		if y in spouses_map.get(x, set()):
			pair = (y, x) if (graph.has_edge(y, x) and not graph.has_edge(x, y)) else (x, y)
			spouse_pairs.add(pair)
			edge_pairs.append(pair)

	x_name = nodes_dict.get(x, str(x))
	prefix = f"Q{question_num}: " if question_num else ""
	title = f"{prefix}{x_name} & [?]"

	return _assemble_diagram(
		title=title,
		node_ids=[x] + list(partners) + list(children_ids),
		edge_pairs=edge_pairs,
		target_ids={x},
		common_source_ids=set(),
		common_effect_ids=set(children_ids) - {x},
		nodes_dict=nodes_dict,
		edge_values={},
		ignore_edge_colors=True,
		bidirectional_edges=spouse_pairs,
		node_colors=node_colors,
	)


def build_family_together_diagram(
	x: str,
	partners: List[str],
	graph,
	nodes_dict: Dict[str, str],
	question_num: int = 0,
	node_colors: Optional[Dict[str, str]] = None,
) -> GraphDiagramData:
	edge_pairs: List[Tuple[str, str]] = []
	spouse_pairs: Set[Tuple[str, str]] = set()

	for y in partners:
		pair = (y, x) if (graph.has_edge(y, x) and not graph.has_edge(x, y)) else (x, y)
		spouse_pairs.add(pair)
		edge_pairs.append(pair)

	x_name = nodes_dict.get(x, str(x))
	prefix = f"Q{question_num}: " if question_num else ""
	title = f"{prefix}{x_name} ↔ [?]"

	return _assemble_diagram(
		title=title,
		node_ids=[x] + list(partners),
		edge_pairs=edge_pairs,
		target_ids={x},
		common_source_ids=set(),
		common_effect_ids=set(),
		nodes_dict=nodes_dict,
		edge_values={},
		ignore_edge_colors=True,
		bidirectional_edges=spouse_pairs,
		node_colors=node_colors,
	)

def build_default_non_cycle_highlight(
	highlights: List[AnswerHighlight],
) -> Optional[AnswerHighlight]:
	"""
	Builds a combined default AnswerHighlight starting from the first non-cycle
	highlight and adding subsequent non-cycle highlights as long as they do not
	assign a conflicting polarity to any shared directed edge.
	"""
	non_cycle = [hl for hl in highlights if not hl.is_cycle and hl.edges]
	if not non_cycle:
		return None

	merged_nodes: Set[str] = set()
	merged_edges: Set[Tuple[str, str]] = set()
	merged_polarities: Dict[Tuple[str, str], int] = {}
	merged_first_nodes: Set[str] = set()
	diagram = non_cycle[0].diagram

	for hl in non_cycle:
		fights = False
		for edge in hl.edges:
			if edge in merged_edges:
				if merged_polarities.get(edge) != hl.edge_polarities.get(edge):
					fights = True
					break
		if fights:
			continue

		merged_nodes.update(hl.node_ids)
		merged_edges.update(hl.edges)
		for edge in hl.edges:
			if edge in hl.edge_polarities:
				merged_polarities[edge] = hl.edge_polarities[edge]
		if hl.first_node_ids:
			merged_first_nodes.update(hl.first_node_ids)
		if hl.first_node_id:
			merged_first_nodes.add(hl.first_node_id)

	if not merged_edges:
		return None

	return AnswerHighlight(
		node_ids=merged_nodes,
		edges=merged_edges,
		is_cycle=False,
		diagram=diagram,
		first_node_ids=merged_first_nodes,
		edge_polarities=merged_polarities,
	)

build_diagram_cycle = _build_diagram_cycle

def build_explorer_subgraph_diagram(
	title: str,
	anchor_id: str,
	node_ids: Iterable[str],
	edge_pairs: List[Tuple[str, str]],
	nodes_dict: Dict[str, str],
	edge_values: Dict[Tuple[str, str], int],
	ignore_edge_colors: bool = False,
	cycles: Optional[List[DiagramCycle]] = None,
	bidirectional_edges: Optional[Set[Tuple[str, str]]] = None,
	node_colors: Optional[Dict[str, str]] = None,
) -> GraphDiagramData:
	return _assemble_diagram(
		title=title,
		node_ids=node_ids,
		edge_pairs=edge_pairs,
		target_ids={anchor_id},
		common_source_ids=set(),
		common_effect_ids=set(),
		nodes_dict=nodes_dict,
		edge_values=edge_values,
		ignore_edge_colors=ignore_edge_colors,
		cycles=cycles,
		bidirectional_edges=bidirectional_edges,
		node_colors=node_colors,
	)