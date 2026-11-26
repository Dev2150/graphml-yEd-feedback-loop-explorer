from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from src.diagram import (
	AnswerHighlight,
	DiagramCycle,
	GraphDiagramData,
	build_default_non_cycle_highlight,
	build_diagram_cycle,
	build_explorer_subgraph_diagram,
)
from src.family import detect_gender, get_child_term, get_parent_term, get_spouse_term
from src.formatters import format_console_node_name, format_path_string, get_path_net_effect_arrow
from src.games.relationship.handlers.common import (
	compute_cycle_polarity,
	compute_path_edge_polarities,
	path_edges,
)
from src.games.relationship.handlers.pair_question import (
	build_family_pair_exploration,
	build_standard_pair_exploration,
)
from src.games.relationship.progress import get_canonical_cycle_tuple
from src.graph_utils import find_bounded_cycles
from src.models import GraphContext

EXPLORER_MODES = ("dual", "descendants", "ascendants", "neighborhood")
SINGLE_NODE_MODES = ("descendants", "ascendants", "neighborhood")
MAX_EXPLORER_PATHS = 200


@dataclass
class ExplorerResult:
	mode: str
	title: str
	diagram: Optional[GraphDiagramData]
	answer_lines: List[Tuple[str, Optional[AnswerHighlight]]]
	active_node_ids: List[str]


def _collect_subgraph_cycles(
	anchor_id: str,
	subgraph_nodes: Set[str],
	ctx: GraphContext,
	is_counter: bool,
	ignore_edge_colors: bool,
) -> Tuple[List[List[str]], List[List[str]], List[DiagramCycle]]:
	max_cyc = ctx.config.max_cycle_length_game
	include_sec = getattr(ctx.config, "include_secondary_cycles", True)
	if max_cyc < 2 or len(subgraph_nodes) < 2:
		return [], [], []

	nodes = ctx.nodes
	primary_cycles: List[List[str]] = []
	secondary_cycles: List[List[str]] = []
	seen_cyc = set()

	for cyc_nodes in find_bounded_cycles(ctx.graph.subgraph(subgraph_nodes), max_cyc):
		if len(cyc_nodes) < 2 or len(cyc_nodes) > max_cyc:
			continue
		canonical = tuple(get_canonical_cycle_tuple(cyc_nodes, nodes))
		if canonical in seen_cyc:
			continue
		seen_cyc.add(canonical)

		if anchor_id in cyc_nodes:
			idx = cyc_nodes.index(anchor_id)
			rotated = cyc_nodes[idx:] + cyc_nodes[:idx]
			primary_cycles.append(rotated + [rotated[0]])
		elif include_sec:
			rotated = list(canonical)
			secondary_cycles.append(rotated + [rotated[0]])

	primary_cycles.sort(key=lambda c: (len(c), [str(nodes.get(n, n)).lower() for n in c]))
	secondary_cycles.sort(key=lambda c: (len(c), [str(nodes.get(n, n)).lower() for n in c]))

	ignore_pol = is_counter or ignore_edge_colors
	diagram_cycles: List[DiagramCycle] = []
	for cyc in primary_cycles:
		diagram_cycles.append(build_diagram_cycle(cyc, ctx.edge_values, ignore_pol, is_secondary=False))
	for cyc in secondary_cycles:
		diagram_cycles.append(build_diagram_cycle(cyc, ctx.edge_values, ignore_pol, is_secondary=True))

	return primary_cycles, secondary_cycles, diagram_cycles


def _append_cycle_answers(
	answer_lines: List[Tuple[str, Optional[AnswerHighlight]]],
	cycles: List[List[str]],
	label_prefix: str,
	diagram: GraphDiagramData,
	ctx: GraphContext,
	is_counter: bool,
	ignore_edge_colors: bool,
):
	ignore_pol = is_counter or ignore_edge_colors
	for cyc in cycles:
		formatted = format_path_string(
			cyc,
			ctx.nodes,
			ctx.edge_values,
			ignore_edge_colors=ignore_edge_colors,
			is_counter=is_counter,
		)
		cyc_len = len(cyc) - 1
		polarity = compute_cycle_polarity(cyc, ctx.edge_values, ignore_pol)
		if polarity is None:
			line = f"{label_prefix} ({cyc_len}): {formatted}"
		else:
			icon = "[💥]" if polarity > 0 else "[⚖️]"
			line = f"{label_prefix} ({cyc_len}) {icon}: {formatted}"
		hl = AnswerHighlight(
			node_ids=set(cyc),
			edges=path_edges(cyc),
			is_cycle=True,
			cycle_polarity=polarity,
			cycle_node_ids=list(dict.fromkeys(cyc)),
			diagram=diagram,
		)
		diagram.highlights.append(hl)
		answer_lines.append((line, hl))


