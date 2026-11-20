from src.family_utils import detect_gender, get_child_term, get_parent_term
from src.formatters import format_console_node_name, format_path_string
from src.graph_diagram import AnswerHighlight, build_leaf_diagram
from src.models import GraphContext


def handle_leaf_source_question(
	question_num: int,
	target_node,
	ctx: GraphContext,
	prepared_data: dict,
	ask_input,
	emit_answer,
	on_graph_update=None,
) -> bool:
	nodes = ctx.nodes
	edge_values = ctx.edge_values
	edge_labels = ctx.edge_labels
	node_colors = ctx.node_colors
	is_counter = prepared_data["is_counter"]
	is_family = prepared_data["is_family"]
	ignore_edge_colors = prepared_data["ignore_edge_colors"]
	leaf_sources_map = prepared_data["leaf_sources_map"]

	raw_target_name = nodes.get(target_node, str(target_node))
	target_name = format_console_node_name(raw_target_name)

	if is_counter:
		print(f"Question {question_num}: 🟦 [?] → 🟥 {target_name}", end=' ')
	elif is_family:
		t_gender = detect_gender(node_colors.get(target_node, ''))
		t_child_term = get_child_term(t_gender)
		print(f"Question {question_num}: [?] (Parent) → {target_name} ({t_child_term})", end=' ')
	else:
		print(f"Question {question_num}: [?] → {target_name}", end=' ')

	user_input = ask_input().strip()
	if user_input == '0':
		print("Stopping the game.")
		return False

	found_leaves = sorted(leaf_sources_map[target_node], key=lambda x: str(nodes.get(x, x)).lower())
	diagram = build_leaf_diagram(
		anchor_node=target_node,
		leaf_nodes=found_leaves,
		is_source_question=True,
		nodes_dict=nodes,
		edge_values=edge_values,
		ignore_edge_colors=is_counter or ignore_edge_colors or is_family,
		question_num=question_num,
		node_colors=node_colors,
	)

	if len(found_leaves) == 1:
		p_nid = found_leaves[0]
		p_name = format_console_node_name(nodes.get(p_nid, str(p_nid)))
		if is_family:
			p_term = get_parent_term(detect_gender(node_colors.get(p_nid, '')))
			ans_text = f"{p_name} ({p_term}) → {target_name}"
		else:
			ans_text = (
				f"{format_path_string([p_nid, target_node], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)}"
			)
		hl = AnswerHighlight(
			node_ids={p_nid, target_node},
			edges={(p_nid, target_node)},
			diagram=diagram,
			first_node_id=p_nid,
		)
		emit_answer(ans_text, hl)
	else:
		for s in found_leaves:
			s_name = format_console_node_name(nodes.get(s, str(s)))
			if is_family:
				p_term = get_parent_term(detect_gender(node_colors.get(s, '')))
				ans_text = f"  • {s_name} ({p_term}) → {target_name}"
			else:
				ans_text = (
					f"  • {format_path_string([s, target_node], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)}"
				)
			hl = AnswerHighlight(
				node_ids={s, target_node},
				edges={(s, target_node)},
				diagram=diagram,
				first_node_id=s,
			)
			emit_answer(ans_text, hl)

	print()
	if on_graph_update is not None:
		on_graph_update(diagram)
	return True


def handle_leaf_dest_question(
	question_num: int,
	source_node,
	ctx: GraphContext,
	prepared_data: dict,
	ask_input,
	emit_answer,
	on_graph_update=None,
) -> bool:
	nodes = ctx.nodes
	edge_values = ctx.edge_values
	edge_labels = ctx.edge_labels
	node_colors = ctx.node_colors
	is_counter = prepared_data["is_counter"]
	is_family = prepared_data["is_family"]
	ignore_edge_colors = prepared_data["ignore_edge_colors"]
	leaf_dests_map = prepared_data["leaf_dests_map"]

	raw_source_name = nodes.get(source_node, str(source_node))
	source_name = format_console_node_name(raw_source_name)

	if is_counter:
		print(f"Question {question_num}: 🟦 {source_name} → 🟥 [?]", end=' ')
	elif is_family:
		s_gender = detect_gender(node_colors.get(source_node, ''))
		s_parent_term = get_parent_term(s_gender)
		print(f"Question {question_num}: {source_name} ({s_parent_term}) → [?] (Child)", end=' ')
	else:
		print(f"Question {question_num}: {source_name} → [?]", end=' ')

	user_input = ask_input().strip()
	if user_input == '0':
		print("Stopping the game.")
		return False

	found_leaves = sorted(leaf_dests_map[source_node], key=lambda x: str(nodes.get(x, x)).lower())
	diagram = build_leaf_diagram(
		anchor_node=source_node,
		leaf_nodes=found_leaves,
		is_source_question=False,
		nodes_dict=nodes,
		edge_values=edge_values,
		ignore_edge_colors=is_counter or ignore_edge_colors or is_family,
		question_num=question_num,
		node_colors=node_colors,
	)

	if len(found_leaves) == 1:
		c_nid = found_leaves[0]
		c_name = format_console_node_name(nodes.get(c_nid, str(c_nid)))
		if is_family:
			diagram.default_highlight = AnswerHighlight(
				node_ids={source_node},
				edges={(source_node, d) for d in found_leaves},
				diagram=diagram,
				first_node_ids={source_node},
			)
			c_term = get_child_term(detect_gender(node_colors.get(c_nid, '')))
			ans_text = f"{source_name} → {c_name} ({c_term})"
		else:
			ans_text = (
				f"{format_path_string([source_node, c_nid], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)}"
			)
		hl = AnswerHighlight(
			node_ids={source_node, c_nid},
			edges={(source_node, c_nid)},
			diagram=diagram,
			first_node_id=source_node,
		)
		emit_answer(ans_text, hl)
	else:
		for d in found_leaves:
			d_name = format_console_node_name(nodes.get(d, str(d)))
			if is_family:
				c_term = get_child_term(detect_gender(node_colors.get(d, '')))
				ans_text = f"  • {source_name} → {d_name} ({c_term})"
			else:
				ans_text = (
					f"  • {format_path_string([source_node, d], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)}"
				)
			hl = AnswerHighlight(
				node_ids={source_node, d},
				edges={(source_node, d)},
				diagram=diagram,
				first_node_id=source_node,
			)
			emit_answer(ans_text, hl)

	print()
	if on_graph_update is not None:
		on_graph_update(diagram)
	return True