import configparser
import os
import random
import sys
import xml.etree.ElementTree as emTree
import json
from collections import defaultdict
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
		keep_nodes = [str(num) if str(num).startswith('n') else f'n{num}' for num in keep_nodes]
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


def read_from_graph_xml(p_input_file, p_color_threshold=48):
	tree = emTree.parse(p_input_file)
	root = tree.getroot()

	def get_local_tag(elem):
		return elem.tag.split('}', 1)[-1]

	all_nodes = {}
	is_group = {}
	group_children = defaultdict(list)

	# Recursive scanner to map all groups and leaf nodes
	def scan_node(node_elem):
		node_id = node_elem.attrib['id']
		all_nodes[node_id] = node_elem

		foldertype = node_elem.attrib.get('yfiles.foldertype', '').lower()
		has_graph_child = False

		for child in node_elem:
			if get_local_tag(child) == 'graph':
				has_graph_child = True
				for sub_elem in child:
					if get_local_tag(sub_elem) == 'node':
						sub_id = sub_elem.attrib['id']
						group_children[node_id].append(sub_id)
						scan_node(sub_elem)

		has_group_graphics = False
		for elem in node_elem.iter():
			tag = get_local_tag(elem)
			if tag in ('GroupNode', 'ProxyAutoBoundsNode'):
				has_group_graphics = True
				break

		if foldertype in ('group', 'folder') or has_graph_child or has_group_graphics:
			is_group[node_id] = True
		else:
			is_group[node_id] = False

	# Find top-level nodes across graphs
	for elem in root.iter():
		if get_local_tag(elem) == 'graph':
			for child in elem:
				if get_local_tag(child) == 'node' and child.attrib['id'] not in all_nodes:
					scan_node(child)

	# Extract leaf nodes
	for node_id, node_elem in all_nodes.items():
		if not is_group.get(node_id, False):
			node_name = None
			node_val = 0

			# Extract node label
			for sub in node_elem.iter():
				if get_local_tag(sub) == 'NodeLabel' and sub.text and sub.text.strip():
					node_name = sub.text.strip().replace('\r\n', ' ').replace('\n', ' ')
					break

			if not node_name:
				node_name = node_id

			# Extract node color/fill value
			for sub in node_elem.iter():
				if get_local_tag(sub) == 'Fill':
					attrib = sub.attrib
					if attrib.get('hasColor') == 'false' or attrib.get('transparent') == 'true':
						node_val = 0
					elif 'color' in attrib:
						color = attrib['color']
						if color.startswith('#'):
							color = color[1:]
						if color.upper() in ['FFCC00', '99CCFF', 'FFFF00', 'FFFFFF', 'F5F5F5']:
							node_val = 0
						elif len(color) == 6:
							try:
								r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
								node_val = -1 if r > (g + b) / 2 + p_color_threshold else +1 if g > (r + b) / 2 + p_color_threshold else 0
							except ValueError:
								node_val = 0
					break

			nodes[node_id] = node_name
			node_values[node_id] = node_val

	# Helper to resolve all descendant leaf nodes for groups or individual nodes
	def get_leaf_nodes(nid):
		if not is_group.get(nid, False):
			return [nid] if nid in nodes else []
		leaves = []
		stack = [nid]
		visited = set()
		while stack:
			curr = stack.pop()
			if curr in visited:
				continue
			visited.add(curr)
			if not is_group.get(curr, False):
				if curr in nodes:
					leaves.append(curr)
			else:
				for ch in group_children.get(curr, []):
					stack.append(ch)
		return leaves

	# Scan and expand all edges throughout the XML
	edge_set = set()
	for edge_elem in root.iter():
		if get_local_tag(edge_elem) == 'edge':
			source_id = edge_elem.attrib.get('source')
			target_id = edge_elem.attrib.get('target')
			if not source_id or not target_id:
				continue

			# Edge line color
			edge_color = "000000"
			for sub in edge_elem.iter():
				if get_local_tag(sub) == 'LineStyle':
					col = sub.attrib.get('color', '#000000')
					if col.startswith('#'):
						col = col[1:]
					edge_color = col
					break

			try:
				r, g, b = int(edge_color[0:2], 16), int(edge_color[2:4], 16), int(edge_color[4:6], 16)
				val = -1 if r > (g + b) / 2 + p_color_threshold else +1
			except Exception:
				val = +1

			# Edge arrowheads (handles standard, reversed, and bidirectional)
			src_arrow = 'none'
			tgt_arrow = 'standard'
			has_arrows_tag = False
			for sub in edge_elem.iter():
				if get_local_tag(sub) == 'Arrows':
					src_arrow = sub.attrib.get('source', 'none')
					tgt_arrow = sub.attrib.get('target', 'standard')
					has_arrows_tag = True
					break

			if not has_arrows_tag:
				has_forward = True
				has_backward = False
			else:
				has_forward = (tgt_arrow not in ('none', '')) or (src_arrow in ('none', '') and tgt_arrow in ('none', ''))
				has_backward = (src_arrow not in ('none', ''))

			src_leaves = get_leaf_nodes(source_id)
			tgt_leaves = get_leaf_nodes(target_id)

			# Expand interactions to all member nodes
			if has_forward:
				for s in src_leaves:
					for t in tgt_leaves:
						if s != t:
							if (s, t) not in edge_set:
								edges.append((s, t))
								edge_set.add((s, t))
							edge_values[(s, t)] = val

			if has_backward:
				for s in src_leaves:
					for t in tgt_leaves:
						if s != t:
							if (t, s) not in edge_set:
								edges.append((t, s))
								edge_set.add((t, s))
							edge_values[(t, s)] = val

	return nodes, edges, edge_values


