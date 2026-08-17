import os

import networkx as nx

from src.formatters import get_color_by_node_properties, edge_value, edge_value_string
from src.graph_utils import find_all_paths, remove_duplicate_subsequences, \
	sort_alphabetically_by_joining_numerical_string_lists, find_bounded_cycles, shift_to, find_all_paths_for_graph_ml
from src.io_graphml import remove_nodes_from_graphml
from src.models import GraphContext


def show_all_paths(p_nodes: list, p_source: str, p_html_content: str, ctx: GraphContext, is_reversed: bool = False) -> str:
	p_html_content += '<br>'
	nodes_to_work_with = []

	if p_source is not None:
		p_html_content = add_title_to_html(p_html_content, ctx.nodes, p_source, is_reversed)
		nodes_to_work_with.append(p_source)
	else:
		for node_id in p_nodes:
			nodes_to_work_with.append(node_id)

	all_paths = []
	for source_node in nodes_to_work_with:
		all_paths = find_all_paths(ctx.graph, all_paths, is_reversed, p_nodes, source_node)
		all_paths = remove_duplicate_subsequences(all_paths)
		all_paths = sort_alphabetically_by_joining_numerical_string_lists(all_paths, ctx.nodes)

	for path in all_paths:
		cycle_correlation, nodes_to_traverse, path_len, hp = initialize_printing_nodes(path, False)
		for path_node_id, _ in enumerate(path):
			cycle_correlation, hp = print_node(path, path_node_id, path_len, cycle_correlation, nodes_to_traverse, hp,
											   ctx.config.enable_non_cycle_printing, ctx)
		if ctx.config.enable_non_cycle_printing:
			p_html_content += hp + "</p>"
	return p_html_content


def print_paths_from_source_to_target(p_html_content: str, p_source_node_id: str, p_target_node_id: str,
									  p_source_node: str, p_target_node: str, ctx: GraphContext) -> str:
	p_html_content += '<br>'
	p_html_content += f'<h1>Paths: {p_source_node} → {p_target_node}</h1>'
	all_paths = list(nx.all_simple_paths(ctx.graph, source=p_source_node_id, target=p_target_node_id))
	p_html_content = print_nodes(all_paths, p_html_content, ctx)
	return p_html_content


def print_node(path, path_node_id, path_len, cycle_correlation, nodes_to_traverse, hp, is_printing_to_html, ctx: GraphContext):
	node_id = path[path_node_id % path_len]
	ctx.nodes_printed.add(node_id)
	try:
		node_name = ctx.nodes[node_id]
		convenience = cycle_correlation * ctx.node_values.get(node_id, 0)
		source_label = ctx.nodes.get(ctx.source_node_id, "").lower() if ctx.source_node_id else ""
		target_label = ctx.nodes.get(ctx.target_node_id, "").lower() if ctx.target_node_id else ""
		is_special_node = (target_label and target_label == node_name.lower()) or (source_label and source_label == node_name.lower())

		if is_printing_to_html:
			hp_text_style = ("background-color:black;" if is_special_node else "") + "color:" + get_color_by_node_properties(
				cycle_correlation, convenience)
			hp += '<span style="' + hp_text_style + '">' + node_name + '</span>'

		if path_node_id < nodes_to_traverse - 1:
			edge_correlation = edge_value(path[path_node_id % path_len], path[(path_node_id + 1) % path_len], ctx.edge_values)
			cycle_correlation *= edge_correlation
			if is_printing_to_html:
				str_connector = edge_value_string(edge_correlation, ignore_edge_colors=ctx.config.ignore_edge_colors)
				hp_text_style = "color:" + ("#FFAAAA" if edge_correlation < 0 else "#CCCCCC")
				hp += '<span style="' + hp_text_style + '">' + str_connector + ' </span>'
	except (KeyError, UnicodeError):
		pass
	return cycle_correlation, hp


