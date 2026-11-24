import random
import networkx as nx

from src.diagram import (
	AnswerHighlight,
	build_family_pair_diagram,
	build_pair_diagram,
	compute_earliest_generation_nodes,
)
from src.family import analyze_family_pair
from src.formatters import (
	format_console_node_name,
	format_path_string,
	get_edge_arrow,
	get_path_net_effect_arrow,
)
from src.games.relationship.handlers.common import ask_continue, compute_cycle_polarity, path_edges, \
	compute_path_edge_polarities
from src.games.relationship.progress import get_canonical_cycle_tuple
from src.graph_utils import find_bounded_cycles
from src.models import GraphContext


def _handle_family_pair(
	question_num: int,
	u,
	v,
	ctx: GraphContext,
	prepared_data: dict,
	emit_answer,
	on_graph_update=None,
):
	nodes = ctx.nodes
	node_colors = ctx.node_colors
	parents_map = prepared_data["parents_map"]
	children_map = prepared_data["children_map"]
	spouses_map = prepared_data["spouses_map"]
	ancestor_paths = prepared_data["ancestor_paths"]
	ancestor_dist = prepared_data["ancestor_dist"]

	fam_res = prepared_data["family_results_cache"].get((u, v)) or analyze_family_pair(
		u, v, nodes, node_colors, parents_map, children_map,
		spouses_map, ancestor_paths, ancestor_dist,
	)

	diagram = build_family_pair_diagram(
		u=u, v=v, graph=ctx.graph, nodes_dict=nodes,
		parents_map=parents_map, children_map=children_map,
		spouses_map=spouses_map, ancestor_paths=ancestor_paths,
		ancestor_dist=ancestor_dist, question_num=question_num,
		node_colors=node_colors,
	)

	if not fam_res.is_relevant:
		diagram.default_highlight = None
		print("IRRELEVANT (No blood or marriage relationship found)")
	else:
		earliest_nodes = compute_earliest_generation_nodes(
			[n.node_id for n in diagram.nodes],
			parents_map,
			spouses_map,
			merged_nodes=diagram.merged_nodes,
		)
		fam_hl = AnswerHighlight(
			node_ids=set(earliest_nodes),
			edges={(e.source_id, e.target_id) for e in diagram.edges},
			diagram=diagram,
			first_node_ids=set(earliest_nodes),
		)
		diagram.default_highlight = fam_hl
		emit_answer(f"{fam_res.primary_title}", fam_hl)
		for d in fam_res.details:
			emit_answer(f"  • {d}", fam_hl)
		if fam_res.lineages:
			print("  Lineage:", end='')
			for lineage in fam_res.lineages:
				emit_answer(f"    {lineage}", fam_hl)

	if on_graph_update is not None:
		on_graph_update(diagram)


