from collections import defaultdict

import networkx as nx

from src.family import (
	FAMILY_CONNECTION_TYPES,
	analyze_family_pair,
	build_family_structures,
	compute_all_ancestors,
)
from src.formatters import COUNTER_CONNECTION_TYPES
from src.games.relationship.progress import get_canonical_cycle_tuple
from src.graph_utils import find_bounded_cycles
from src.models import GraphContext


def _build_leaf_maps(g: nx.DiGraph, nodes: dict, block_starting_node: list, leaf_only: bool,
					root_nodes: set, terminal_nodes: set, parents_map=None, children_map=None):
	leaf_sources_map = defaultdict(list)
	leaf_dests_map = defaultdict(list)

	for target in g.nodes():
		preds = list(parents_map.get(target, [])) if parents_map is not None else list(g.predecessors(target))
		if preds and (not leaf_only or target in terminal_nodes or any(p in root_nodes for p in preds)):
			leaf_sources_map[target] = preds

	for source in g.nodes():
		succs = list(children_map.get(source, [])) if children_map is not None else list(g.successors(source))
		if succs and (not leaf_only or source in root_nodes or any(s in terminal_nodes for s in succs)):
			leaf_dests_map[source] = succs

	blocked = set(block_starting_node)
	leaf_items = (
		[('leaf_src', n) for n in leaf_sources_map if str(nodes.get(n, n)).lower() not in blocked]
		+ [('leaf_dst', n) for n in leaf_dests_map if str(nodes.get(n, n)).lower() not in blocked]
	)
	return leaf_sources_map, leaf_dests_map, leaf_items


def _find_valid_cycles(g: nx.DiGraph, nodes: dict, max_cycle_length: int, block_starting_node: list):
	if max_cycle_length < 2:
		return []
	blocked = set(block_starting_node)
	valid_cycles = []
	seen_cycles = set()
	for cyc in find_bounded_cycles(g, max_cycle_length):
		if len(cyc) < 2 or len(cyc) > max_cycle_length:
			continue
		if all(str(nodes.get(n, n)).lower() in blocked for n in cyc):
			continue
		canonical = tuple(get_canonical_cycle_tuple(cyc, nodes))
		if canonical not in seen_cycles:
			seen_cycles.add(canonical)
			valid_cycles.append(list(canonical))
	return valid_cycles


def _iter_unblocked_pairs(node_list: list, nodes: dict, blocked: set, leaf_only: bool, leaf_nodes: set):
	for i in range(len(node_list)):
		u = node_list[i]
		u_blocked = str(nodes.get(u, u)).lower() in blocked
		for j in range(i + 1, len(node_list)):
			v = node_list[j]
			if leaf_only and (u not in leaf_nodes and v not in leaf_nodes):
				continue
			if u_blocked and str(nodes.get(v, v)).lower() in blocked:
				continue
			yield u, v


def _prepare_family_categories(
	all_node_list, nodes, node_colors, parents_map, children_map, spouses_map,
	ancestor_paths, ancestor_dist, valid_cycles, leaf_items, leaf_only, leaf_nodes, blocked,
):
	buckets = defaultdict(list)
	family_results_cache = {}

	for u, v in _iter_unblocked_pairs(all_node_list, nodes, blocked, leaf_only, leaf_nodes):
		res = analyze_family_pair(
			u, v, nodes, node_colors, parents_map, children_map,
			spouses_map, ancestor_paths, ancestor_dist,
		)
		family_results_cache[(u, v)] = res
		family_results_cache[(v, u)] = res
		buckets[res.category].append((res.category, (u, v)))

	shared_children_items = []
	together_items = []
	for x in all_node_list:
		if str(nodes.get(x, x)).lower() in blocked:
			continue
		shared_by_partner = defaultdict(list)
		for c in children_map.get(x, []):
			for y in parents_map.get(c, []):
				if y != x and c not in shared_by_partner[y]:
					shared_by_partner[y].append(c)

		children_groups = defaultdict(list)
		for y, c_list in shared_by_partner.items():
			if leaf_only and (x not in leaf_nodes and y not in leaf_nodes):
				continue
			sorted_c = tuple(sorted(c_list, key=lambda cid: (str(nodes.get(cid, cid)).lower(), str(cid))))
			children_groups[sorted_c].append(y)

		for sorted_c in sorted(children_groups.keys(), key=lambda cs: [str(nodes.get(c, c)).lower() for c in cs]):
			shared_children_items.append(('shared_children', (x, sorted_c)))

		if any(
			y != x and y not in shared_by_partner and (not leaf_only or (x in leaf_nodes or y in leaf_nodes))
			for y in spouses_map.get(x, set())
		):
			together_items.append(('together', x))

	partner_items = shared_children_items + together_items
	cycle_items = [('cycle', cyc) for cyc in valid_cycles]

	category_config = [
		('Cycle', cycle_items),
		('Single', leaf_items),
		('Partner', partner_items),
		('Parent/Child', buckets['parent_child']),
		('Grandparent+', buckets['grandparent']),
		('Sibling', buckets['sibling']),
		('Uncle/Aunt', buckets['uncle_nephew']),
		('1st Cousin', buckets['first_cousin']),
		('2nd/3rd Cousin', buckets['second_third_cousin']),
		('In-Law', buckets['in_law']),
		('Irrelevant', buckets['irrelevant']),
	]
	all_relevant_items = [it for cat, items in category_config if cat != 'Irrelevant' for it in items]
	return family_results_cache, all_relevant_items, buckets['irrelevant'], category_config