def _explore_dual(
	node_a_id: str,
	node_b_id: str,
	ctx: GraphContext,
	prepared_data: dict,
) -> ExplorerResult:
	u_name = format_console_node_name(ctx.nodes.get(node_a_id, str(node_a_id)))
	v_name = format_console_node_name(ctx.nodes.get(node_b_id, str(node_b_id)))
	title = f"Explore (Dual): {u_name} ↔ {v_name}"

	if prepared_data["is_family"]:
		diagram, entries, is_relevant = build_family_pair_exploration(
			node_a_id, node_b_id, ctx, prepared_data, question_num=0
		)
		if not is_relevant:
			answer_lines = [("IRRELEVANT (No blood or marriage relationship found)", None)]
		else:
			answer_lines = []
			lineage_added = False
			for kind, text, hl in entries:
				if kind == "lineage" and not lineage_added:
					answer_lines.append(("  Lineage:", hl))
					lineage_added = True
				answer_lines.append((text, hl))
	else:
		diagram, connection_entries = build_standard_pair_exploration(
			node_a_id, node_b_id, ctx, prepared_data, question_num=0
		)
		if not connection_entries:
			answer_lines = [("IRRELEVANT (no connection found within depth limits)", None)]
		elif len(connection_entries) == 1:
			answer_lines = [connection_entries[0]]
		else:
			answer_lines = [(f"  • {text}", hl) for text, hl in connection_entries]

	return ExplorerResult(
		mode="dual",
		title=title,
		diagram=diagram,
		answer_lines=answer_lines,
		active_node_ids=[node_a_id, node_b_id],
	)


