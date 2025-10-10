import configparser
import os
import xml.etree.ElementTree as emTree
from typing import List, Any

import networkx as nx
from colorama import Back

DEBUGGING = True
prefix = 'src//' if DEBUGGING else '_internal//src//'
input_file = prefix + 'input.txt'
OUTPUT_FOLDER = 'output//'

# Define the section name
SECTION = 'SETTINGS'

nodes = {}
node_values = {}
edges = []
edge_values = {}
nodes_printed = set()


def filter_graphml(p_input_file, p_output_file, keep_nodes=None, keep_edges=None):
	g = nx.read_graphml(p_input_file)

	if keep_nodes is not None:
		keep_nodes = [f'n{num}' for num in keep_nodes]
		nodes_to_remove = [node for node in g.nodes()
						   if node not in keep_nodes]
		g.remove_nodes_from(nodes_to_remove)

	if keep_edges is not None:
		edges_to_remove = [edge for edge in g.edges(keys=True)
						   if edge[2] not in keep_edges]
		g.remove_edges_from(edges_to_remove)

	for node, data in g.nodes(data=True):
		if 'label' in data:
			data['y:NodeLabel'] = data['label']

	nx.write_graphml(g, p_output_file)


def shift_to(lst: list, p_target_node):
	if not lst:
		return lst

	min_index = lst.index(p_target_node)

	return lst[min_index:] + lst[:min_index]


def remove_duplicate_subsequences(list_of_lists: List[List[Any]]) -> List[List[Any]]:
	# Sort by length in reverse order. This ensures we check if a shorter list
	# is a sub-sequence of a longer list that has already been added to 'result'.
	sorted_lists = sorted(list_of_lists, key=len, reverse=True)
	result: List[List[Any]] = []

	for current_list in sorted_lists:
		# Convert the current list to a string representation for easy sub-sequence checking.
		# We use a unique separator (e.g., ',') to prevent false matches (e.g., '1' in '10').
		current_str = ','.join(map(str, current_list))

		# Check if the current list (path) is a contiguous sub-sequence of any path already in 'result'.
		is_subsequence = False
		for existing_list in result:
			existing_str = ','.join(map(str, existing_list))
			# Check if the current_str is found contiguously within the existing_str
			if current_str in existing_str:
				is_subsequence = True
				break
		# If the current list is NOT a contiguous sub-sequence of any existing, keep it.
		if not is_subsequence:
			result.append(current_list)
	return result


def find_all_paths_for_graph_ml(p_nodes, p_source, is_reversed=False):
	for _, nodeID in enumerate(p_nodes):
		target = nodeID
		source = p_source
		if target == source or target in nodes_printed:
			continue
		if is_reversed:
			source, target = target, source
		paths = list(nx.all_simple_paths(G, source, target))
		for path in paths:
			for node in path:
				nodes_printed.add(node)


def show_all_paths(p_nodes, p_source, p_html_content, is_reversed=False):
	p_html_content += '<br>'

	nodes_to_work_with = []

	if p_source != -1:
		p_html_content = add_title_to_html(p_html_content, p_nodes, p_source, is_reversed)
		nodes_to_work_with.append(p_source)
	else:
		for _, nodeID in enumerate(p_nodes):
			p_source = nodeID
			nodes_to_work_with.append(p_source)

	all_paths = []
	for p_source in nodes_to_work_with:
		all_paths = find_all_paths(all_paths, is_reversed, p_nodes, p_source)

		all_paths = remove_duplicate_subsequences(all_paths)
		all_paths = sort_alphabetically_by_joining_numerical_string_lists(all_paths, p_nodes)

	for path in all_paths:
		cycle_correlation, nodes_to_traverse, path_len, hp = initialize_printing_nodes(path, False)
		for pathNodeID, nodeID in enumerate(path):
			cycle_correlation, hp = print_node(path, pathNodeID, path_len, cycle_correlation, nodes_to_traverse, hp,
											   ENABLE_NON_CYCLE_PRINTING)
		# print(sp)
		if ENABLE_NON_CYCLE_PRINTING:
			p_html_content += hp + "</p>"
	return p_html_content


