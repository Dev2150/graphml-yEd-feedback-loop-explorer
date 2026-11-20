import random

from src.formatters import format_node_name, format_path_string, get_box_prefix, get_edge_arrow
from src.graph_diagram import AnswerHighlight, build_cycle_diagram
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
		u = full_path[k]
		v = full_path[k + 1]
		val = edge_values.get((u, v), 1)
		cum_val *= val
		arrow = get_edge_arrow(cum_val, ignore_edge_colors=ignore_edge_colors)
		if (k + 1) == m:
			node_text = f"{get_box_prefix(k + 1)} [?]" if is_counter else "[?]"
		else:
			node_text = format_node_name(v, nodes, k + 1, is_counter)
		q_parts.append(f"{arrow} {node_text}")

	question_str = " ".join(q_parts)
	print(f"Question {question_num}: {question_str}", end=' ')

	user_input = ask_input().strip()
	if user_input == '0':
		print("Stopping the game.")
		return False

	known_nodes = set(rotated_cyc) - {chosen_middle}
	candidate_paths = []
	for cand in g.nodes():
		if cand in known_nodes:
			continue
		if str(nodes.get(cand, cand)).lower() in block_starting_node:
			continue
		if g.has_edge(pred_node, cand) and g.has_edge(cand, succ_node):
			val_in = edge_values.get((pred_node, cand), 1)
			val_out = edge_values.get((cand, succ_node), 1)
			if val_in == edge_val_in and val_out == edge_val_out:
				cand_path = full_path[:m] + [cand] + full_path[m + 1:]
				candidate_paths.append(cand_path)

	candidate_paths.sort(key=lambda p: [str(nodes.get(n, n)).lower() for n in p])

	paths_for_diagram = candidate_paths if candidate_paths else [full_path]
	ans_ids = {p[m] for p in paths_for_diagram}
	diagram = build_cycle_diagram(
		paths=paths_for_diagram,
		answer_node_ids=ans_ids,
		nodes_dict=nodes,
		edge_values=edge_values,
		ignore_edge_colors=is_counter or ignore_edge_colors,
		question_num=question_num,
		node_colors=node_colors,
	)

	if len(candidate_paths) <= 1:
		target_path = candidate_paths[0] if candidate_paths else full_path
		formatted_cycle = format_path_string(
			target_path, nodes, edge_values,
			ignore_edge_colors=ignore_edge_colors, is_counter=is_counter,
		)
		if is_counter or ignore_edge_colors:
			polarity = None
			ans_text = f"{formatted_cycle}"
		else:
			cycle_corr = 1
			for k in range(len(target_path) - 1):
				cycle_corr *= edge_values.get((target_path[k], target_path[k + 1]), 1)
			polarity = 1 if cycle_corr > 0 else -1
			polarity_icon = "[💥]" if cycle_corr > 0 else "[⚖️]"
			loop_type = "Reinforcing" if cycle_corr > 0 else "Balancing"
			ans_text = f"{formatted_cycle} ({polarity_icon} {loop_type})"

		hl = AnswerHighlight(
			node_ids=set(target_path),
			edges={(target_path[k], target_path[k + 1]) for k in range(len(target_path) - 1)},
			is_cycle=True,
			cycle_polarity=polarity,
			cycle_node_ids=list(dict.fromkeys(target_path)),
			diagram=diagram,
		)
		emit_answer(ans_text, hl)
	else:
		for cand_p in candidate_paths:
			formatted_cycle = format_path_string(
				cand_p, nodes, edge_values,
				ignore_edge_colors=ignore_edge_colors, is_counter=is_counter,
			)
			if is_counter or ignore_edge_colors:
				polarity = None
				ans_text = f"  • {formatted_cycle}"
			else:
				cycle_corr = 1
				for k in range(len(cand_p) - 1):
					cycle_corr *= edge_values.get((cand_p[k], cand_p[k + 1]), 1)
				polarity = 1 if cycle_corr > 0 else -1
				polarity_icon = "[💥]" if cycle_corr > 0 else "[⚖️]"
				loop_type = "Reinforcing" if cycle_corr > 0 else "Balancing"
				ans_text = f"  • {formatted_cycle} ({polarity_icon} {loop_type})"

			hl = AnswerHighlight(
				node_ids=set(cand_p),
				edges={(cand_p[k], cand_p[k + 1]) for k in range(len(cand_p) - 1)},
				is_cycle=True,
				cycle_polarity=polarity,
				cycle_node_ids=list(dict.fromkeys(cand_p)),
				diagram=diagram,
			)
			emit_answer(ans_text, hl)

	print()
	if on_graph_update is not None:
		on_graph_update(diagram)
	return True