def edge_value_string(p_edge_value, is_simple=False):
	if not is_simple:
		return ":--->:" if p_edge_value > 0 else ":--X->:"
	return "→" if p_edge_value > 0 else "-X>"


def edge_value(node1, node2):
	value = edge_values.get((node1, node2))
	if value is not None:
		return value
	return 1  # raise Exception("Edge not found!")


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
	p_html_content += f'<h1>Paths: {p_source_node} → {p_target_node}</h1>'
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
	os.makedirs(OUTPUT_FOLDER, exist_ok=True)
	if not source_node_exists:
		base_file_name = os.path.splitext(os.path.basename(FILE_NAME))[0]
		name = base_file_name if base_file_name else FILE_NAME
	else:
		name = source_node
		if target_node_exists:
			name += " - " + target_node
	file_name = name + '.html'
	file_path = os.path.join(OUTPUT_FOLDER, file_name)

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

	with open(file_path, 'w', encoding="utf-8") as f:
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

	kept_set = set(p_nodes_to_keep)

	# Mark group nodes as kept if any member inside is kept
	def mark_kept_groups(node_elem):
		node_id = node_elem.get('id')
		is_kept = node_id in kept_set
		for child in node_elem:
			if child.tag.split('}', 1)[-1] == 'graph':
				for nested_node in child:
					if nested_node.tag.split('}', 1)[-1] == 'node':
						if mark_kept_groups(nested_node):
							is_kept = True
		if is_kept:
			kept_set.add(node_id)
		return is_kept

	for graph in root.findall('.//graphml:graph', namespaces):
		for node in graph.findall('graphml:node', namespaces):
			mark_kept_groups(node)

	# Remove unkept nodes across all levels
	for graph in root.findall('.//graphml:graph', namespaces):
		nodes_to_delete = []
		for node in graph.findall('graphml:node', namespaces):
			node_id = node.get('id')
			if node_id not in kept_set:
				nodes_to_delete.append(node)

		# Actually remove the nodes
		for node in nodes_to_delete:
			graph.remove(node)

		# Remove edges connected to removed nodes
		edges_to_delete = []
		for edge in graph.findall('graphml:edge', namespaces):
			source = edge.get('source')
			target = edge.get('target')
			if source not in kept_set or target not in kept_set:
				edges_to_delete.append(edge)

		# Actually remove the edges
		for edge in edges_to_delete:
			graph.remove(edge)

	# Write the modified XML
	tree.write(p_output_file, encoding='utf-8', xml_declaration=True)

	with open(p_output_file, 'r', encoding='utf-8') as f:
		content = f.read()

	# Remove standalone attribute if needed
	content = content.replace(' standalone="no"', '')

	with open(p_output_file, 'w', encoding='utf-8') as f:
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
	show_connections_list = config.getboolean(SECTION, 'show_connections_list', fallback=False)
	connections_skipped = config.getint(SECTION, 'connections_skipped', fallback=0)
	enable_non_cycle_printing = config.getboolean(SECTION, 'enable_non_cycle_printing', fallback=False)
	sort_by_len = config.getboolean(SECTION, 'sort_by_len', fallback=False)

	color_threshold = config.getint(SECTION, 'color_threshold', fallback=48)

	folder_path = config.get(SECTION, 'folder_path', fallback='').strip()
	file_name = config.get(SECTION, 'file_name', fallback='').strip()

	block_starting_node_str = config.get(SECTION, 'block_starting_node', fallback='')
	block_starting_node = [x.strip().lower() for x in block_starting_node_str.split(',') if
						   x.strip()] if block_starting_node_str else []

	# Game settings
	chance_irrelevant = config.getfloat(SECTION, 'chance_irrelevant', fallback=0.33)
	if chance_irrelevant > 1.0:
		chance_irrelevant /= 100.0

	chance_indirect = config.getfloat(SECTION, 'chance_indirect', fallback=0.33)
	if chance_indirect > 1.0:
		chance_indirect /= 100.0

	chance_same = config.getfloat(SECTION, 'chance_same', fallback=0.33)
	if chance_same > 1.0:
		chance_same /= 100.0

	max_indirectness = config.getint(SECTION, 'max_indirectness', fallback=3)
	leaf_only = config.getboolean(SECTION, 'leaf_only', fallback=False)

	return (p_source_node, p_target_node, show_only_edges, show_connections_list,
			connections_skipped, enable_non_cycle_printing, sort_by_len,
			color_threshold, folder_path, file_name, block_starting_node,
			chance_irrelevant, chance_indirect, chance_same, max_indirectness, leaf_only)


