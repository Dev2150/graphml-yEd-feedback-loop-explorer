import random

from src.diagram import AnswerHighlight, build_cycle_diagram
from src.formatters import format_node_name, format_path_string, get_box_prefix, get_edge_arrow
from src.games.relationship.handlers.common import ask_continue, compute_cycle_polarity, path_edges
from src.models import GraphContext


def handle_cycle_question(
	question_num: int,
	rotated_cyc: list,
	ctx: GraphContext,
	prepared_data: dict,
	ask_input,
	emit_answer,
	on_graph_update=None,
) -> bool:
	g = ctx.graph
	nodes = ctx.nodes
	edge_values = ctx.edge_values
	node_colors = ctx.node_colors
	block_starting_node = ctx.config.block_starting_node
	is_counter = prepared_data["is_counter"]
	ignore_edge_colors = prepared_data["ignore_edge_colors"]

	valid_m = [
		idx for idx in range(1, len(rotated_cyc))
		if str(nodes.get(rotated_cyc[idx], rotated_cyc[idx])).lower() not in block_starting_node
	]
	m = random.choice(valid_m) if valid_m else random.randint(1, len(rotated_cyc) - 1)

	full_path = rotated_cyc + [rotated_cyc[0]]
	chosen_middle = full_path[m]
	pred_node = full_path[m - 1]
	succ_node = full_path[m + 1]

	edge_val_in = edge_values.get((pred_node, chosen_middle), 1)
	edge_val_out = edge_values.get((chosen_middle, succ_node), 1)

	cum_val = 1
	q_parts = [format_node_name(full_path[0], nodes, 0, is_counter)]
	for k in range(len(full_path) - 1):
		u, v = full_path[k], full_path[k + 1]
		cum_val *= edge_values.get((u, v), 1)
		arrow = get_edge_arrow(cum_val, ignore_edge_colors=ignore_edge_colors)
		node_text = (
			(f"{get_box_prefix(k + 1)} [?]" if is_counter else "[?]")
			if (k + 1) == m
			else format_node_name(v, nodes, k + 1, is_counter)
		)
		q_parts.append(f"{arrow} {node_text}")

	print(f"Question {question_num}: {' '.join(q_parts)}", end=' ')
	if not ask_continue(ask_input):
		return False

	known_nodes = set(rotated_cyc) - {chosen_middle}
	candidate_paths = []
	for cand in g.nodes():
		if cand in known_nodes:
			continue
		if str(nodes.get(cand, cand)).lower() in block_starting_node:
			continue
		if g.has_edge(pred_node, cand) and g.has_edge(cand, succ_node):
			if edge_values.get((pred_node, cand), 1) == edge_val_in and edge_values.get((cand, succ_node), 1) == edge_val_out:
				candidate_paths.append(full_path[:m] + [cand] + full_path[m + 1:])

	candidate_paths.sort(key=lambda p: [str(nodes.get(n, n)).lower() for n in p])
	paths_for_diagram = candidate_paths if candidate_paths else [full_path]

	diagram = build_cycle_diagram(
		paths=paths_for_diagram,
		answer_node_ids={p[m] for p in paths_for_diagram},
		nodes_dict=nodes,
		edge_values=edge_values,
		ignore_edge_colors=is_counter or ignore_edge_colors,
		question_num=question_num,
		node_colors=node_colors,
	)

	is_single = len(candidate_paths) <= 1
	paths_to_emit = [paths_for_diagram[0]] if is_single else candidate_paths
	prefix = "" if is_single else "  • "

	for cand_p in paths_to_emit:
		formatted_cycle = format_path_string(
			cand_p, nodes, edge_values,
			ignore_edge_colors=ignore_edge_colors, is_counter=is_counter,
		)
		polarity = compute_cycle_polarity(cand_p, edge_values, is_counter or ignore_edge_colors)
		if polarity is None:
			ans_text = f"{prefix}{formatted_cycle}"
		else:
			polarity_icon = "[💥]" if polarity > 0 else "[⚖️]"
			loop_type = "Reinforcing" if polarity > 0 else "Balancing"
			ans_text = f"{prefix}{formatted_cycle} ({polarity_icon} {loop_type})"

		hl = AnswerHighlight(
			node_ids=set(cand_p),
			edges=path_edges(cand_p),
			is_cycle=True,
			cycle_polarity=polarity,
			cycle_node_ids=list(dict.fromkeys(cand_p)),
			diagram=diagram,
		)
		if is_single:
			diagram.default_highlight = hl
		emit_answer(ans_text, hl)

	print()
	if on_graph_update is not None:
		on_graph_update(diagram)
	return True