def print_nodes(all_paths, p_html_content, ctx: GraphContext, is_cycle=False):
	is_printing_to_html = ctx.config.enable_non_cycle_printing or is_cycle
	for path_id, path in enumerate(all_paths):
		cycle_correlation, nodes_to_traverse, path_len, hp = initialize_printing_nodes(path, is_cycle)
		for path_node_id in range(nodes_to_traverse):
			cycle_correlation, hp = print_node(path, path_node_id, path_len, cycle_correlation, nodes_to_traverse, hp,
											   is_printing_to_html, ctx)
		hp += '</span>'

		edge_correlation_str = ''
		if is_cycle:
			try:
				color = get_color_by_node_properties(cycle_correlation, cycle_correlation * ctx.node_values.get(path[0], 0))
			except KeyError:
				p_html_content += f'<p style="color:red">ERROR: There is no nodeValue for {ctx.nodes.get(path[0], path[0])}</p>'
			else:
				edge_correlation_str = '<span style="color:' + color + '"> [V] </span>' if cycle_correlation > 0 else '<span style="color:#FFFF22"> [=] </span>'
		p_html_content += f'<p><span style="color:white">{path_id: >3} ({len(path): >2}) {edge_correlation_str}: </span>{hp}<span>{edge_correlation_str}</span></p>'
	return p_html_content


def initialize_printing_nodes(path, is_cycle):
	hp = "<span>"
	cycle_correlation = 1
	path_len = len(path)
	nodes_to_traverse = path_len + (1 if is_cycle else 0)
	return cycle_correlation, nodes_to_traverse, path_len, hp


def print_to_file(p_html_content: str, output_folder: str, ctx: GraphContext):
	os.makedirs(output_folder, exist_ok=True)
	if not ctx.source_node_id:
		base_file_name = os.path.splitext(os.path.basename(ctx.config.file_name))[0]
		name = base_file_name if base_file_name else ctx.config.file_name
	else:
		name = ctx.config.source_node
		if ctx.target_node_id:
			name += " - " + ctx.config.target_node
	file_name = name + '.html'
	file_path = os.path.join(output_folder, file_name)

	p_html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-16">
	<title>{file_name}</title>