def show_edges(p_edges, p_html_content):
	p_html_content += '<br>'
	p_html_content += f'<h1 style="color:white;">Edges</h1>'
	for e in p_edges:
		try:
			edge_value_int = edge_values.get((e[0], e[1]), 1)
			edge_value_str = edge_value_string(edge_value_int, True)
			p_html_content += f'<p><span style="color:#AAAAFF">{nodes[e[0]]}</span> <span style="color:#000000">{edge_value_str}</span> <span style="color:#AAAAFF">{nodes[e[1]]}</span></p>'
		except KeyError as ke:
			print(f"KeyError for edge {e}: {ke}")
		except Exception as ex:
			print(f"An error occurred for edge {e}: {ex}")
	return p_html_content


def show_connections_list(p_graph, p_connections_skipped, p_html_content):
	p_html_content += '<br>'
	p_html_content += f'<h1 style="color:white;">Connection List</h1>'

	if p_connections_skipped <= 0:
		# Use direct edges
		for e in edges:
			try:
				source_name = nodes[e[0]]
				target_name = nodes[e[1]]
				p_html_content += f'<p style="color:white;">{source_name} → {target_name}</p>'
				nodes_printed.add(e[0])
				nodes_printed.add(e[1])
			except KeyError as ke:
				print(f"KeyError for edge {e}: {ke}")
			except Exception as ex:
				print(f"An error occurred for edge {e}: {ex}")
	else:
		# Search for simple paths of length: target_length = p_connections_skipped + 1
		target_length = p_connections_skipped + 1
		seen_connections = set()

		for source in p_graph.nodes():
			# Depth First Search for simple paths of a specific length
			stack = [(source, [source])]
			while stack:
				curr, path = stack.pop()
				if len(path) - 1 == target_length:
					seen_connections.add((path[0], path[-1]))
					continue
				for neighbor in p_graph.successors(curr):
					if neighbor not in path:
						stack.append((neighbor, path + [neighbor]))

		# Display connections alphabetically
		sorted_connections = sorted(list(seen_connections), key=lambda x: (nodes.get(x[0], ''), nodes.get(x[1], '')))
		for e in sorted_connections:
			try:
				source_name = nodes[e[0]]
				target_name = nodes[e[1]]
				p_html_content += f'<p style="color:white;">{source_name} → {target_name}</p>'
				nodes_printed.add(e[0])
				nodes_printed.add(e[1])
			except KeyError as ke:
				print(f"KeyError for connection {e}: {ke}")
			except Exception as ex:
				print(f"An error occurred for connection {e}: {ex}")

	return p_html_content