def add_title_to_html(p_html_content, p_nodes, p_source, is_reversed):
	if not is_reversed:
		p_html_content += f'<h1 style="color:white;">Paths from {p_nodes[p_source]}</h1>'
		print(f"\nPaths from {p_nodes[p_source]}")
	else:
		p_html_content += f'<h1 style="color:white;">Paths leading to {p_nodes[p_source]}</h1>'
		print(f"\nPaths leading to {p_nodes[p_source]}")
	return p_html_content


def find_all_paths(all_paths, is_reversed, p_nodes, p_source):
	for _, nodeID in enumerate(p_nodes):
		target = nodeID
		source = p_source
		if target != source:
			if is_reversed:
				source, target = target, source
			paths = list(nx.all_simple_paths(G, source, target))
			for path in paths:
				all_paths.append(path)
	return all_paths


def find_node(child):
	node_id = child.attrib['id'].replace('n', '')
	if node_id == "91::0":
		pass
	for dataNode in child:
		tag = dataNode.tag.split('}', 1)[-1]
		if tag == 'data':
			key = dataNode.attrib['key']
			if key == "d6":
				d6_descendant = dataNode[0]
				if d6_descendant.tag.split('}', 1)[-1] == 'ShapeNode':
					node_name = d6_descendant[3].text.replace("\n", " ")
					attrib = d6_descendant[1].attrib
					if 'hasColor' in attrib and attrib['hasColor'] == 'false':
						node_values[node_id] = 0
					else:
						color = attrib['color'][1:]
						if color in ['FFCC00', '99CCFF', 'FFFF00']:  # noqa: spellcheck
							node_values[node_id] = 0
						else:
							r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
							node_values[node_id] = -1 if r > (g + b) / 2 + COLOR_THRESHOLD else + 1 if g > (
									r + b) / 2 + COLOR_THRESHOLD else 0
					nodes[node_id] = node_name
				else:
					d6_descendant = d6_descendant[0][0]
					for element in d6_descendant:
						if element.tag.split('}', 1)[-1] == 'NodeLabel':
							node_name = d6_descendant[3].text.replace("\n", " ")
							nodes[node_id] = node_name
		elif tag == 'graph':
			for dataNodeChild in dataNode:
				find_node(dataNodeChild)


def read_from_graph_xml(p_input_file):
	tree = emTree.parse(p_input_file)
	root = tree.getroot()

	# Iterate through elements
	children = root[len(root) - 2]
	for child in children:
		tag = child.tag.split('}', 1)[-1]
		if tag == 'node':
			find_node(child)
		elif tag == 'edge':
			edge_id = child.attrib['id'].replace('e', '')
			source = child.attrib['source'][1:].replace('n', '')
			target = child.attrib['target'][1:].replace('n', '')
			for data in child:
				if data.attrib['key'] == "d10":
					edge_color = data[0][1].attrib['color'][1:]
					r, g, b = int(edge_color[0:2], 16), int(edge_color[2:4], 16), int(edge_color[4:6], 16)
					edges.append((source, target))
					edge_values[edge_id] = -1 if r > (g + b) / 2 + COLOR_THRESHOLD else +1

	return nodes, edges, edge_values


def edge_value_string(p_edge_value, is_simple=False):
	if not is_simple:
		return ":--->:" if p_edge_value > 0 else ":--X->:"
	return "->" if p_edge_value > 0 else "-X>"


def edge_value(node1, node2):
	for idEdge, e in enumerate(edges):
		if e[0] == node1 and e[1] == node2:
			value = edge_values.get(str(idEdge))
			if value:
				return value
	raise Exception("Edge not found!")


def rgb_print(text, r, g, b):
	return f"\033[38;2;{r};{g};{b}m{text}\033[0m"


def set_text_color_by_node_properties(text, cycle_correlation, convenience):
	if convenience < 0:
		return rgb_print(text, 255, 0, 0) if cycle_correlation > 0 else rgb_print(text, 255, 155, 155)
	if convenience > 0:
		return rgb_print(text, 0, 255, 0) if cycle_correlation > 0 else rgb_print(text, 155, 255, 155)
	return rgb_print(text, 255, 255, 255) if cycle_correlation > 0 else rgb_print(text, 96, 96, 96)


def get_color_by_node_properties(cycle_correlation, convenience):
	if convenience < 0:
		return "#FF0000" if cycle_correlation > 0 else "#FFAAAA"
	if convenience > 0:
		return "#00FF00" if cycle_correlation > 0 else "#AAFFAA"
	return "#FFFFFF" if cycle_correlation > 0 else "#777777"