def _explore_directional(
	mode: str,
	anchor_id: str,
	ctx: GraphContext,
	prepared_data: dict,
	max_depth: Optional[int],
) -> ExplorerResult:
	nodes = ctx.nodes
	edge_values = ctx.edge_values
	edge_labels = ctx.edge_labels
	is_counter = prepared_data["is_counter"]
	is_family = prepared_data["is_family"]
	ignore_edge_colors = prepared_data["ignore_edge_colors"]
	ignore_pol = is_counter or ignore_edge_colors
	is_descendants = (mode == "descendants")

	if max_depth is None:
		cutoff = max(1, ctx.config.max_indirectness + 1) if ctx.config.max_indirectness >= 0 else None
	elif max_depth <= 0:
		cutoff = None
	else:
		cutoff = int(max_depth)

	def _neighbors(nid: str) -> List[str]:
		if is_family:
			raw = prepared_data["children_map"].get(nid, []) if is_descendants else prepared_data["parents_map"].get(nid, [])
		else:
			raw = ctx.graph.successors(nid) if is_descendants else ctx.graph.predecessors(nid)
		return sorted(raw, key=lambda x: str(nodes.get(x, x)).lower())

	queue = deque([[anchor_id]])
	found_paths: List[List[str]] = []
	visited_nodes: Set[str] = {anchor_id}
	truncated = False

	while queue:
		path = queue.popleft()
		curr = path[-1]
		if cutoff is not None and (len(path) - 1) >= cutoff:
			continue
		for nxt in _neighbors(curr):
			if nxt == anchor_id or nxt in path:
				continue
			new_path = path + [nxt]
			visited_nodes.add(nxt)
			if len(found_paths) < MAX_EXPLORER_PATHS:
				found_paths.append(new_path if is_descendants else list(reversed(new_path)))
				queue.append(new_path)
			else:
				truncated = True

	primary_cycles: List[List[str]] = []
	secondary_cycles: List[List[str]] = []
	diagram_cycles: List[DiagramCycle] = []
	if not is_family:
		primary_cycles, secondary_cycles, diagram_cycles = _collect_subgraph_cycles(
			anchor_id, visited_nodes, ctx, is_counter, ignore_edge_colors
		)

	edge_pairs: List[Tuple[str, str]] = []
	for p in found_paths:
		for k in range(len(p) - 1):
			edge_pairs.append((p[k], p[k + 1]))
	for cyc in primary_cycles + secondary_cycles:
		for k in range(len(cyc) - 1):
			edge_pairs.append((cyc[k], cyc[k + 1]))

	a_name = format_console_node_name(nodes.get(anchor_id, str(anchor_id)))
	diag_title = f"{a_name} → Descendants" if is_descendants else f"Ascendants → {a_name}"
	title = f"Explore ({'Descendants' if is_descendants else 'Ascendants'}): {a_name}"

	diagram = build_explorer_subgraph_diagram(
		title=diag_title,
		anchor_id=anchor_id,
		node_ids=sorted(visited_nodes, key=lambda x: (0 if x == anchor_id else 1, str(nodes.get(x, x)).lower())),
		edge_pairs=edge_pairs,
		nodes_dict=nodes,
		edge_values=edge_values,
		ignore_edge_colors=is_counter or ignore_edge_colors,
		cycles=diagram_cycles,
		node_colors=ctx.node_colors,
	)

	answer_lines: List[Tuple[str, Optional[AnswerHighlight]]] = []
	for p in found_paths:
		formatted = format_path_string(
			p,
			nodes,
			edge_values,
			edge_labels=edge_labels if len(p) == 2 else None,
			ignore_edge_colors=ignore_edge_colors,
			is_counter=is_counter,
		)
		if len(p) == 2:
			line = f"Direct: {formatted}"
		else:
			suffix = "" if ignore_pol else f" ({get_path_net_effect_arrow(p, edge_values)})"
			kind_lbl = "Descendant" if is_descendants else "Ascendant"
			line = f"{kind_lbl} ({len(p) - 2}): {formatted}{suffix}"

		edge_pols = compute_path_edge_polarities(p, edge_values, ignore_pol)
		hl = AnswerHighlight(
			node_ids=set(p),
			edges=path_edges(p),
			diagram=diagram,
			first_node_id=p[0],
			edge_polarities=edge_pols,
		)
		diagram.highlights.append(hl)
		answer_lines.append((line, hl))

	_append_cycle_answers(answer_lines, primary_cycles, "Cycle", diagram, ctx, is_counter, ignore_edge_colors)
	_append_cycle_answers(answer_lines, secondary_cycles, "Secondary cycle", diagram, ctx, is_counter, ignore_edge_colors)

	diagram.default_highlight = build_default_non_cycle_highlight(diagram.highlights)

	if truncated:
		answer_lines.append((f"... (showing first {MAX_EXPLORER_PATHS} paths)", None))
	if not answer_lines:
		noun = "descendants" if is_descendants else "ascendants"
		answer_lines.append((f"No {noun} found for {a_name}.", None))

	return ExplorerResult(
		mode=mode,
		title=title,
		diagram=diagram,
		answer_lines=answer_lines,
		active_node_ids=[anchor_id],
	)


