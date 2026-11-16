from collections import defaultdict
from typing import List, Optional, Set, Tuple
from xml.etree import ElementTree as emTree
import networkx as nx


def filter_graphml(p_input_file: str, p_output_file: str, keep_nodes=None, keep_edges=None):
	g = nx.read_graphml(p_input_file)

	if keep_nodes is not None:
		keep_nodes = [str(num) if str(num).startswith('n') else f'n{num}' for num in keep_nodes]
		nodes_to_remove = [node for node in g.nodes() if node not in keep_nodes]
		g.remove_nodes_from(nodes_to_remove)

	if keep_edges is not None:
		edges_to_remove = [edge for edge in g.edges(keys=True) if edge[2] not in keep_edges]
		g.remove_edges_from(edges_to_remove)

	for node, data in g.nodes(data=True):
		if 'label' in data:
			data['y:NodeLabel'] = data['label']

	nx.write_graphml(g, p_output_file)


def _get_local_tag(elem) -> str:
	return elem.tag.split('}', 1)[-1]


def _get_own_node_labels(node_elem) -> List[str]:
	"""Extracts non-empty NodeLabel strings from direct <data> children of node_elem (ignoring nested <graph>)."""
	labels: List[str] = []
	for child in node_elem:
		if _get_local_tag(child) == 'data':
			for sub in child.iter():
				if _get_local_tag(sub) == 'NodeLabel' and sub.text and sub.text.strip():
					lbl = sub.text.strip().replace('\r\n', ' ').replace('\n', ' ')
					if lbl not in labels:
						labels.append(lbl)
	return labels


def _scan_graphml_hierarchy(root):
	all_nodes = {}
	is_group = {}
	group_children = defaultdict(list)
	node_own_labels = {}

	def scan_node(node_elem):
		node_id = node_elem.attrib['id']
		all_nodes[node_id] = node_elem
		node_own_labels[node_id] = _get_own_node_labels(node_elem)
		foldertype = node_elem.attrib.get('yfiles.foldertype', '').lower()
		has_graph_child = False

		for child in node_elem:
			if _get_local_tag(child) == 'graph':
				has_graph_child = True
				for sub_elem in child:
					if _get_local_tag(sub_elem) == 'node':
						sub_id = sub_elem.attrib['id']
						group_children[node_id].append(sub_id)
						scan_node(sub_elem)

		has_group_graphics = False
		for child in node_elem:
			if _get_local_tag(child) == 'data':
				for elem in child.iter():
					if _get_local_tag(elem) in ('GroupNode', 'ProxyAutoBoundsNode'):
						has_group_graphics = True
						break
				if has_group_graphics:
					break

		is_group[node_id] = (foldertype in ('group', 'folder') or has_graph_child or has_group_graphics)

	for elem in root.iter():
		if _get_local_tag(elem) == 'graph':
			for child in elem:
				if _get_local_tag(child) == 'node' and child.attrib['id'] not in all_nodes:
					scan_node(child)

	return all_nodes, is_group, group_children, node_own_labels


def list_graph_elements_and_groups(p_input_file: str) -> Tuple[List[str], List[str]]:
	"""Returns (sorted_group_names, sorted_element_names) present in the GraphML file."""
	tree = emTree.parse(p_input_file)
	root = tree.getroot()
	all_nodes, is_group, _, node_own_labels = _scan_graphml_hierarchy(root)

	groups_seen: Set[str] = set()
	elems_seen: Set[str] = set()
	groups: List[str] = []
	elements: List[str] = []

	for nid in all_nodes:
		labels = node_own_labels.get(nid, [])
		display_name = labels[0] if labels else nid
		key = display_name.lower()
		if is_group.get(nid, False):
			if key not in groups_seen:
				groups_seen.add(key)
				groups.append(display_name)
		else:
			if key not in elems_seen:
				elems_seen.add(key)
				elements.append(display_name)

	groups.sort(key=lambda s: s.lower())
	elements.sort(key=lambda s: s.lower())
	return groups, elements