def print_paths_from_source_to_target(p_html_content, p_source_node_id, p_target_node_id, p_source_node, p_target_node):
	p_html_content += '<br>'
	p_html_content += f'<h1>Paths: {p_source_node} -> {p_target_node}</h1>'
	# print(f"\n {Fore.RESET}Paths: {sourceNode} -> {targetNode}")
	all_paths = list(nx.all_simple_paths(G, source=p_source_node_id, target=p_target_node_id))
	p_html_content = print_nodes(all_paths, p_html_content)
	return p_html_content


def sort_alphabetically_by_joining_numerical_string_lists(p_cycles, p_nodes):
	max_length = len(str(len(p_nodes))) + 1

	def sort_key(sublist):
		return ''.join(ss.rjust(max_length, '0') for ss in sublist)

	p_cycles = sorted(p_cycles, key=sort_key)
	return p_cycles


def print_node(path, path_node_id, path_len, cycle_correlation, nodes_to_traverse, hp, is_printing_to_html):
	node_id = path[path_node_id % path_len]
	nodes_printed.add(node_id)
	try:
		node_name = nodes[node_id]
		convenience = cycle_correlation * node_values[node_id]
		is_special_node = target_node == node_name or source_node == node_name
		if is_printing_to_html:
			hp_text_style = (
								"background-color:black;" if is_special_node else "") + "color:" + get_color_by_node_properties(
				cycle_correlation, convenience)
			hp += '<span style="' + hp_text_style + '">' + node_name + '</span>'
		if path_node_id < nodes_to_traverse - 1:
			edge_correlation = edge_value(path[path_node_id % path_len], path[(path_node_id + 1) % path_len])
			cycle_correlation *= edge_correlation
			if is_printing_to_html:
				str_connector = edge_value_string(edge_correlation)
				hp_text_style = "color:" + ("#AAAAFF" if edge_correlation < 0 else "#000000")
				hp += '<span style="' + hp_text_style + '">' + str_connector + ' </span>'
	except KeyError:
		pass
	except UnicodeError:
		pass
	return cycle_correlation, hp


def print_nodes(all_paths, p_html_content, is_cycle=False):
	is_printing_to_html = ENABLE_NON_CYCLE_PRINTING or is_cycle
	for pathID, path in enumerate(all_paths):
		cycle_correlation, nodes_to_traverse, path_len, hp = initialize_printing_nodes(path, is_cycle)
		for pathNodeID in range(nodes_to_traverse):
			cycle_correlation, hp = print_node(path, pathNodeID, path_len, cycle_correlation, nodes_to_traverse, hp,
											   is_printing_to_html)
		hp += '</span>'

		edge_correlation_str3 = ''
		if is_cycle:
			try:
				color = get_color_by_node_properties(cycle_correlation, cycle_correlation * node_values[path[0]])
			except KeyError:
				p_html_content += f'<p style="color:red">ERROR: There is no nodeValue for {nodes[path[0]]}</p>'
			else:
				edge_correlation_str3 = '<span style="color:' + color + '"> [V] </span>' if cycle_correlation > 0 else '<span style="color:#FFFF22"> [=] </span>'
		p_html_content += f'<p><span style="color:white">{pathID: >3} ({len(path): >2}) {edge_correlation_str3}: </span>{hp}<span>{edge_correlation_str3}</span></p>'
	return p_html_content


def initialize_printing_nodes(path, is_cycle):
	hp = "<span>"
	cycle_correlation = 1
	path_len = len(path)
	nodes_to_traverse = path_len + (1 if is_cycle else 0)
	return cycle_correlation, nodes_to_traverse, path_len, hp