def _handle_standard_pair(
	question_num: int,
	u,
	v,
	u_name: str,
	v_name: str,
	ctx: GraphContext,
	prepared_data: dict,
	emit_answer,
	on_graph_update=None,
):
	g = ctx.graph
	nodes = ctx.nodes
	edge_values = ctx.edge_values
	edge_labels = ctx.edge_labels
	config = ctx.config

	max_indirectness_game = config.max_indirectness_game
	max_cycle_length_game = config.max_cycle_length_game
	include_secondary_cycles = getattr(config, 'include_secondary_cycles', True)

	is_counter = prepared_data["is_counter"]
	ignore_edge_colors = prepared_data["ignore_edge_colors"]
	text_shared_source = prepared_data["text_shared_source"]
	text_shared_dest = prepared_data["text_shared_dest"]

	cutoff_distance = max_indirectness_game + 1
	paths_u_v = sorted(nx.all_simple_paths(g, source=u, target=v, cutoff=cutoff_distance), key=len)
	paths_v_u = sorted(nx.all_simple_paths(g, source=v, target=u, cutoff=cutoff_distance), key=len)

	direct_u_v = [p for p in paths_u_v if len(p) == 2]
	direct_v_u = [p for p in paths_v_u if len(p) == 2]
	indirect_u_v = [p for p in paths_u_v if len(p) > 2]
	indirect_v_u = [p for p in paths_v_u if len(p) > 2]

	shared_srcs = sorted(
		(s for s in set(g.predecessors(u)).intersection(g.predecessors(v)) if s != u and s != v),
		key=lambda s: str(nodes.get(s, s)).lower(),
	)
	shared_dsts = sorted(
		(d for d in set(g.successors(u)).intersection(g.successors(v)) if d != u and d != v),
		key=lambda d: str(nodes.get(d, d)).lower(),
	)

	connection_entries = []

	def _append_path_entries(paths: list, label_prefix: str):
		for p in paths:
			formatted_p = format_path_string(
				p, nodes, edge_values,
				ignore_edge_colors=ignore_edge_colors, is_counter=is_counter,
			)
			suffix = "" if (is_counter or ignore_edge_colors) else f" ({get_path_net_effect_arrow(p, edge_values)})"
			edge_pols = compute_path_edge_polarities(p, edge_values, is_counter or ignore_edge_colors)
			connection_entries.append((
				f"{label_prefix} ({len(p) - 2}): {formatted_p}{suffix}",
				AnswerHighlight(node_ids=set(p), edges=path_edges(p), first_node_id=p[0], edge_polarities=edge_pols),
			))

	def _append_cycle_entries(cycles: list, label_prefix: str):
		for cyc in cycles:
			formatted_cyc = format_path_string(
				cyc, nodes, edge_values,
				ignore_edge_colors=ignore_edge_colors, is_counter=is_counter,
			)
			cyc_len = len(cyc) - 1
			polarity = compute_cycle_polarity(cyc, edge_values, is_counter or ignore_edge_colors)
			if polarity is None:
				line = f"{label_prefix} ({cyc_len}): {formatted_cyc}"
			else:
				polarity_icon = "[💥]" if polarity > 0 else "[⚖️]"
				line = f"{label_prefix} ({cyc_len}) {polarity_icon}: {formatted_cyc}"
			connection_entries.append((
				line,
				AnswerHighlight(
					node_ids=set(cyc),
					edges=path_edges(cyc),
					is_cycle=True,
					cycle_polarity=polarity,
					cycle_node_ids=list(dict.fromkeys(cyc)),
				),
			))

	# 1. Shared sources & destinations
	for s in shared_srcs:
		s_name = format_console_node_name(nodes.get(s, s))
		if is_counter:
			line = f"{text_shared_source}: 🟦 {s_name} → 🟥 {u_name} & 🟥 {v_name}"
		else:
			arr_u = get_edge_arrow(edge_values.get((s, u), 1))
			arr_v = get_edge_arrow(edge_values.get((s, v), 1))
			line = (
				f"{text_shared_source}: {s_name} {arr_u}"
				if arr_u == arr_v
				else f"{text_shared_source}: {s_name} {arr_u} {u_name} + {arr_v} {v_name}"
			)
		edge_pols = {} if (is_counter or ignore_edge_colors) else {
			(s, u): 1 if edge_values.get((s, u), 1) > 0 else -1,
			(s, v): 1 if edge_values.get((s, v), 1) > 0 else -1,
		}
		connection_entries.append((
			line,
			AnswerHighlight(node_ids={s, u, v}, edges={(s, u), (s, v)}, first_node_id=s, edge_polarities=edge_pols),
		))

	for d in shared_dsts:
		d_name = format_console_node_name(nodes.get(d, d))
		if is_counter:
			line = f"{text_shared_dest}: 🟦 {u_name} & 🟦 {v_name} → 🟥 {d_name}"
		else:
			arr_u = get_edge_arrow(edge_values.get((u, d), 1))
			arr_v = get_edge_arrow(edge_values.get((v, d), 1))
			line = (
				f"{text_shared_dest}: {arr_u} {d_name}"
				if arr_u == arr_v
				else f"{text_shared_dest}: {u_name} ({arr_u}) + {v_name} ({arr_v}) → {d_name}"
			)
		edge_pols = {} if (is_counter or ignore_edge_colors) else {
			(u, d): 1 if edge_values.get((u, d), 1) > 0 else -1,
			(v, d): 1 if edge_values.get((v, d), 1) > 0 else -1,
		}
		connection_entries.append((
			line,
			AnswerHighlight(node_ids={u, v, d}, edges={(u, d), (v, d)}, first_node_id=u, edge_polarities=edge_pols),
		))

	# 2. Direct & indirect paths
	if direct_u_v and direct_v_u:
		p1_str = format_path_string([u, v], nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		p2_str = format_path_string([v, u], nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		lbl_lines = []
		if edge_labels:
			if edge_labels.get((u, v)):
				lbl_lines.append(f"      ({u_name} → {v_name}: {edge_labels[(u, v)]})")
			if edge_labels.get((v, u)):
				lbl_lines.append(f"      ({v_name} → {u_name}: {edge_labels[(v, u)]})")
		lbl_suffix = ("\n" + "\n".join(lbl_lines)) if lbl_lines else ""
		edge_pols = {} if (is_counter or ignore_edge_colors) else {
			(u, v): 1 if edge_values.get((u, v), 1) > 0 else -1,
			(v, u): 1 if edge_values.get((v, u), 1) > 0 else -1,
		}
		connection_entries.append((
			f"Direct (⟳): {p1_str} ↔ {p2_str}{lbl_suffix}",
			AnswerHighlight(node_ids={u, v}, edges={(u, v), (v, u)}, first_node_id=u, edge_polarities=edge_pols),
		))
		_append_path_entries(indirect_u_v, "Indirect")
		_append_path_entries(indirect_v_u, "Indirect ↩")
	elif direct_u_v:
		p_str = format_path_string([u, v], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		edge_pols = compute_path_edge_polarities([u, v], edge_values, is_counter or ignore_edge_colors)
		connection_entries.append((
			f"Direct: {p_str}",
			AnswerHighlight(node_ids={u, v}, edges={(u, v)}, first_node_id=u, edge_polarities=edge_pols),
		))
		_append_path_entries(indirect_u_v, "Indirect")
		_append_path_entries(indirect_v_u, "Indirect ↩")
	elif direct_v_u:
		p_str = format_path_string([v, u], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		edge_pols = compute_path_edge_polarities([v, u], edge_values, is_counter or ignore_edge_colors)
		connection_entries.append((
			f"Direct: {p_str}",
			AnswerHighlight(node_ids={v, u}, edges={(v, u)}, first_node_id=v, edge_polarities=edge_pols),
		))
		_append_path_entries(indirect_v_u, "Indirect")
		_append_path_entries(indirect_u_v, "Indirect ↩")
	else:
		_append_path_entries(indirect_u_v, "Indirect")
		_append_path_entries(indirect_v_u, "Indirect ↩" if indirect_u_v else "Indirect")

	# 3. Primary cycles containing both u and v
	pair_cycles = []
	seen_pair_cycles = set()
	if max_cycle_length_game >= 2:
		paths_fwd = list(nx.all_simple_paths(g, source=u, target=v, cutoff=max_cycle_length_game - 1))
		paths_bwd = list(nx.all_simple_paths(g, source=v, target=u, cutoff=max_cycle_length_game - 1))
		for p1 in paths_fwd:
			mid1 = set(p1[1:-1])
			for p2 in paths_bwd:
				if (len(p1) - 1) + (len(p2) - 1) <= max_cycle_length_game and mid1.isdisjoint(p2[1:-1]):
					full_cycle = p1[:-1] + p2
					canonical = tuple(get_canonical_cycle_tuple(full_cycle[:-1], nodes))
					if canonical not in seen_pair_cycles:
						seen_pair_cycles.add(canonical)
						pair_cycles.append(full_cycle)

	pair_cycles.sort(key=lambda c: (len(c), [str(nodes.get(n, n)) for n in c]))
	_append_cycle_entries(pair_cycles, "Cycle")

	# 4. Secondary cycles among nodes appearing in the diagram
	base_nodes = {u, v} | set(shared_srcs) | set(shared_dsts)
	for p in paths_u_v + paths_v_u + pair_cycles:
		base_nodes.update(p)

	secondary_cycles = []
	if include_secondary_cycles and max_cycle_length_game >= 2 and len(base_nodes) >= 2:
		seen_sec_cycles = set()
		for cyc_nodes in find_bounded_cycles(g.subgraph(base_nodes), max_cycle_length_game):
			if len(cyc_nodes) < 2 or len(cyc_nodes) > max_cycle_length_game:
				continue
			cyc_set = set(cyc_nodes)
			if u in cyc_set and v in cyc_set:
				continue
			canonical = tuple(get_canonical_cycle_tuple(cyc_nodes, nodes))
			if canonical in seen_sec_cycles:
				continue
			seen_sec_cycles.add(canonical)

			if u in cyc_set:
				idx = cyc_nodes.index(u)
				rotated = cyc_nodes[idx:] + cyc_nodes[:idx]
			elif v in cyc_set:
				idx = cyc_nodes.index(v)
				rotated = cyc_nodes[idx:] + cyc_nodes[:idx]
			else:
				rotated = list(canonical)
			secondary_cycles.append(rotated + [rotated[0]])

		secondary_cycles.sort(key=lambda c: (len(c), [str(nodes.get(n, n)).lower() for n in c]))
		_append_cycle_entries(secondary_cycles, "Secondary cycle")

	diagram = build_pair_diagram(
		u=u,
		v=v,
		nodes_dict=nodes,
		edge_values=edge_values,
		shared_srcs=shared_srcs,
		shared_dsts=shared_dsts,
		paths_u_v=paths_u_v,
		paths_v_u=paths_v_u,
		pair_cycles=pair_cycles,
		secondary_cycles=secondary_cycles,
		ignore_edge_colors=is_counter or ignore_edge_colors,
		question_num=question_num,
		node_colors=ctx.node_colors,
	)

	for _, hl in connection_entries:
		hl.diagram = diagram

	if not connection_entries:
		print("IRRELEVANT")
	elif len(connection_entries) == 1:
		text, hl = connection_entries[0]
		emit_answer(text, hl)
	else:
		for text, hl in connection_entries:
			emit_answer(f"  • {text}", hl)

	if on_graph_update is not None:
		on_graph_update(diagram)


def handle_pair_question(
	question_num: int,
	pair_data: tuple,
	ctx: GraphContext,
	prepared_data: dict,
	ask_input,
	emit_answer,
	on_graph_update=None,
) -> bool:
	u, v = pair_data
	if random.random() > 0.5:
		u, v = v, u

	u_name = format_console_node_name(ctx.nodes.get(u, str(u)))
	v_name = format_console_node_name(ctx.nodes.get(v, str(v)))

	print(f"Question {question_num}: {u_name} [?] {v_name}", end=' ')
	if not ask_continue(ask_input):
		return False

	if prepared_data["is_family"]:
		_handle_family_pair(question_num, u, v, ctx, prepared_data, emit_answer, on_graph_update)
	else:
		_handle_standard_pair(question_num, u, v, u_name, v_name, ctx, prepared_data, emit_answer, on_graph_update)

	print()
	return True