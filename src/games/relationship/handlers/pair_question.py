import random
import networkx as nx

from src.family import analyze_family_pair
from src.formatters import (
	format_console_node_name,
	format_path_string,
	get_edge_arrow,
	get_path_net_effect_arrow,
)
from src.games.relationship.progress import get_canonical_cycle_tuple
from src.diagram import (
	AnswerHighlight,
	build_family_pair_diagram,
	build_pair_diagram,
	compute_earliest_generation_nodes,
)
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
	g = ctx.graph
	nodes = ctx.nodes
	node_colors = ctx.node_colors
	parents_map = prepared_data["parents_map"]
	children_map = prepared_data["children_map"]
	spouses_map = prepared_data["spouses_map"]
	ancestor_paths = prepared_data["ancestor_paths"]
	ancestor_dist = prepared_data["ancestor_dist"]
	family_results_cache = prepared_data["family_results_cache"]

	fam_res = family_results_cache.get((u, v))
	if not fam_res:
		fam_res = analyze_family_pair(
			u, v, nodes, node_colors, parents_map, children_map,
			spouses_map, ancestor_paths, ancestor_dist,
		)

	diagram = build_family_pair_diagram(
		u=u, v=v, graph=g, nodes_dict=nodes,
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
	node_colors = ctx.node_colors
	config = ctx.config

	max_indirectness_game = config.max_indirectness_game
	max_cycle_length_game = config.max_cycle_length_game
	include_secondary_cycles = getattr(config, 'include_secondary_cycles', True)

	is_counter = prepared_data["is_counter"]
	ignore_edge_colors = prepared_data["ignore_edge_colors"]
	text_shared_source = prepared_data["text_shared_source"]
	text_shared_dest = prepared_data["text_shared_dest"]

	cutoff_distance = max_indirectness_game + 1
	paths_u_v = list(nx.all_simple_paths(g, source=u, target=v, cutoff=cutoff_distance))
	paths_v_u = list(nx.all_simple_paths(g, source=v, target=u, cutoff=cutoff_distance))

	paths_u_v.sort(key=len)
	paths_v_u.sort(key=len)

	direct_u_v = [p for p in paths_u_v if len(p) == 2]
	direct_v_u = [p for p in paths_v_u if len(p) == 2]

	indirect_u_v = [p for p in paths_u_v if len(p) > 2]
	indirect_v_u = [p for p in paths_v_u if len(p) > 2]

	is_direct = bool(direct_u_v or direct_v_u)
	is_indirect = not is_direct and bool(indirect_u_v or indirect_v_u)

	shared_srcs = [s for s in set(g.predecessors(u)).intersection(g.predecessors(v)) if s != u and s != v]
	shared_dsts = [d for d in set(g.successors(u)).intersection(g.successors(v)) if d != u and d != v]

	shared_srcs.sort(key=lambda s: str(nodes.get(s, s)).lower())
	shared_dsts.sort(key=lambda d: str(nodes.get(d, d)).lower())

	connection_entries = []

	if is_counter:
		for s in shared_srcs:
			s_name = format_console_node_name(nodes.get(s, s))
			connection_entries.append((
				f"{text_shared_source}: 🟦 {s_name} → 🟥 {u_name} & 🟥 {v_name}",
				AnswerHighlight(node_ids={s, u, v}, edges={(s, u), (s, v)}, first_node_id=s),
			))

		for d in shared_dsts:
			d_name = format_console_node_name(nodes.get(d, d))
			connection_entries.append((
				f"{text_shared_dest}: 🟦 {u_name} & 🟦 {v_name} → 🟥 {d_name}",
				AnswerHighlight(node_ids={u, v, d}, edges={(u, d), (v, d)}, first_node_id=u),
			))
	else:
		for s in shared_srcs:
			val_u = edge_values.get((s, u), 1)
			val_v = edge_values.get((s, v), 1)
			arr_u = get_edge_arrow(val_u)
			arr_v = get_edge_arrow(val_v)
			s_name = format_console_node_name(nodes.get(s, s))
			if arr_u == arr_v:
				line = f"{text_shared_source}: {s_name} {arr_u}"
			else:
				line = f"{text_shared_source}: {s_name} {arr_u} {u_name} + {arr_v} {v_name}"
			connection_entries.append((
				line,
				AnswerHighlight(node_ids={s, u, v}, edges={(s, u), (s, v)}, first_node_id=s),
			))

		for d in shared_dsts:
			val_u = edge_values.get((u, d), 1)
			val_v = edge_values.get((v, d), 1)
			arr_u = get_edge_arrow(val_u)
			arr_v = get_edge_arrow(val_v)
			d_name = format_console_node_name(nodes.get(d, d))
			if arr_u == arr_v:
				line = f"{text_shared_dest}: {arr_u} {d_name}"
			else:
				line = f"{text_shared_dest}: {u_name} ({arr_u}) + {v_name} ({arr_v}) → {d_name}"
			connection_entries.append((
				line,
				AnswerHighlight(node_ids={u, v, d}, edges={(u, d), (v, d)}, first_node_id=u),
			))

	if is_direct:
		if direct_u_v and direct_v_u:
			p1_str = format_path_string([u, v], nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
			p2_str = format_path_string([v, u], nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
			lbl1 = edge_labels.get((u, v), '') if edge_labels else ''
			lbl2 = edge_labels.get((v, u), '') if edge_labels else ''
			lbl_lines = []
			if lbl1:
				lbl_lines.append(f"      ({u_name} → {v_name}: {lbl1})")
			if lbl2:
				lbl_lines.append(f"      ({v_name} → {u_name}: {lbl2})")
			lbl_suffix = ("\n" + "\n".join(lbl_lines)) if lbl_lines else ""
			connection_entries.append((
				f"Direct (⟳): {p1_str} ↔ {p2_str}{lbl_suffix}",
				AnswerHighlight(node_ids={u, v}, edges={(u, v), (v, u)}, first_node_id=u),
			))
		elif direct_u_v:
			p_str = format_path_string([u, v], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
			connection_entries.append((
				f"Direct: {p_str}",
				AnswerHighlight(node_ids={u, v}, edges={(u, v)}, first_node_id=u),
			))
			for p in paths_v_u:
				is_p_direct = len(p) == 2
				prefix = "Direct ↩" if is_p_direct else f"Indirect ↩ ({len(p) - 2})"
				formatted_p = format_path_string(p, nodes, edge_values, edge_labels if is_p_direct else None, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
				suffix = "" if (is_counter or ignore_edge_colors or is_p_direct) else f" ({get_path_net_effect_arrow(p, edge_values)})"
				connection_entries.append((
					f"{prefix}: {formatted_p}{suffix}",
					AnswerHighlight(node_ids=set(p), edges={(p[k], p[k + 1]) for k in range(len(p) - 1)}, first_node_id=p[0]),
				))
		elif direct_v_u:
			p_str = format_path_string([v, u], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
			connection_entries.append((
				f"Direct: {p_str}",
				AnswerHighlight(node_ids={v, u}, edges={(v, u)}, first_node_id=v),
			))
			for p in paths_u_v:
				is_p_direct = len(p) == 2
				prefix = "Direct ↩" if is_p_direct else f"Indirect ↩ ({len(p) - 2})"
				formatted_p = format_path_string(p, nodes, edge_values, edge_labels if is_p_direct else None, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
				suffix = "" if (is_counter or ignore_edge_colors or is_p_direct) else f" ({get_path_net_effect_arrow(p, edge_values)})"
				connection_entries.append((
					f"{prefix}: {formatted_p}{suffix}",
					AnswerHighlight(node_ids=set(p), edges={(p[k], p[k + 1]) for k in range(len(p) - 1)}, first_node_id=p[0]),
				))

		for p in indirect_u_v:
			formatted_p = format_path_string(p, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
			suffix = "" if (is_counter or ignore_edge_colors) else f" ({get_path_net_effect_arrow(p, edge_values)})"
			connection_entries.append((
				f"Indirect ({len(p) - 2}): {formatted_p}{suffix}",
				AnswerHighlight(node_ids=set(p), edges={(p[k], p[k + 1]) for k in range(len(p) - 1)}, first_node_id=p[0]),
			))
	elif is_indirect:
		for p in indirect_u_v:
			formatted_p = format_path_string(p, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
			suffix = "" if (is_counter or ignore_edge_colors) else f" ({get_path_net_effect_arrow(p, edge_values)})"
			connection_entries.append((
				f"Indirect ({len(p) - 2}): {formatted_p}{suffix}",
				AnswerHighlight(node_ids=set(p), edges={(p[k], p[k + 1]) for k in range(len(p) - 1)}, first_node_id=p[0]),
			))
		for p in indirect_v_u:
			prefix = "Indirect ↩" if indirect_u_v else "Indirect"
			formatted_p = format_path_string(p, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
			suffix = "" if (is_counter or ignore_edge_colors) else f" ({get_path_net_effect_arrow(p, edge_values)})"
			connection_entries.append((
				f"{prefix} ({len(p) - 2}): {formatted_p}{suffix}",
				AnswerHighlight(node_ids=set(p), edges={(p[k], p[k + 1]) for k in range(len(p) - 1)}, first_node_id=p[0]),
			))

	pair_cycles = []
	seen_pair_cycles = set()

	def _add_pair_cycle(full_cycle: list):
		cycle_tuple = tuple(full_cycle[:-1])
		min_i = cycle_tuple.index(min(cycle_tuple))
		canonical = cycle_tuple[min_i:] + cycle_tuple[:min_i]
		if canonical not in seen_pair_cycles:
			seen_pair_cycles.add(canonical)
			pair_cycles.append(full_cycle)

	if max_cycle_length_game >= 2:
		paths_fwd = list(nx.all_simple_paths(g, source=u, target=v, cutoff=max_cycle_length_game - 1))
		paths_bwd = list(nx.all_simple_paths(g, source=v, target=u, cutoff=max_cycle_length_game - 1))

		for p1 in paths_fwd:
			mid1 = set(p1[1:-1])
			for p2 in paths_bwd:
				total_nodes = (len(p1) - 1) + (len(p2) - 1)
				if total_nodes <= max_cycle_length_game and mid1.isdisjoint(p2[1:-1]):
					_add_pair_cycle(p1[:-1] + p2)

		for p1 in paths_u_v:
			mid1 = set(p1[1:-1])
			for p2 in paths_v_u:
				total_nodes = (len(p1) - 1) + (len(p2) - 1)
				if total_nodes <= max_cycle_length_game and mid1.isdisjoint(p2[1:-1]):
					_add_pair_cycle(p1[:-1] + p2)

	base_nodes = {u, v} | set(shared_srcs) | set(shared_dsts)
	base_edges = set()
	for s in shared_srcs:
		base_edges.add((s, u))
		base_edges.add((s, v))
	for d in shared_dsts:
		base_edges.add((u, d))
		base_edges.add((v, d))
	for p in paths_u_v + paths_v_u + pair_cycles:
		base_nodes.update(p)
		for k in range(len(p) - 1):
			base_edges.add((p[k], p[k + 1]))

	base_g = nx.DiGraph()
	base_g.add_nodes_from(base_nodes)
	base_g.add_edges_from(base_edges)
	drawn_cycles = find_bounded_cycles(base_g, max_cycle_length_game) if max_cycle_length_game >= 2 else []

	for cyc_nodes in drawn_cycles:
		if 2 <= len(cyc_nodes) <= max_cycle_length_game and u in cyc_nodes and v in cyc_nodes:
			idx = cyc_nodes.index(u)
			rotated = cyc_nodes[idx:] + cyc_nodes[:idx]
			_add_pair_cycle(rotated + [rotated[0]])

	pair_cycles.sort(key=lambda c: (len(c), [str(nodes.get(n, n)) for n in c]))

	for cyc in pair_cycles:
		formatted_cyc = format_path_string(cyc, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
		cyc_len = len(cyc) - 1
		if is_counter or ignore_edge_colors:
			polarity = None
			line = f"Cycle ({cyc_len}): {formatted_cyc}"
		else:
			cycle_corr = 1
			for k in range(len(cyc) - 1):
				cycle_corr *= edge_values.get((cyc[k], cyc[k + 1]), 1)
			polarity = 1 if cycle_corr > 0 else -1
			polarity_icon = "[💥]" if cycle_corr > 0 else "[⚖️]"
			line = f"Cycle ({cyc_len}) {polarity_icon}: {formatted_cyc}"

		connection_entries.append((
			line,
			AnswerHighlight(
				node_ids=set(cyc),
				edges={(cyc[k], cyc[k + 1]) for k in range(len(cyc) - 1)},
				is_cycle=True,
				cycle_polarity=polarity,
				cycle_node_ids=list(dict.fromkeys(cyc)),
			),
		))

	secondary_cycles = []
	if include_secondary_cycles and max_cycle_length_game >= 2:
		raw_sec_cycles = list(drawn_cycles)
		if len(base_nodes) >= 2:
			sub_g = g.subgraph(base_nodes)
			raw_sec_cycles.extend(find_bounded_cycles(sub_g, max_cycle_length_game))

		seen_sec_cycles = set()
		for cyc_nodes in raw_sec_cycles:
			if len(cyc_nodes) < 2 or len(cyc_nodes) > max_cycle_length_game:
				continue
			cyc_set = set(cyc_nodes)
			if u in cyc_set and v in cyc_set:
				continue
			if not cyc_set.issubset(base_nodes):
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

		for cyc in secondary_cycles:
			formatted_cyc = format_path_string(cyc, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
			cyc_len = len(cyc) - 1
			if is_counter or ignore_edge_colors:
				polarity = None
				line = f"Secondary cycle ({cyc_len}): {formatted_cyc}"
			else:
				cycle_corr = 1
				for k in range(len(cyc) - 1):
					cycle_corr *= edge_values.get((cyc[k], cyc[k + 1]), 1)
				polarity = 1 if cycle_corr > 0 else -1
				polarity_icon = "[💥]" if cycle_corr > 0 else "[⚖️]"
				line = f"Secondary cycle ({cyc_len}) {polarity_icon}: {formatted_cyc}"

			connection_entries.append((
				line,
				AnswerHighlight(
					node_ids=set(cyc),
					edges={(cyc[k], cyc[k + 1]) for k in range(len(cyc) - 1)},
					is_cycle=True,
					cycle_polarity=polarity,
					cycle_node_ids=list(dict.fromkeys(cyc)),
				),
			))

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
		node_colors=node_colors,
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

	user_input = ask_input().strip()
	if user_input == '0':
		print("Stopping the game.")
		return False

	if prepared_data["is_family"]:
		_handle_family_pair(question_num, u, v, ctx, prepared_data, emit_answer, on_graph_update)
	else:
		_handle_standard_pair(question_num, u, v, u_name, v_name, ctx, prepared_data, emit_answer, on_graph_update)

	print()
	return True