</head>
<body style="background-color:#1E1F22">
""" + p_html_content + """</body>
</html>
"""
	with open(file_path, 'w', encoding="utf-8") as f:
		f.write(p_html_content)
	print(f"HTML file '{file_name}' has been generated.")


def show_edges(p_edges, p_html_content, ctx: GraphContext):
	p_html_content += '<br><h1 style="color:white;">Edges</h1>'
	for e in p_edges:
		try:
			edge_value_int = ctx.edge_values.get((e[0], e[1]), 1)
			edge_value_str = edge_value_string(edge_value_int, is_simple=True, ignore_edge_colors=ctx.config.ignore_edge_colors)
			p_html_content += f'<p><span style="color:#AAAAFF">{ctx.nodes[e[0]]}</span> <span style="color:#000000">{edge_value_str}</span> <span style="color:#AAAAFF">{ctx.nodes[e[1]]}</span></p>'
		except KeyError as ke:
			print(f"KeyError for edge {e}: {ke}")
		except Exception as ex:
			print(f"An error occurred for edge {e}: {ex}")
	return p_html_content


def show_connections_list(p_connections_skipped: int, p_html_content: str, ctx: GraphContext):
	p_html_content += '<br><h1 style="color:white;">Connection List</h1>'

	if p_connections_skipped <= 0:
		for e in ctx.edges:
			try:
				source_name = ctx.nodes[e[0]]
				target_name = ctx.nodes[e[1]]
				p_html_content += f'<p style="color:white;">{source_name} → {target_name}</p>'
				ctx.nodes_printed.add(e[0])
				ctx.nodes_printed.add(e[1])
			except KeyError as ke:
				print(f"KeyError for edge {e}: {ke}")
			except Exception as ex:
				print(f"An error occurred for edge {e}: {ex}")
	else:
		target_length = p_connections_skipped + 1
		seen_connections = set()

		for source in ctx.graph.nodes():
			stack = [(source, [source])]
			while stack:
				curr, path = stack.pop()
				if len(path) - 1 == target_length:
					seen_connections.add((path[0], path[-1]))
					continue
				for neighbor in ctx.graph.successors(curr):
					if neighbor not in path:
						stack.append((neighbor, path + [neighbor]))

		sorted_connections = sorted(list(seen_connections), key=lambda x: (ctx.nodes.get(x[0], ''), ctx.nodes.get(x[1], '')))
		for e in sorted_connections:
			try:
				source_name = ctx.nodes[e[0]]
				target_name = ctx.nodes[e[1]]
				p_html_content += f'<p style="color:white;">{source_name} → {target_name}</p>'
				ctx.nodes_printed.add(e[0])
				ctx.nodes_printed.add(e[1])
			except KeyError as ke:
				print(f"KeyError for connection {e}: {ke}")
			except Exception as ex:
				print(f"An error occurred for connection {e}: {ex}")

	return p_html_content


def generate_html_and_graphml(ctx: GraphContext, output_folder: str, input_graph_ml_file: str):
	html_content = ''

	if ctx.config.max_cycle_length_html > 0:
		cycles = find_bounded_cycles(ctx.graph, ctx.config.max_cycle_length_html)

		if ctx.target_node_id:
			cycles = [cycle for cycle in cycles if ctx.target_node_id in cycle]
		if ctx.source_node_id:
			cycles = [cycle for cycle in cycles if ctx.source_node_id in cycle]
			cycles = [shift_to(cycle, ctx.source_node_id) for cycle in cycles]

		cycles = sort_alphabetically_by_joining_numerical_string_lists(cycles, ctx.nodes)
		if ctx.config.sort_by_len:
			cycles = sorted(cycles, key=len)

		if ctx.config.source_node:
			if ctx.config.target_node:
				html_content += f'<h1 style="color:white;">Cycles: {ctx.config.source_node} → {ctx.config.target_node} ({len(cycles)})</h1>'
			else:
				html_content += f'<h1 style="color:white;">Cycles from: {ctx.config.source_node} ({len(cycles)})</h1>'
		else:
			html_content += f'<h1 style="color:white;">All Cycles / Feedback Loops (max len {ctx.config.max_cycle_length_html}: {len(cycles)})</h1>'

		if cycles:
			html_content = print_nodes(cycles, html_content, ctx, is_cycle=True)
		else:
			html_content += f'<p style="color:#888888;">No feedback loops found with length ≤ {ctx.config.max_cycle_length_html}.</p>'

	if ctx.config.show_connections_list:
		html_content = show_connections_list(ctx.config.connections_skipped, html_content, ctx)
	elif ctx.config.show_only_edges:
		html_content = show_edges(ctx.edges, html_content, ctx)
	else:
		node_ids = list(ctx.nodes.keys())
		if ctx.source_node_id:
			if ctx.target_node_id:
				html_content = print_paths_from_source_to_target(html_content, ctx.source_node_id, ctx.target_node_id,
																 ctx.config.source_node, ctx.config.target_node, ctx)
				html_content = print_paths_from_source_to_target(html_content, ctx.target_node_id, ctx.source_node_id,
																 ctx.config.target_node, ctx.config.source_node, ctx)
			else:
				if ctx.config.enable_non_cycle_printing:
					html_content = show_all_paths(node_ids, ctx.source_node_id, html_content, ctx, is_reversed=True)
					html_content = show_all_paths(node_ids, ctx.source_node_id, html_content, ctx, is_reversed=False)
				else:
					find_all_paths_for_graph_ml(ctx.graph, node_ids, ctx.source_node_id, ctx.nodes_printed, is_reversed=True)
					find_all_paths_for_graph_ml(ctx.graph, node_ids, ctx.source_node_id, ctx.nodes_printed, is_reversed=False)
		else:
			if not ctx.target_node_id:
				html_content = show_all_paths(node_ids, None, html_content, ctx)

	print_to_file(html_content, output_folder, ctx)

	print(f"Node count: {len(ctx.nodes_printed)} / {len(ctx.nodes)} ({int(100 * len(ctx.nodes_printed) / len(ctx.nodes)) if len(ctx.nodes) > 0 else 0}%)")

	output_file = os.path.join(output_folder, 'output.graphml')
	nodes_to_keep = set(ctx.nodes_printed)
	nodes_to_exclude = sorted([ctx.nodes[y] for y in ctx.nodes if y not in nodes_to_keep])

	print('Irrelevant nodes:')
	for i in nodes_to_exclude:
		print(i, end=', ')
	remove_nodes_from_graphml(input_graph_ml_file, output_file, nodes_to_keep)
	print('\nHTML & GraphML files generated.\n')


def add_title_to_html(p_html_content: str, p_nodes: dict, p_source: str, is_reversed: bool) -> str:
	source_name = p_nodes.get(p_source, p_source)
	if not is_reversed:
		p_html_content += f'<h1 style="color:white;">Paths from {source_name}</h1>'
		print(f"\nPaths from {source_name}")
	else:
		p_html_content += f'<h1 style="color:white;">Paths leading to {source_name}</h1>'
		print(f"\nPaths leading to {source_name}")
	return p_html_content