def print_to_file(p_html_content: str):
	if not source_node_exists:
		name = FILE_NAME
	else:
		name = source_node
		if target_node_exists:
			name += " - " + target_node
	file_name = name + '.html'
	file_path = OUTPUT_FOLDER + file_name

	p_html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-16">
        <title>{file_name}</title>
    </head>
    <body style="background-color:#1E1F22">
    """ + p_html_content

	p_html_content += """</body>
    </html>
    """

	with open(file_path, 'w') as f:
		f.write(p_html_content)
	print(f"HTML file '{file_name}' has been generated.")


def remove_nodes_from_graphml(p_input_file, p_output_file, p_nodes_to_keep):
	# Register namespaces to ensure proper parsing
	emTree.register_namespace('', 'http://graphml.graphdrawing.org/xmlns')
	emTree.register_namespace('y', 'http://www.yworks.com/xml/graphml')
	emTree.register_namespace('yed', 'http://www.yworks.com/xml/yed/3')

	# Parse the XML tree
	tree = emTree.parse(p_input_file)
	root = tree.getroot()

	# Define namespaces for finding elements
	namespaces = {
		'graphml': 'http://graphml.graphdrawing.org/xmlns',
		'y': 'http://www.yworks.com/xml/graphml',
		'yed': 'http://www.yworks.com/xml/yed/3'
	}

	# Find the graph element
	graph = root.find('.//graphml:graph', namespaces)

	# Remove specified nodes
	if graph is not None:
		nodes_to_delete = set()
		for node in graph.findall('graphml:node', namespaces):
			node_id = node.get('id')
			if node_id not in p_nodes_to_keep:
				nodes_to_delete.add(node)

		# Actually remove the nodes
		for node in nodes_to_delete:
			graph.remove(node)

		# Remove edges connected to removed nodes
		edges_to_delete = []
		for edge in graph.findall('graphml:edge', namespaces):
			source = edge.get('source')
			target = edge.get('target')

			if source not in p_nodes_to_keep or target not in p_nodes_to_keep:
				edges_to_delete.append(edge)

		# Actually remove the edges
		for edge in edges_to_delete:
			graph.remove(edge)

	# Write the modified XML
	tree.write(p_output_file, encoding='utf-8', xml_declaration=True)

	# Optionally, manually fix the XML to ensure proper formatting
	with open(p_output_file, 'r') as f:
		content = f.read()

	# Remove standalone attribute if needed
	content = content.replace(' standalone="no"', '')

	with open(p_output_file, 'w') as f:
		f.write(content)


def read_config_file(p_input_file):
	config = configparser.ConfigParser()

	# Read the file. Note: configparser is case-insensitive for keys by default.
	config.read(p_input_file)

	# Safely get values with type conversion and defaults
	p_source_node = config.get(SECTION, 'source_node', fallback='').lower()
	p_target_node = config.get(SECTION, 'target_node', fallback='').lower()

	# configparser has built-in methods for booleans and integers
	show_only_edges = config.getboolean(SECTION, 'show_only_edges', fallback=False)
	enable_non_cycle_printing = config.getboolean(SECTION, 'enable_non_cycle_printing', fallback=False)
	sort_by_len = config.getboolean(SECTION, 'sort_by_len', fallback=False)

	color_threshold = config.getint(SECTION, 'color_threshold', fallback=48)

	folder_path = config.get(SECTION, 'folder_path', fallback='').strip()
	file_name = config.get(SECTION, 'file_name', fallback='').strip()

	return p_source_node, p_target_node, show_only_edges, enable_non_cycle_printing, sort_by_len, color_threshold, folder_path, file_name


def show_edges(p_edges, p_html_content):
	p_html_content += '<br>'
	p_html_content += f'<h1 style="color:white;">Edges</h1>'
	for edge_id, e in enumerate(p_edges):
		try:
			edge_value_int = edge_values.get(str(edge_id))
			edge_value_str = edge_value_string(edge_value_int, True)
			p_html_content += f'<p><span style="color:#AAAAFF">{nodes[e[0]]}</span> <span style="color:#000000">{edge_value_str}</span> <span style="color:#AAAAFF">{nodes[e[1]]}</span></p>'
		except KeyError as ke:
			print(f"KeyError for edge {e} with ID {edge_id}: {ke}")
		except Exception as ex:
			print(f"An error occurred for edge {e} with ID {edge_id}: {ex}")
	return p_html_content


def create_input_file():
	print(f"Configuration file '{input_file}' not found. Creating a default one.")
	default_content = f"""[{SECTION}]
