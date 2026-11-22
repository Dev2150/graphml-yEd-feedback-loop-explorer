from collections import defaultdict

from src.diagram import (
	AnswerHighlight,
	build_family_shared_children_diagram,
	build_family_together_diagram,
)
from src.family import detect_gender, get_spouse_term
from src.formatters import format_console_node_name
from src.models import GraphContext


def handle_shared_children_question(
	question_num: int,
	item_data: tuple,
	ctx: GraphContext,
	prepared_data: dict,
	ask_input,
	emit_answer,
	on_graph_update=None,
) -> bool:
	x, children_ids = item_data
	g = ctx.graph
	nodes = ctx.nodes
	node_colors = ctx.node_colors
	parents_map = prepared_data["parents_map"]
	children_map = prepared_data["children_map"]
	spouses_map = prepared_data["spouses_map"]

	x_name = format_console_node_name(nodes.get(x, str(x)))
	child_names = [format_console_node_name(nodes.get(c, str(c))) for c in children_ids]
	children_str = ", ".join(child_names)
	noun = "child" if len(children_ids) == 1 else "children"

	print(f"Question {question_num}: Who shares {noun} {children_str} with {x_name}?", end=' ')

	user_input = ask_input().strip()
	if user_input == '0':
		print("Stopping the game.")
		return False

	shared_by_partner = defaultdict(list)
	for c in children_map.get(x, []):
		for y in parents_map.get(c, []):
			if y != x and c not in shared_by_partner[y]:
				shared_by_partner[y].append(c)

	target_set = set(children_ids)
	partners = [
		y for y, c_list in shared_by_partner.items()
		if set(c_list) == target_set
	]
	if not partners:
		partners = [
			y for y, c_list in shared_by_partner.items()
			if target_set.issubset(set(c_list))
		]
	partners.sort(key=lambda nid: str(nodes.get(nid, nid)).lower())

	diagram = build_family_shared_children_diagram(
		x=x,
		partners=partners,
		children_ids=list(children_ids),
		graph=g,
		nodes_dict=nodes,
		spouses_map=spouses_map,
		question_num=question_num,
		node_colors=node_colors,
	)

	spouse_edge_set = {(e.source_id, e.target_id) for e in diagram.edges if e.bidirectional}

	if len(partners) == 1:
		y = partners[0]
		y_name = format_console_node_name(nodes.get(y, str(y)))
		y_term = get_spouse_term(detect_gender(node_colors.get(y, '')))
		hl_edges = {(x, c) for c in children_ids} | {(y, c) for c in children_ids}
		if (x, y) in spouse_edge_set:
			hl_edges.add((x, y))
		elif (y, x) in spouse_edge_set:
			hl_edges.add((y, x))

		hl = AnswerHighlight(
			node_ids={x, y} | target_set,
			edges=hl_edges,
			diagram=diagram,
			first_node_id=y,
		)
		diagram.default_highlight = hl
		emit_answer(f"{y_name} ({y_term}) ↔ {x_name} (shares: {children_str})", hl)
	else:
		for y in partners:
			y_name = format_console_node_name(nodes.get(y, str(y)))
			y_term = get_spouse_term(detect_gender(node_colors.get(y, '')))
			hl_edges = {(x, c) for c in children_ids} | {(y, c) for c in children_ids}
			if (x, y) in spouse_edge_set:
				hl_edges.add((x, y))
			elif (y, x) in spouse_edge_set:
				hl_edges.add((y, x))

			hl = AnswerHighlight(
				node_ids={x, y} | target_set,
				edges=hl_edges,
				diagram=diagram,
				first_node_id=y,
			)
			emit_answer(f"  • {y_name} ({y_term}) ↔ {x_name} (shares: {children_str})", hl)

	print()
	if on_graph_update is not None:
		on_graph_update(diagram)
	return True


def handle_together_question(
	question_num: int,
	x,
	ctx: GraphContext,
	prepared_data: dict,
	ask_input,
	emit_answer,
	on_graph_update=None,
) -> bool:
	g = ctx.graph
	nodes = ctx.nodes
	node_colors = ctx.node_colors
	parents_map = prepared_data["parents_map"]
	children_map = prepared_data["children_map"]
	spouses_map = prepared_data["spouses_map"]

	x_name = format_console_node_name(nodes.get(x, str(x)))
	print(f"Question {question_num}: Who is together with {x_name}?", end=' ')

	user_input = ask_input().strip()
	if user_input == '0':
		print("Stopping the game.")
		return False

	shared_by_partner = defaultdict(list)
	for c in children_map.get(x, []):
		for y in parents_map.get(c, []):
			if y != x and c not in shared_by_partner[y]:
				shared_by_partner[y].append(c)

	partners = sorted(
		[y for y in spouses_map.get(x, set()) if y != x],
		key=lambda nid: (1 if nid in shared_by_partner else 0, str(nodes.get(nid, nid)).lower()),
	)

	diagram = build_family_together_diagram(
		x=x,
		partners=partners,
		graph=g,
		nodes_dict=nodes,
		question_num=question_num,
		node_colors=node_colors,
	)

	spouse_edge_set = {(e.source_id, e.target_id) for e in diagram.edges if e.bidirectional}

	if len(partners) == 1:
		y = partners[0]
		y_name = format_console_node_name(nodes.get(y, str(y)))
		y_term = get_spouse_term(detect_gender(node_colors.get(y, '')))
		hl_edges = set()
		if (x, y) in spouse_edge_set:
			hl_edges.add((x, y))
		elif (y, x) in spouse_edge_set:
			hl_edges.add((y, x))

		hl = AnswerHighlight(
			node_ids={x, y},
			edges=hl_edges,
			diagram=diagram,
			first_node_id=y,
		)
		diagram.default_highlight = hl
		emit_answer(f"{y_name} ({y_term}) ↔ {x_name}", hl)
	else:
		for y in partners:
			y_name = format_console_node_name(nodes.get(y, str(y)))
			y_term = get_spouse_term(detect_gender(node_colors.get(y, '')))
			hl_edges = set()
			if (x, y) in spouse_edge_set:
				hl_edges.add((x, y))
			elif (y, x) in spouse_edge_set:
				hl_edges.add((y, x))

			shared_c = sorted(shared_by_partner.get(y, []), key=lambda cid: str(nodes.get(cid, cid)).lower())
			suffix = (
				f" (shares: {', '.join(format_console_node_name(nodes.get(c, str(c))) for c in shared_c)})"
				if shared_c else ""
			)
			hl = AnswerHighlight(
				node_ids={x, y},
				edges=hl_edges,
				diagram=diagram,
				first_node_id=y,
			)
			emit_answer(f"  • {y_name} ({y_term}) ↔ {x_name}{suffix}", hl)

	print()
	if on_graph_update is not None:
		on_graph_update(diagram)
	return True