def get_save_file_path(file_name):
	# Use APPDATA on Windows, fallback to home directory on other OS
	appdata = os.getenv('APPDATA')
	if not appdata:
		appdata = os.path.expanduser('~')

	save_dir = os.path.join(appdata, 'YAMLGuessingGame')
	os.makedirs(save_dir, exist_ok=True)

	# Extract filename without path and extension
	base_name = os.path.splitext(os.path.basename(file_name))[0]
	safe_name = "".join([c for c in base_name if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
	if not safe_name:
		safe_name = "default_graph"

	return os.path.join(save_dir, f"{safe_name}_progress.json")


def load_progress(save_path):
	if os.path.exists(save_path):
		try:
			with open(save_path, 'r', encoding='utf-8') as f:
				return json.load(f)
		except Exception as e:
			print(f"Error loading progress: {e}")
	return {}


def save_progress(save_path, progress_data):
	try:
		with open(save_path, 'w', encoding='utf-8') as f:
			json.dump(progress_data, f, indent=4)
	except Exception as e:
		print(f"Error saving progress: {e}")


def create_input_file():
	print(f"Configuration file '{input_file}' not found. Creating a default one.")
	default_content = f"""[{SECTION}]
SOURCE_NODE=
TARGET_NODE=
SHOW_ONLY_EDGES=False
SHOW_CONNECTIONS_LIST=False
CONNECTIONS_SKIPPED=0
ENABLE_NON_CYCLE_PRINTING=True
SORT_BY_LEN=False
COLOR_THRESHOLD=48
FOLDER_PATH=
FILE_NAME=
BLOCK_STARTING_NODE=
CHANCE_SAME=0.1
CHANCE_IRRELEVANT=0.20
CHANCE_INDIRECT=0.35
MAX_INDIRECTNESS=1
LEAF_ONLY=False
"""
	try:
		# Ensure the directory exists before writing the file
		os.makedirs(os.path.dirname(input_file), exist_ok=True)
		with open(input_file, 'w') as f:
			f.write(default_content)
		print("Default configuration file created successfully.")
	except Exception as e:
		print(f"Error creating default configuration file: {e}")


def format_path_string(path):
	parts = [nodes.get(path[0], path[0])]
	for k in range(len(path) - 1):
		u = path[k]
		v = path[k + 1]
		val = edge_values.get((u, v), 1)
		arrow = "→↓" if val < 0 else "→"
		parts.append(f"{arrow} {nodes.get(v, v)}")
	return " ".join(parts)


def run_connection_guessing_game():
	while True:
		try:
			skip_input = input("Enter the number of connections to skip (must be > 0): ").strip()
			con_skipped = int(skip_input)
			if con_skipped > 0:
				break
			else:
				print("Please enter a positive number greater than 0.")
		except ValueError:
			print("Invalid input. Please enter a valid integer.")

	target_length = con_skipped + 1
	all_paths = []

	for source in G.nodes():
		if str(nodes.get(source, source)).lower() in BLOCK_STARTING_NODE:
			continue
		stack = [(source, [source])]
		while stack:
			curr, path = stack.pop()
			if len(path) - 1 == target_length:
				all_paths.append(path)
				continue
			for neighbor in G.successors(curr):
				if neighbor not in path:
					stack.append((neighbor, path + [neighbor]))

	if not all_paths:
		print(f"No connections found with exactly {con_skipped} intermediate elements.")
		return

	paths_by_pair = defaultdict(list)
	for path in all_paths:
		src = path[0]
		tgt = path[-1]
		intermediates = path[1:-1]
		paths_by_pair[(src, tgt)].append(intermediates)

	quiz_cases = list(paths_by_pair.keys())

	save_path = get_save_file_path(FILE_NAME)
	progress_data = load_progress(save_path)

	skip_key = str(con_skipped)
	if skip_key not in progress_data:
		progress_data[skip_key] = {}

	def get_counter_by_node_text(case):
		src_text = nodes.get(case[0], case[0])
		tgt_text = nodes.get(case[1], case[1])
		return progress_data[skip_key].get(f"{src_text},{tgt_text}", 0)

	quiz_cases.sort(key=lambda case: (
		get_counter_by_node_text(case),
		random.random()
	))

	print("Guess the element(s) in-between. Enter 0 to stop.\n")

	for i, (src, tgt) in enumerate(quiz_cases):
		src_name = nodes.get(src, src)
		tgt_name = nodes.get(tgt, tgt)

		pair_key = f"{src_name},{tgt_name}"
		current_counter = progress_data[skip_key].get(pair_key, 0)

		correct_paths = paths_by_pair[(src, tgt)]

		first_full_path = [src] + correct_paths[0] + [tgt]
		q_parts = [src_name]
		for k in range(len(first_full_path) - 1):
			u = first_full_path[k]
			v = first_full_path[k + 1]
			edge_val = edge_values.get((u, v), 1)
			arrow = "→↓" if edge_val < 0 else "→"

			if k < len(first_full_path) - 2:
				q_parts.append(f"{arrow} [?]")
			else:
				q_parts.append(f"{arrow} {tgt_name}")

		question_str = " ".join(q_parts)
		print(f"Question {i + 1}/{len(quiz_cases)} (x{current_counter}): {question_str}", end=' ')

		user_input = input().strip()
		if user_input == '0':
			print("Stopping the game.")
			break

		if len(correct_paths) == 1:
			inter_nodes = correct_paths[0]
			ans_parts = [nodes.get(inter_nodes[0], inter_nodes[0])]
			for k in range(len(inter_nodes) - 1):
				u = inter_nodes[k]
				v = inter_nodes[k + 1]
				edge_val = edge_values.get((u, v), 1)
				arrow = "→ ↓" if edge_val < 0 else "→"
				ans_parts.append(f"{arrow} {nodes.get(v, v)}")
			print(f"Correct answer: {' '.join(ans_parts)}")
		else:
			print("Correct answer(s):")
			for idx, inter_nodes in enumerate(correct_paths):
				ans_parts = [nodes.get(inter_nodes[0], inter_nodes[0])]
				for k in range(len(inter_nodes) - 1):
					u = inter_nodes[k]
					v = inter_nodes[k + 1]
					edge_val = edge_values.get((u, v), 1)
					arrow = "→ ↓" if edge_val < 0 else "→"
					ans_parts.append(f"{arrow} {nodes.get(v, v)}")
				print(f"  Option {idx + 1}: {' '.join(ans_parts)}")

		shorter_paths = list(nx.all_simple_paths(G, source=src, target=tgt, cutoff=target_length - 1))
		if shorter_paths:
			print("More direct connection(s) also exist:")
			shorter_paths.sort(key=len)
			for sp in shorter_paths:
				sp_parts = [nodes.get(sp[0], sp[0])]
				for k in range(len(sp) - 1):
					u = sp[k]
					v = sp[k + 1]
					edge_val = edge_values.get((u, v), 1)
					arrow = "→ ↓" if edge_val < 0 else "→"
					sp_parts.append(f"{arrow} {nodes.get(v, v)}")
				print(f"  {' '.join(sp_parts)}")

		print()
		progress_data[skip_key][pair_key] = current_counter + 1
		save_progress(save_path, progress_data)

	print("Quiz finished.")
	sys.exit(0)


def run_relationship_guessing_game():
	print("\n--- Relationship Guessing Game ---")
	print("Guess if the 2 nodes connect Directly, Indirectly, Share a Source/Destination, or are Irrelevant. Enter 0 to stop.")
	print("[Direct / Indirect / Shared sources/destinations / Irrelevant] (Press Enter to reveal answer, or 0 to quit).\n")

	# Find leaf nodes if LEAF_ONLY is set
	leaf_nodes = set()
	for n in G.nodes():
		if G.in_degree(n) == 0 or G.out_degree(n) == 0:
			leaf_nodes.add(n)

	# Categorize all unordered node pairs
	all_node_list = list(G.nodes())
	direct_pairs = []
	indirect_pairs = []
	same_pairs = []
	irrelevant_pairs = []

	max_cutoff = MAX_INDIRECTNESS + 1

	for i in range(len(all_node_list)):
		for j in range(i + 1, len(all_node_list)):
			u = all_node_list[i]
			v = all_node_list[j]

			if LEAF_ONLY and (u not in leaf_nodes and v not in leaf_nodes):
				continue

			u_name = str(nodes.get(u, u)).lower()
			v_name = str(nodes.get(v, v)).lower()
			if u_name in BLOCK_STARTING_NODE and v_name in BLOCK_STARTING_NODE:
				continue

			# Shared direct sources & shared direct destinations
			shared_srcs = [s for s in set(G.predecessors(u)).intersection(G.predecessors(v)) if s != u and s != v]
			shared_dsts = [d for d in set(G.successors(u)).intersection(G.successors(v)) if d != u and d != v]
			has_shared = bool(shared_srcs or shared_dsts)

			if has_shared:
				same_pairs.append((u, v))

			# Check shortest path in both directions
			has_u_to_v = nx.has_path(G, u, v)
			has_v_to_u = nx.has_path(G, v, u)

			len_u_v = nx.shortest_path_length(G, u, v) if has_u_to_v else float('inf')
			len_v_u = nx.shortest_path_length(G, v, u) if has_v_to_u else float('inf')

			if len_u_v == 1 or len_v_u == 1:
				direct_pairs.append((u, v))
			elif (len_u_v <= max_cutoff) or (len_v_u <= max_cutoff):
				indirect_pairs.append((u, v))
			elif not has_u_to_v and not has_v_to_u and not has_shared:
				irrelevant_pairs.append((u, v))

	if not direct_pairs and not indirect_pairs and not irrelevant_pairs and not same_pairs:
		print("No valid node pairs found matching your graph and filter settings.")
		return

	# Load progress
	save_path = get_save_file_path(FILE_NAME)
	progress_data = load_progress(save_path)
	game2_key = "game2_relationship"
	if game2_key not in progress_data:
		progress_data[game2_key] = {}

	def get_pair_key(u_node, v_node):
		name1 = nodes.get(u_node, u_node)
		name2 = nodes.get(v_node, v_node)
		return ",".join(sorted([name1, name2]))

	question_num = 0
	while True:
		question_num += 1

		# Pick category based on CHANCE_SAME, CHANCE_IRRELEVANT, and CHANCE_INDIRECT
		rand_val = random.random()
		chosen_pool = None

		if rand_val < CHANCE_SAME and same_pairs:
			chosen_pool = same_pairs
		elif rand_val < (CHANCE_SAME + CHANCE_IRRELEVANT) and irrelevant_pairs:
			chosen_pool = irrelevant_pairs
		elif rand_val < (CHANCE_SAME + CHANCE_IRRELEVANT + CHANCE_INDIRECT) and indirect_pairs:
			chosen_pool = indirect_pairs
		elif direct_pairs:
			chosen_pool = direct_pairs
		elif same_pairs:
			chosen_pool = same_pairs
		elif indirect_pairs:
			chosen_pool = indirect_pairs
		elif irrelevant_pairs:
			chosen_pool = irrelevant_pairs

		if not chosen_pool:
			# Fallback if preferred pools are empty
			all_valid = direct_pairs + indirect_pairs + same_pairs + irrelevant_pairs
			if not all_valid:
				print("No pairs available.")
				break
			chosen_pool = all_valid

		# Pick pair with lowest count in the chosen pool
		chosen_pool.sort(key=lambda p: (
			progress_data[game2_key].get(get_pair_key(p[0], p[1]), 0),
			random.random()
		))
		u, v = chosen_pool[0]

		# Randomize display order
		if random.random() > 0.5:
			u, v = v, u

		u_name = nodes.get(u, u)
		v_name = nodes.get(v, v)
		pair_key = get_pair_key(u, v)
		current_counter = progress_data[game2_key].get(pair_key, 0)

		print(f"Question {question_num} (x{current_counter}): {u_name} [?] {v_name}", end=' ')

		user_input = input().strip()
		if user_input == '0':
			print("Stopping the game.")
			break

		# Compute relationship details
		has_u_v = nx.has_path(G, u, v)
		has_v_u = nx.has_path(G, v, u)
		paths_u_v = list(nx.all_shortest_paths(G, u, v)) if has_u_v else []
		paths_v_u = list(nx.all_shortest_paths(G, v, u)) if has_v_u else []

		len_u_v = len(paths_u_v[0]) - 1 if paths_u_v else float('inf')
		len_v_u = len(paths_v_u[0]) - 1 if paths_v_u else float('inf')

		is_direct = (len_u_v == 1 or len_v_u == 1)
		is_indirect = not is_direct and (has_u_v or has_v_u)

		# Find shared sources and shared destinations
		shared_srcs = [s for s in set(G.predecessors(u)).intersection(G.predecessors(v)) if s != u and s != v]
		shared_dsts = [d for d in set(G.successors(u)).intersection(G.successors(v)) if d != u and d != v]

		shared_srcs.sort(key=lambda s: str(nodes.get(s, s)).lower())
		shared_dsts.sort(key=lambda d: str(nodes.get(d, d)).lower())

		# Collect all distinct connection options
		connection_lines = []
		if is_direct:
			if len_u_v == 1 and len_v_u == 1:
				connection_lines.append(f"Direct (⟳): {format_path_string([u, v])} ↔ {format_path_string([v, u])}")
			elif len_u_v == 1:
				connection_lines.append(f"Direct: {format_path_string([u, v])}")
				if has_v_u:
					for p in paths_v_u:
						connection_lines.append(f"Indirect ↩ ({len(p) - 2}): {format_path_string(p)}")
			elif len_v_u == 1:
				connection_lines.append(f"Direct: {format_path_string([v, u])}")
				if has_u_v:
					for p in paths_u_v:
						connection_lines.append(f"Indirect ↩ ({len(p) - 2}): {format_path_string(p)}")
		elif is_indirect:
			if has_u_v:
				for p in paths_u_v:
					connection_lines.append(f"Indirect ({len(p) - 2}): {format_path_string(p)}")
			if has_v_u:
				for p in paths_v_u:
					prefix = "Indirect ↩" if has_u_v else "Indirect"
					connection_lines.append(f"{prefix} ({len(p) - 2}): {format_path_string(p)}")

		for s in shared_srcs:
			connection_lines.append(f"Shared Source: {format_path_string([s, u])}, {format_path_string([s, v])}")

		for d in shared_dsts:
			connection_lines.append(f"Shared Destination: {format_path_string([u, d])}, {format_path_string([v, d])}")

		# Print inline if single path or irrelevant; otherwise print list
		if not connection_lines:
			print("Answer: IRRELEVANT")
		elif len(connection_lines) == 1:
			print(f"Answer: {connection_lines[0]}")
		else:
			print("Answer:")
			for line in connection_lines:
				print(f"  • {line}")

		print()
		progress_data[game2_key][pair_key] = current_counter + 1
		save_progress(save_path, progress_data)

	print("Quiz finished.")
	sys.exit(0)


if __name__ == '__main__':
	if not os.path.exists(input_file):
		create_input_file()
	(source_node, target_node, SHOW_ONLY_EDGES, SHOW_CONNECTIONS_LIST,
	 CONNECTIONS_SKIPPED, ENABLE_NON_CYCLE_PRINTING, SORT_BY_LEN,
	 COLOR_THRESHOLD, FOLDER_PATH, FILE_NAME, BLOCK_STARTING_NODE,
	 CHANCE_IRRELEVANT, CHANCE_INDIRECT, CHANCE_SAME, MAX_INDIRECTNESS, LEAF_ONLY) = read_config_file(input_file)

	# Determine if FILE_NAME is an absolute or full path (contains slashes)
	if '/' in FILE_NAME or '\\' in FILE_NAME or os.path.isabs(FILE_NAME):
		input_graph_ml_file = FILE_NAME if FILE_NAME.endswith('.graphml') else FILE_NAME + '.graphml'
	else:
		input_graph_ml_file = FOLDER_PATH + FILE_NAME + ('' if FILE_NAME.endswith('.graphml') else '.graphml')

	nodes, edges, edge_values = read_from_graph_xml(input_graph_ml_file, COLOR_THRESHOLD)

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
			raise Exception(f"Could not find source node {source_node}")

	if target_node:
		for cycleNodeID in nodes:
			nodeKey = nodes[cycleNodeID]
			if nodeKey.lower() == target_node:
				target_node_id = cycleNodeID
				target_node_exists = True
		if not target_node_exists:
			raise Exception(f"Could not find target node {target_node}")

	G.add_edges_from(edges)

	# --------------------------------------------------------------------------
	# Game Selection Menu
	# --------------------------------------------------------------------------
	print("\n" + "=" * 50)
	print("Select Game Mode:")
	print("  [1] Connection Guessing Game (Guess intermediate nodes)")
	print("  [2] Relationship Guessing Game (Direct / Indirect / Shared source/destination / Irrelevant)")
	print("  [0] No Game (Generate HTML / Graph output only)")
	print("=" * 50)
	game_choice = input("Enter choice (0-2): ").strip()

	if game_choice == '1':
		run_connection_guessing_game()
	elif game_choice == '2':
		run_relationship_guessing_game()

	# --------------------------------------------------------------------------
	# HTML / GraphML Output Generation
	# --------------------------------------------------------------------------
	html_content = ''

	if SHOW_CONNECTIONS_LIST:
		html_content = show_connections_list(G, CONNECTIONS_SKIPPED, html_content)
	else:
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

		if source_node:
			if target_node:
				s = f"Cycles: {Back.LIGHTBLACK_EX}{source_node}{Back.RESET} → {Back.LIGHTBLACK_EX}{target_node}{Back.RESET}\n"
				html_content += f'<h1 style="color:white;">Cycles: {source_node} → {target_node}</h1>'
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

	print(f"Node count: {len(nodes_printed)} / {len(nodes)} ({int(100 * len(nodes_printed) / len(nodes)) if len(nodes) > 0 else 0}%)")

	output_file = OUTPUT_FOLDER + 'output.graphml'
	nodes_to_keep = set(nodes_printed)
	nodes_to_exclude = sorted([nodes[y] for y in nodes if y not in nodes_to_keep])

	print('Irrelevant nodes:')
	for i in nodes_to_exclude:
		print(i, end=', ')
	remove_nodes_from_graphml(input_graph_ml_file, output_file, nodes_to_keep)
	print('\nDone')