def _explore_neighborhood(
	anchor_id: str,
	ctx: GraphContext,
	prepared_data: dict,
) -> ExplorerResult:
	nodes = ctx.nodes
	edge_values = ctx.edge_values
	edge_labels = ctx.edge_labels
	node_colors = ctx.node_colors
	is_counter = prepared_data["is_counter"]
	is_family = prepared_data["is_family"]
	ignore_edge_colors = prepared_data["ignore_edge_colors"]
	ignore_pol = is_counter or ignore_edge_colors

	a_name = format_console_node_name(nodes.get(anchor_id, str(anchor_id)))
	diag_title = f"Neighborhood: {a_name}"
	title = f"Explore (Neighborhood): {a_name}"

	if is_family:
		parents_map = prepared_data["parents_map"]
		children_map = prepared_data["children_map"]
		spouses_map = prepared_data["spouses_map"]

		preds = sorted(parents_map.get(anchor_id, []), key=lambda x: str(nodes.get(x, x)).lower())
		succs = sorted(children_map.get(anchor_id, []), key=lambda x: str(nodes.get(x, x)).lower())
		spouses = sorted(spouses_map.get(anchor_id, set()), key=lambda x: str(nodes.get(x, x)).lower())

		nb_nodes = list(dict.fromkeys([anchor_id] + spouses + preds + succs))
		edge_pairs: List[Tuple[str, str]] = []
		bidirectional_edges: Set[Tuple[str, str]] = set()

		def _spouse_pair(a: str, b: str) -> Tuple[str, str]:
			return (b, a) if (ctx.graph.has_edge(b, a) and not ctx.graph.has_edge(a, b)) else (a, b)

		for sp in spouses:
			pair = _spouse_pair(anchor_id, sp)
			edge_pairs.append(pair)
			bidirectional_edges.add(pair)

		for p in preds:
			edge_pairs.append((p, anchor_id))
		for c in succs:
			edge_pairs.append((anchor_id, c))

		# Include co-parent / spouse links among anchor's parents
		for i in range(len(preds)):
			for j in range(i + 1, len(preds)):
				p1, p2 = preds[i], preds[j]
				if p2 in spouses_map.get(p1, set()):
					pair = _spouse_pair(p1, p2)
					edge_pairs.append(pair)
					bidirectional_edges.add(pair)

		diagram = build_explorer_subgraph_diagram(
			title=diag_title,
			anchor_id=anchor_id,
			node_ids=nb_nodes,
			edge_pairs=edge_pairs,
			nodes_dict=nodes,
			edge_values={},
			ignore_edge_colors=True,
			bidirectional_edges=bidirectional_edges,
			node_colors=node_colors,
		)

		answer_lines: List[Tuple[str, Optional[AnswerHighlight]]] = []
		for sp in spouses:
			sp_name = format_console_node_name(nodes.get(sp, str(sp)))
			sp_term = get_spouse_term(detect_gender(node_colors.get(sp, "")))
			pair = _spouse_pair(anchor_id, sp)
			hl = AnswerHighlight(
				node_ids={anchor_id, sp},
				edges={pair},
				diagram=diagram,
				first_node_id=sp,
			)
			diagram.highlights.append(hl)
			answer_lines.append((f"Spouse ({sp_term}): {sp_name} ↔ {a_name}", hl))

		for p in preds:
			p_name = format_console_node_name(nodes.get(p, str(p)))
			p_term = get_parent_term(detect_gender(node_colors.get(p, "")))
			hl = AnswerHighlight(
				node_ids={p, anchor_id},
				edges={(p, anchor_id)},
				diagram=diagram,
				first_node_id=p,
			)
			diagram.highlights.append(hl)
			answer_lines.append((f"Parent ({p_term}): {p_name} → {a_name}", hl))

		for c in succs:
			c_name = format_console_node_name(nodes.get(c, str(c)))
			c_term = get_child_term(detect_gender(node_colors.get(c, "")))
			hl = AnswerHighlight(
				node_ids={anchor_id, c},
				edges={(anchor_id, c)},
				diagram=diagram,
				first_node_id=anchor_id,
			)
			diagram.highlights.append(hl)
			answer_lines.append((f"Child ({c_term}): {a_name} → {c_name}", hl))

		diagram.default_highlight = build_default_non_cycle_highlight(diagram.highlights)
		if not answer_lines:
			answer_lines.append((f"{a_name} has no immediate family neighbors.", None))

		return ExplorerResult(
			mode="neighborhood",
			title=title,
			diagram=diagram,
			answer_lines=answer_lines,
			active_node_ids=[anchor_id],
		)

	# Standard (correlation / counter) neighborhood
	preds = sorted(ctx.graph.predecessors(anchor_id), key=lambda x: str(nodes.get(x, x)).lower())
	succs = sorted(ctx.graph.successors(anchor_id), key=lambda x: str(nodes.get(x, x)).lower())
	nb_set = {anchor_id} | set(preds) | set(succs)

	mutual = sorted(set(preds) & set(succs), key=lambda x: str(nodes.get(x, x)).lower())
	mutual_set = set(mutual)
	only_preds = [p for p in preds if p not in mutual_set]
	only_succs = [s for s in succs if s not in mutual_set]

	neighbor_edges = sorted(
		(
			(u, v)
			for (u, v) in ctx.graph.edges()
			if u in nb_set and v in nb_set and u != anchor_id and v != anchor_id and u != v
		),
		key=lambda e: (str(nodes.get(e[0], e[0])).lower(), str(nodes.get(e[1], e[1])).lower()),
	)

	primary_cycles, secondary_cycles, diagram_cycles = _collect_subgraph_cycles(
		anchor_id, nb_set, ctx, is_counter, ignore_edge_colors
	)

	edge_pairs: List[Tuple[str, str]] = (
		[(p, anchor_id) for p in preds]
		+ [(anchor_id, s) for s in succs]
		+ neighbor_edges
	)

	diagram = build_explorer_subgraph_diagram(
		title=diag_title,
		anchor_id=anchor_id,
		node_ids=sorted(nb_set, key=lambda x: (0 if x == anchor_id else 1, str(nodes.get(x, x)).lower())),
		edge_pairs=edge_pairs,
		nodes_dict=nodes,
		edge_values=edge_values,
		ignore_edge_colors=is_counter or ignore_edge_colors,
		cycles=diagram_cycles,
		node_colors=node_colors,
	)

	answer_lines: List[Tuple[str, Optional[AnswerHighlight]]] = []

	for m in mutual:
		p1 = format_path_string([anchor_id, m], nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		p2 = format_path_string([m, anchor_id], nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		edge_pols = {} if ignore_pol else {
			(anchor_id, m): 1 if edge_values.get((anchor_id, m), 1) > 0 else -1,
			(m, anchor_id): 1 if edge_values.get((m, anchor_id), 1) > 0 else -1,
		}
		hl = AnswerHighlight(
			node_ids={anchor_id, m},
			edges={(anchor_id, m), (m, anchor_id)},
			diagram=diagram,
			first_node_id=anchor_id,
			edge_polarities=edge_pols,
		)
		diagram.highlights.append(hl)
		answer_lines.append((f"Direct (⟳): {p1} ↔ {p2}", hl))

	for p in only_preds:
		formatted = format_path_string([p, anchor_id], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		edge_pols = compute_path_edge_polarities([p, anchor_id], edge_values, ignore_pol)
		hl = AnswerHighlight(
			node_ids={p, anchor_id},
			edges={(p, anchor_id)},
			diagram=diagram,
			first_node_id=p,
			edge_polarities=edge_pols,
		)
		diagram.highlights.append(hl)
		answer_lines.append((f"Incoming: {formatted}", hl))

	for s in only_succs:
		formatted = format_path_string([anchor_id, s], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		edge_pols = compute_path_edge_polarities([anchor_id, s], edge_values, ignore_pol)
		hl = AnswerHighlight(
			node_ids={anchor_id, s},
			edges={(anchor_id, s)},
			diagram=diagram,
			first_node_id=anchor_id,
			edge_polarities=edge_pols,
		)
		diagram.highlights.append(hl)
		answer_lines.append((f"Outgoing: {formatted}", hl))

	for u, v in neighbor_edges:
		formatted = format_path_string([u, v], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		edge_pols = compute_path_edge_polarities([u, v], edge_values, ignore_pol)
		hl = AnswerHighlight(
			node_ids={u, v},
			edges={(u, v)},
			diagram=diagram,
			first_node_id=u,
			edge_polarities=edge_pols,
		)
		diagram.highlights.append(hl)
		answer_lines.append((f"Neighbor link: {formatted}", hl))

	_append_cycle_answers(answer_lines, primary_cycles, "Cycle", diagram, ctx, is_counter, ignore_edge_colors)
	_append_cycle_answers(answer_lines, secondary_cycles, "Secondary cycle", diagram, ctx, is_counter, ignore_edge_colors)

	diagram.default_highlight = build_default_non_cycle_highlight(diagram.highlights)
	if not answer_lines:
		answer_lines.append((f"{a_name} has no neighbors.", None))

	return ExplorerResult(
		mode="neighborhood",
		title=title,
		diagram=diagram,
		answer_lines=answer_lines,
		active_node_ids=[anchor_id],
	)


def build_explorer_result(
	ctx: GraphContext,
	prepared_data: dict,
	mode: str,
	node_a_id: Optional[str] = None,
	node_b_id: Optional[str] = None,
	max_depth: Optional[int] = None,
) -> ExplorerResult:
	mode_norm = (mode or "").strip().lower()
	valid_a = node_a_id if (node_a_id and node_a_id in ctx.nodes) else None
	valid_b = node_b_id if (node_b_id and node_b_id in ctx.nodes) else None

	if mode_norm == "dual":
		if not valid_a or not valid_b:
			raise ValueError("Select both Node A and Node B for Dual exploration.")
		if valid_a == valid_b:
			raise ValueError("Node A and Node B must be different for Dual exploration.")
		return _explore_dual(valid_a, valid_b, ctx, prepared_data)

	anchor_id = valid_a or valid_b
	if not anchor_id:
		raise ValueError("Select a node to explore.")

	if mode_norm in ("descendants", "ascendants"):
		return _explore_directional(mode_norm, anchor_id, ctx, prepared_data, max_depth)

	if mode_norm == "neighborhood":
		return _explore_neighborhood(anchor_id, ctx, prepared_data)

	raise ValueError(f"Unknown explorer mode: {mode}")