SOURCE_NODE=
TARGET_NODE=
SHOW_ONLY_EDGES=False
ENABLE_NON_CYCLE_PRINTING=True
SORT_BY_LEN=False
COLOR_THRESHOLD=48
FOLDER_PATH=
FILE_NAME=
"""
	try:
		# Ensure the directory exists before writing the file
		os.makedirs(os.path.dirname(input_file), exist_ok=True)
		with open(input_file, 'w') as f:
			f.write(default_content)
		print("Default configuration file created successfully.")
	except Exception as e:
		print(f"Error creating default configuration file: {e}")


if __name__ == '__main__':
	if not os.path.exists(input_file):
		create_input_file()
	source_node, target_node, SHOW_ONLY_EDGES, ENABLE_NON_CYCLE_PRINTING, SORT_BY_LEN, COLOR_THRESHOLD, FOLDER_PATH, FILE_NAME = read_config_file(
		input_file)

	input_graph_ml_file = FOLDER_PATH + FILE_NAME + '.graphml'
	nodes, edges, edge_values = read_from_graph_xml(input_graph_ml_file)

	G = nx.DiGraph()
	G.add_nodes_from(nodes.keys())

	source_node_exists = False
	target_node_exists = False
	source_node_id = -1
	target_node_id = -1
	if source_node:
		for cycleNodeID in nodes:
			nodeKey = nodes[cycleNodeID]
			if nodeKey.lower() == source_node:
				source_node_id = cycleNodeID
				source_node_exists = True

		if not source_node_exists:
			raise Exception(f"Cound not find source node {source_node}")

	if target_node:
		for cycleNodeID in nodes:
			nodeKey = nodes[cycleNodeID]
			if nodeKey.lower() == target_node:
				target_node_id = cycleNodeID
				target_node_exists = True
		if not target_node_exists:
			raise Exception(f"Cound not find target node {target_node}")

	G.add_edges_from(edges)
	cycles = list(nx.simple_cycles(G))

	if target_node_exists:
		cycles = [cycle for cycle in cycles if target_node_id in cycle]
	if source_node_exists:
		cycles = [cycle for cycle in cycles if source_node_id in cycle]

		newCycles = []
		for cycle in cycles:
			newCycles.append(shift_to(cycle, source_node_id))
		cycles = newCycles

	cycles = sort_alphabetically_by_joining_numerical_string_lists(cycles, nodes)
	if SORT_BY_LEN:
		cycles = sorted(cycles, key=len)

	html_content = ''
	if source_node:
		if target_node:
			s = f"Cycles: {Back.LIGHTBLACK_EX}{source_node}{Back.RESET} -> {Back.LIGHTBLACK_EX}{target_node}{Back.RESET}\n"
			html_content += f'<h1 style="color:white;">Cycles: {source_node} -> {target_node}</h1>'
		else:
			s = f"Cycles from: {Back.BLACK}{source_node}{Back.RESET}\n"
			html_content += f'<h1 style="color:white;">Cycles from: {source_node}</h1>'

	html_content = print_nodes(cycles, html_content, True)

	if SHOW_ONLY_EDGES:
		html_content = show_edges(edges, html_content)
	else:
		if source_node_exists:
			if target_node_exists:
				html_content = print_paths_from_source_to_target(html_content, source_node_id, target_node_id,
																 source_node,
																 target_node)
				html_content = print_paths_from_source_to_target(html_content, target_node_id, source_node_id,
																 target_node,
																 source_node)
			else:
				if ENABLE_NON_CYCLE_PRINTING:
					html_content = show_all_paths(nodes, source_node_id, html_content, True)
					html_content = show_all_paths(nodes, source_node_id, html_content)
				else:
					find_all_paths_for_graph_ml(nodes, source_node_id, True)
					find_all_paths_for_graph_ml(nodes, source_node_id)
		else:
			if not target_node_exists:
				html_content = show_all_paths(nodes, source_node_id, html_content)

	print_to_file(html_content)

	print(f"Node count: {len(nodes_printed)} / {len(nodes)} ({int(100 * len(nodes_printed) / len(nodes))}%)")

	output_file = OUTPUT_FOLDER + 'output.graphml'
	nodes_to_keep = [f'n{num}' for num in nodes_printed]
	nodes_to_exclude = sorted([nodes[y] for y in [x for x in nodes if x not in nodes_to_keep]])

	print('Irrelevant nodes:')
	for i in nodes_to_exclude:
		print(i, end=', ')
	remove_nodes_from_graphml(input_graph_ml_file, output_file, nodes_to_keep)
	print('\nDone')
