from typing import List, Any, Set, Optional
import networkx as nx


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
	result_strs: List[str] = []

	for current_list in sorted_lists:
		current_str = ',' + ','.join(map(str, current_list)) + ','
		is_subsequence = False
		for existing_str in result_strs:
			if current_str in existing_str:
				is_subsequence = True
				break
		if not is_subsequence:
			result.append(current_list)
			result_strs.append(current_str)
	return result


def find_all_paths_for_graph_ml(graph: nx.DiGraph, p_nodes: list, p_source: str, nodes_printed: Set[str], is_reversed: bool = False):
	has_edge = graph.in_degree(p_source) > 0 if is_reversed else graph.out_degree(p_source) > 0
	if not has_edge:
		return
	reach = nx.ancestors(graph, p_source) if is_reversed else nx.descendants(graph, p_source)
	valid_targets = set(p_nodes)
	if any(t in valid_targets and t != p_source and t not in nodes_printed for t in reach):
		nodes_printed.add(p_source)
		nodes_printed.update(reach)


def find_all_paths(graph: nx.DiGraph, all_paths: list, is_reversed: bool, p_nodes: list, p_source: str, cutoff: Optional[int] = None):
	for node_id in p_nodes:
		target = node_id
		source = p_source
		if target != source:
			if is_reversed:
				source, target = target, source
			paths = list(nx.all_simple_paths(graph, source, target, cutoff=cutoff))
			for path in paths:
				all_paths.append(path)
	return all_paths


def sort_alphabetically_by_joining_numerical_string_lists(p_cycles: list, p_nodes: dict) -> list:
	max_length = len(str(len(p_nodes))) + 1

	def sort_key(sublist):
		return ''.join(str(ss).rjust(max_length, '0') for ss in sublist)

	return sorted(p_cycles, key=sort_key)


def find_bounded_cycles(graph: nx.DiGraph, max_len: int) -> list:
	if max_len <= 1:
		return []
	try:
		return list(nx.simple_cycles(graph, length_bound=max_len))
	except TypeError:
		cycles = []
		nodes_list = list(graph.nodes())
		for i, start_node in enumerate(nodes_list):
			valid_nodes = set(nodes_list[i:])
			stack = [(start_node, [start_node])]
			while stack:
				curr, path = stack.pop()
				if len(path) > max_len:
					continue
				for neighbor in graph.successors(curr):
					if neighbor == start_node and len(path) >= 2:
						cycles.append(path)
					elif neighbor in valid_nodes and neighbor not in path:
						if len(path) < max_len:
							stack.append((neighbor, path + [neighbor]))
		return cycles