def _prepare_standard_categories(
	g, all_node_list, nodes, valid_cycles, leaf_items, leaf_only, leaf_nodes, blocked, max_indirectness_game,
):
	max_cutoff = max_indirectness_game + 1
	direct_items, indirect_items, same_items, irrelevant_items = [], [], [], []

	for u, v in _iter_unblocked_pairs(all_node_list, nodes, blocked, leaf_only, leaf_nodes):
		has_shared = bool(
			(set(g.predecessors(u)) & set(g.predecessors(v))) - {u, v}
			or (set(g.successors(u)) & set(g.successors(v))) - {u, v}
		)
		has_u_to_v = nx.has_path(g, u, v)
		has_v_to_u = nx.has_path(g, v, u)
		len_u_v = nx.shortest_path_length(g, u, v) if has_u_to_v else float('inf')
		len_v_u = nx.shortest_path_length(g, v, u) if has_v_to_u else float('inf')

		if len_u_v == 1 or len_v_u == 1:
			direct_items.append(('direct', (u, v)))
		elif len_u_v <= max_cutoff or len_v_u <= max_cutoff:
			indirect_items.append(('indirect', (u, v)))
		elif has_shared:
			same_items.append(('same', (u, v)))
		elif not has_u_to_v and not has_v_to_u:
			irrelevant_items.append(('irrelevant', (u, v)))

	cycle_items = [('cycle', cyc) for cyc in valid_cycles]
	category_config = [
		('Cycle', cycle_items),
		('Single', leaf_items),
		('Direct', direct_items),
		('Indirect', indirect_items),
		('Same/Shared', same_items),
		('Irrelevant', irrelevant_items),
	]
	all_relevant_items = cycle_items + leaf_items + direct_items + indirect_items + same_items
	return all_relevant_items, irrelevant_items, category_config


def prepare_relationship_game_data(ctx: GraphContext) -> dict:
	g = ctx.graph
	nodes = ctx.nodes
	edge_labels = ctx.edge_labels
	node_colors = ctx.node_colors
	config = ctx.config
	blocked = set(config.block_starting_node)

	conn_type = getattr(config, 'connection_type', 'correlation').lower()
	is_counter = conn_type in COUNTER_CONNECTION_TYPES
	is_family = conn_type in FAMILY_CONNECTION_TYPES
	ignore_edge_colors = config.ignore_edge_colors or is_counter or is_family

	if is_family:
		text_shared_source, text_shared_dest = "Parents", "Children"
	elif is_counter:
		text_shared_source, text_shared_dest = "Common threat", "Common counter"
	else:
		text_shared_source, text_shared_dest = "Common cause (Confounder)", "Common effect (Collider)"

	parents_map = children_map = spouses_map = ancestor_paths = ancestor_dist = None
	if is_family:
		parents_map, children_map, spouses_map = build_family_structures(g, edge_labels)
		root_nodes = {n for n in g.nodes() if not parents_map.get(n)}
		terminal_nodes = {n for n in g.nodes() if not children_map.get(n)}
	else:
		root_nodes = {n for n in g.nodes() if g.in_degree(n) == 0}
		terminal_nodes = {n for n in g.nodes() if g.out_degree(n) == 0}
	leaf_nodes = root_nodes | terminal_nodes

	leaf_sources_map, leaf_dests_map, leaf_items = _build_leaf_maps(
		g, nodes, config.block_starting_node, config.leaf_only,
		root_nodes, terminal_nodes, parents_map, children_map,
	)

	if is_family:
		cycle_graph = nx.DiGraph()
		cycle_graph.add_nodes_from(g.nodes())
		for p, chs in children_map.items():
			for c in chs:
				cycle_graph.add_edge(p, c)
		valid_cycles = _find_valid_cycles(cycle_graph, nodes, config.max_cycle_length_game, config.block_starting_node)
	else:
		valid_cycles = _find_valid_cycles(g, nodes, config.max_cycle_length_game, config.block_starting_node)

	all_node_list = list(g.nodes())

	if is_family:
		ancestor_paths, ancestor_dist = compute_all_ancestors(all_node_list, parents_map)
		family_results_cache, all_relevant_items, irrelevant_items, category_config = _prepare_family_categories(
			all_node_list, nodes, node_colors, parents_map, children_map, spouses_map,
			ancestor_paths, ancestor_dist, valid_cycles, leaf_items, config.leaf_only, leaf_nodes, blocked,
		)
	else:
		family_results_cache = {}
		all_relevant_items, irrelevant_items, category_config = _prepare_standard_categories(
			g, all_node_list, nodes, valid_cycles, leaf_items, config.leaf_only,
			leaf_nodes, blocked, config.max_indirectness_game,
		)

	return {
		"is_counter": is_counter,
		"is_family": is_family,
		"ignore_edge_colors": ignore_edge_colors,
		"text_shared_source": text_shared_source,
		"text_shared_dest": text_shared_dest,
		"leaf_sources_map": leaf_sources_map,
		"leaf_dests_map": leaf_dests_map,
		"parents_map": parents_map,
		"children_map": children_map,
		"spouses_map": spouses_map,
		"ancestor_paths": ancestor_paths,
		"ancestor_dist": ancestor_dist,
		"family_results_cache": family_results_cache,
		"all_relevant_items": all_relevant_items,
		"irrelevant_items": irrelevant_items,
		"category_config": category_config,
	}