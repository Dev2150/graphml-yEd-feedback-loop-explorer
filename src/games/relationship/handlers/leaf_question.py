from src.diagram import AnswerHighlight, build_leaf_diagram
from src.family import detect_gender, get_child_term, get_parent_term
from src.formatters import format_console_node_name, format_path_string
from src.games.relationship.handlers.common import ask_continue
from src.models import GraphContext


def _handle_leaf_question(
	question_num: int,
	anchor_node,
	is_source_question: bool,
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
	leaf_map = prepared_data["leaf_sources_map"] if is_source_question else prepared_data["leaf_dests_map"]

	anchor_name = format_console_node_name(nodes.get(anchor_node, str(anchor_node)))
	anchor_gender = detect_gender(node_colors.get(anchor_node, ''))

	if is_source_question:
		if is_counter:
			prompt = f"🟦 [?] → 🟥 {anchor_name}"
		elif is_family:
			prompt = f"[?] (Parent) → {anchor_name} ({get_child_term(anchor_gender)})"
		else:
			prompt = f"[?] → {anchor_name}"
	else:
		if is_counter:
			prompt = f"🟦 {anchor_name} → 🟥 [?]"
		elif is_family:
			prompt = f"{anchor_name} ({get_parent_term(anchor_gender)}) → [?] (Child)"
		else:
			prompt = f"{anchor_name} → [?]"

	print(f"Question {question_num}: {prompt}", end=' ')
	if not ask_continue(ask_input):
		return False

	found_leaves = sorted(leaf_map[anchor_node], key=lambda x: str(nodes.get(x, x)).lower())
	diagram = build_leaf_diagram(
		anchor_node=anchor_node,
		leaf_nodes=found_leaves,
		is_source_question=is_source_question,
		nodes_dict=nodes,
		edge_values=edge_values,
		ignore_edge_colors=is_counter or ignore_edge_colors or is_family,
		question_num=question_num,
		node_colors=node_colors,
	)

	is_single = len(found_leaves) == 1
	prefix = "" if is_single else "  • "

	for leaf in found_leaves:
		leaf_name = format_console_node_name(nodes.get(leaf, str(leaf)))
		edge = (leaf, anchor_node) if is_source_question else (anchor_node, leaf)

		if is_family:
			leaf_gender = detect_gender(node_colors.get(leaf, ''))
			if is_source_question:
				ans_text = f"{prefix}{leaf_name} ({get_parent_term(leaf_gender)}) → {anchor_name}"
			else:
				ans_text = f"{prefix}{anchor_name} → {leaf_name} ({get_child_term(leaf_gender)})"
		else:
			path = [leaf, anchor_node] if is_source_question else [anchor_node, leaf]
			formatted = format_path_string(
				path, nodes, edge_values, edge_labels,
				ignore_edge_colors=ignore_edge_colors, is_counter=is_counter,
			)
			ans_text = f"{prefix}{formatted}"

		edge_pols = {} if (is_counter or ignore_edge_colors or is_family) \
			else { edge: 1 if edge_values.get(edge, 1) > 0 else -1, }

		hl = AnswerHighlight(
			node_ids={anchor_node, leaf},
			edges={edge},
			diagram=diagram,
			first_node_id=leaf if is_source_question else anchor_node,
			edge_polarities=edge_pols,
		)
		if is_single:
			diagram.default_highlight = hl
		emit_answer(ans_text, hl)

	print()
	if on_graph_update is not None:
		on_graph_update(diagram)
	return True


def handle_leaf_source_question(
	question_num: int,
	target_node,
	ctx: GraphContext,
	prepared_data: dict,
	ask_input,
	emit_answer,
	on_graph_update=None,
) -> bool:
	return _handle_leaf_question(
		question_num, target_node, True, ctx, prepared_data, ask_input, emit_answer, on_graph_update
	)


def handle_leaf_dest_question(
	question_num: int,
	source_node,
	ctx: GraphContext,
	prepared_data: dict,
	ask_input,
	emit_answer,
	on_graph_update=None,
) -> bool:
	return _handle_leaf_question(
		question_num, source_node, False, ctx, prepared_data, ask_input, emit_answer, on_graph_update
	)