def read_from_graph_xml(
	p_input_file: str,
	p_color_threshold: int = 48,
	excluded_elements: Optional[List[str]] = None,
):
	tree = emTree.parse(p_input_file)
	root = tree.getroot()

	nodes = {}
	node_values = {}
	node_colors = {}
	edges = []
	edge_values = {}
	edge_labels = {}

	all_nodes, is_group, group_children, node_own_labels = _scan_graphml_hierarchy(root)

	excluded_set = {str(x).strip().lower() for x in (excluded_elements or []) if str(x).strip()}
	excluded_ids: Set[str] = set()

	def mark_excluded_subtree(nid: str):
		if nid in excluded_ids:
			return
		excluded_ids.add(nid)
		for ch in group_children.get(nid, []):
			mark_excluded_subtree(ch)

	if excluded_set:
		for nid in all_nodes:
			own_labels = node_own_labels.get(nid, [])
			if nid.lower() in excluded_set or any(lbl.lower() in excluded_set for lbl in own_labels):
				mark_excluded_subtree(nid)

	for node_id, node_elem in all_nodes.items():
		if not is_group.get(node_id, False) and node_id not in excluded_ids:
			own_labels = node_own_labels.get(node_id, [])
			node_name = own_labels[0] if own_labels else node_id
			node_val = 0
			node_color = ""

			for child in node_elem:
				if _get_local_tag(child) != 'data':
					continue
				for sub in child.iter():
					if _get_local_tag(sub) == 'Fill':
						attrib = sub.attrib
						if attrib.get('hasColor') == 'false' or attrib.get('transparent') == 'true':
							node_val = 0
							node_color = ""
						elif 'color' in attrib:
							color = attrib['color']
							node_color = color
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
			node_colors[node_id] = node_color

	def get_leaf_nodes(nid):
		if nid in excluded_ids:
			return []
		if not is_group.get(nid, False):
			return [nid] if nid in nodes else []
		leaves = []
		stack = [nid]
		visited = set()
		while stack:
			curr = stack.pop()
			if curr in visited or curr in excluded_ids:
				continue
			visited.add(curr)
			if not is_group.get(curr, False):
				if curr in nodes:
					leaves.append(curr)
			else:
				for ch in group_children.get(curr, []):
					if ch not in excluded_ids:
						stack.append(ch)
		return leaves

	edge_set = set()
	for edge_elem in root.iter():
		if _get_local_tag(edge_elem) == 'edge':
			source_id = edge_elem.attrib.get('source')
			target_id = edge_elem.attrib.get('target')
			if not source_id or not target_id:
				continue

			src_leaves = get_leaf_nodes(source_id)
			tgt_leaves = get_leaf_nodes(target_id)
			if not src_leaves or not tgt_leaves:
				continue

			edge_color = "000000"
			for sub in edge_elem.iter():
				if _get_local_tag(sub) == 'LineStyle':
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

			edge_label = ""
			for sub in edge_elem.iter():
				if _get_local_tag(sub) == 'EdgeLabel' and sub.text and sub.text.strip():
					edge_label = sub.text.strip().replace('\r\n', ' ').replace('\n', ' ')
					break

			src_arrow = 'none'
			tgt_arrow = 'standard'
			has_arrows_tag = False
			for sub in edge_elem.iter():
				if _get_local_tag(sub) == 'Arrows':
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

			if has_forward:
				for s in src_leaves:
					for t in tgt_leaves:
						if s != t:
							if (s, t) not in edge_set:
								edges.append((s, t))
								edge_set.add((s, t))
							edge_values[(s, t)] = val
							if edge_label:
								edge_labels[(s, t)] = edge_label

			if has_backward:
				for s in src_leaves:
					for t in tgt_leaves:
						if s != t:
							if (t, s) not in edge_set:
								edges.append((t, s))
								edge_set.add((t, s))
							edge_values[(t, s)] = val
							if edge_label:
								edge_labels[(t, s)] = edge_label

	return nodes, edges, edge_values, node_values, edge_labels, node_colors


def remove_nodes_from_graphml(p_input_file: str, p_output_file: str, p_nodes_to_keep: set):
	emTree.register_namespace('', 'http://graphml.graphdrawing.org/xmlns')
	emTree.register_namespace('y', 'http://www.yworks.com/xml/graphml')
	emTree.register_namespace('yed', 'http://www.yworks.com/xml/yed/3')

	tree = emTree.parse(p_input_file)
	root = tree.getroot()

	namespaces = {
		'graphml': 'http://graphml.graphdrawing.org/xmlns',
		'y': 'http://www.yworks.com/xml/graphml',
		'yed': 'http://www.yworks.com/xml/yed/3'
	}

	kept_set = set(p_nodes_to_keep)

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

	for graph in root.findall('.//graphml:graph', namespaces):
		nodes_to_delete = []
		for node in graph.findall('graphml:node', namespaces):
			node_id = node.get('id')
			if node_id not in kept_set:
				nodes_to_delete.append(node)

		for node in nodes_to_delete:
			graph.remove(node)

		edges_to_delete = []
		for edge in graph.findall('graphml:edge', namespaces):
			source = edge.get('source')
			target = edge.get('target')
			if source not in kept_set or target not in kept_set:
				edges_to_delete.append(edge)

		for edge in edges_to_delete:
			graph.remove(edge)

	tree.write(p_output_file, encoding='utf-8', xml_declaration=True)

	with open(p_output_file, 'r', encoding='utf-8') as f:
		content = f.read()

	content = content.replace(' standalone="no"', '')

	with open(p_output_file, 'w', encoding='utf-8') as f:
		f.write(content)


def detect_gender(color: str) -> str:
	"""
	Detects gender from hex color code.
	Returns:
	  'M' for Male (Blue / Cyan hues)
	  'F' for Female (Red / Pink / Magenta hues)
	  'U' for Unknown / Neutral
	"""
	if not color:
		return 'U'
	c = color.strip()
	if c.startswith('#'):
		c = c[1:]
	if len(c) != 6:
		return 'U'

	try:
		r = int(c[0:2], 16)
		g = int(c[2:4], 16)
		b = int(c[4:6], 16)
	except ValueError:
		return 'U'

	if max(r, g, b) - min(r, g, b) < 18:
		return 'U'

	if r > 200 and g > 200 and b < 100:
		return 'U'

	if r > b + 15 and r > g + 15:
		return 'F'
	if r > 180 and b > 140 and r >= b + 10 and g < min(r, b) - 20:
		return 'F'

	if b > r + 15:
		return 'M'
	if b > 180 and g > 140 and b >= r + 10:
		return 'M'

	if r > b + 25:
		return 'F'
	if b > r + 25:
		return 'M'

	return 'U'