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


def prepare_relationship_game_data(ctx: GraphContext) -> dict:
	g = ctx.graph
	nodes = ctx.nodes
	edge_labels = ctx.edge_labels
	node_colors = ctx.node_colors
	config = ctx.config

	block_starting_node = config.block_starting_node
	max_indirectness_game = config.max_indirectness_game
	leaf_only = config.leaf_only
	max_cycle_length_game = config.max_cycle_length_game

	# Resolve connection mode
	conn_type = getattr(config, 'connection_type', 'correlation').lower()
	is_counter = conn_type in COUNTER_CONNECTION_TYPES
	is_family = conn_type in FAMILY_CONNECTION_TYPES
	ignore_edge_colors = config.ignore_edge_colors or is_counter or is_family

	if is_family:
		text_shared_source = "Parents"
		text_shared_dest = "Children"
	elif is_counter:
		text_shared_source = "Common threat"
		text_shared_dest = "Common counter"
	else:
		text_shared_source = "Common cause (Confounder)"
		text_shared_dest = "Common effect (Collider)"

	# Build family structures early so spouse edges don't leak into Single (leaf) questions
	parents_map = children_map = spouses_map = ancestor_paths = ancestor_dist = None
	if is_family:
		parents_map, children_map, spouses_map = build_family_structures(g, edge_labels)
		root_nodes = {n for n in g.nodes() if not parents_map.get(n)}
		terminal_nodes = {n for n in g.nodes() if not children_map.get(n)}
	else:
		root_nodes = {n for n in g.nodes() if g.in_degree(n) == 0}
		terminal_nodes = {n for n in g.nodes() if g.out_degree(n) == 0}
	leaf_nodes = root_nodes.union(terminal_nodes)

	# Precompute source and destination mappings for leaf connections
	leaf_sources_map = defaultdict(list)
	leaf_dests_map = defaultdict(list)

	for target in g.nodes():
		predecessors = list(parents_map.get(target, [])) if is_family else list(g.predecessors(target))
		if not predecessors:
			continue
		if not leaf_only or target in terminal_nodes or any(p in root_nodes for p in predecessors):
			leaf_sources_map[target] = predecessors

	for source in g.nodes():
		successors = list(children_map.get(source, [])) if is_family else list(g.successors(source))
		if not successors:
			continue
		if not leaf_only or source in root_nodes or any(s in terminal_nodes for s in successors):
			leaf_dests_map[source] = successors

	leaf_source_candidates = [
		n for n in leaf_sources_map.keys()
		if str(nodes.get(n, n)).lower() not in block_starting_node
	]
	leaf_dest_candidates = [
		n for n in leaf_dests_map.keys()
		if str(nodes.get(n, n)).lower() not in block_starting_node
	]

	# Find cycles for cycle questions
	cycle_candidates = find_bounded_cycles(g, max_cycle_length_game) if max_cycle_length_game >= 2 else []
	valid_cycles = []
	seen_cycles = set()
	for cyc in cycle_candidates:
		if len(cyc) < 2 or len(cyc) > max_cycle_length_game:
			continue
		if all(str(nodes.get(n, n)).lower() in block_starting_node for n in cyc):
			continue
		canonical = tuple(get_canonical_cycle_tuple(cyc, nodes))
		if canonical not in seen_cycles:
			seen_cycles.add(canonical)
			valid_cycles.append(list(canonical))

	# Categorize all unordered node pairs
	all_node_list = list(g.nodes())
	family_results_cache = {}

	if is_family:
		ancestor_paths, ancestor_dist = compute_all_ancestors(all_node_list, parents_map)

		parent_child_pairs = []
		grandparent_pairs = []
		sibling_pairs = []
		uncle_nephew_pairs = []
		first_cousin_pairs = []
		second_third_cousin_pairs = []
		in_law_pairs = []
		irrelevant_pairs = []

		for i in range(len(all_node_list)):
			for j in range(i + 1, len(all_node_list)):
				u = all_node_list[i]
				v = all_node_list[j]

				if leaf_only and (u not in leaf_nodes and v not in leaf_nodes):
					continue

				u_name = str(nodes.get(u, u)).lower()
				v_name = str(nodes.get(v, v)).lower()
				if u_name in block_starting_node and v_name in block_starting_node:
					continue

				res = analyze_family_pair(
					u, v, nodes, node_colors, parents_map, children_map,
					spouses_map, ancestor_paths, ancestor_dist,
				)
				family_results_cache[(u, v)] = res
				family_results_cache[(v, u)] = res

				cat = res.category
				if cat == 'parent_child':
					parent_child_pairs.append((u, v))
				elif cat == 'grandparent':
					grandparent_pairs.append((u, v))
				elif cat == 'sibling':
					sibling_pairs.append((u, v))
				elif cat == 'uncle_nephew':
					uncle_nephew_pairs.append((u, v))
				elif cat == 'first_cousin':
					first_cousin_pairs.append((u, v))
				elif cat == 'second_third_cousin':
					second_third_cousin_pairs.append((u, v))
				elif cat == 'in_law':
					in_law_pairs.append((u, v))
				else:
					irrelevant_pairs.append((u, v))

		shared_children_items = []
		together_items = []

		for x in all_node_list:
			x_name = str(nodes.get(x, x)).lower()
			if x_name in block_starting_node:
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

			for sorted_c in sorted(
				children_groups.keys(),
				key=lambda cs: [str(nodes.get(c, c)).lower() for c in cs],
			):
				shared_children_items.append(('shared_children', (x, sorted_c)))

			childless_partners = [
				y for y in spouses_map.get(x, set())
				if y != x and y not in shared_by_partner
				and (not leaf_only or (x in leaf_nodes or y in leaf_nodes))
			]
			if childless_partners:
				together_items.append(('together', x))

		partner_items = shared_children_items + together_items

		cycle_items = []
		for cyc in valid_cycles:
			for rot_idx in range(len(cyc)):
				rotated_cyc = cyc[rot_idx:] + cyc[:rot_idx]
				cycle_items.append(('cycle', rotated_cyc))
		leaf_items = [('leaf_src', n) for n in leaf_source_candidates] + [('leaf_dst', n) for n in leaf_dest_candidates]
		parent_child_items = [('parent_child', p) for p in parent_child_pairs]
		grandparent_items = [('grandparent', p) for p in grandparent_pairs]
		sibling_items = [('sibling', p) for p in sibling_pairs]
		uncle_nephew_items = [('uncle_nephew', p) for p in uncle_nephew_pairs]
		first_cousin_items = [('first_cousin', p) for p in first_cousin_pairs]
		second_third_cousin_items = [('second_third_cousin', p) for p in second_third_cousin_pairs]
		in_law_items = [('in_law', p) for p in in_law_pairs]
		irrelevant_items = [('irrelevant', p) for p in irrelevant_pairs]

		all_relevant_items = (
			cycle_items + leaf_items + partner_items + parent_child_items + grandparent_items +
			sibling_items + uncle_nephew_items + first_cousin_items +
			second_third_cousin_items + in_law_items
		)

		category_config = [
			('Cycle', cycle_items),
			('Single', leaf_items),
			('Partner', partner_items),
			('Parent/Child', parent_child_items),
			('Grandparent+', grandparent_items),
			('Sibling', sibling_items),
			('Uncle/Aunt', uncle_nephew_items),
			('1st Cousin', first_cousin_items),
			('2nd/3rd Cousin', second_third_cousin_items),
			('In-Law', in_law_items),
			('Irrelevant', irrelevant_items),
		]
	else:
		# Standard Correlation / Counter Mode
		direct_pairs = []
		indirect_pairs = []
		same_pairs = []
		irrelevant_pairs = []
		max_cutoff = max_indirectness_game + 1

		for i in range(len(all_node_list)):
			for j in range(i + 1, len(all_node_list)):
				u = all_node_list[i]
				v = all_node_list[j]

				if leaf_only and (u not in leaf_nodes and v not in leaf_nodes):
					continue

				u_name = str(nodes.get(u, u)).lower()
				v_name = str(nodes.get(v, v)).lower()
				if u_name in block_starting_node and v_name in block_starting_node:
					continue

				# Shared direct sources & shared direct destinations
				shared_srcs = [s for s in set(g.predecessors(u)).intersection(g.predecessors(v)) if s != u and s != v]
				shared_dsts = [d for d in set(g.successors(u)).intersection(g.successors(v)) if d != u and d != v]
				has_shared = bool(shared_srcs or shared_dsts)

				# Check shortest path in both directions
				has_u_to_v = nx.has_path(g, u, v)
				has_v_to_u = nx.has_path(g, v, u)

				len_u_v = nx.shortest_path_length(g, u, v) if has_u_to_v else float('inf')
				len_v_u = nx.shortest_path_length(g, v, u) if has_v_to_u else float('inf')

				if len_u_v == 1 or len_v_u == 1:
					direct_pairs.append((u, v))
				elif (len_u_v <= max_cutoff) or (len_v_u <= max_cutoff):
					indirect_pairs.append((u, v))
				elif has_shared:
					same_pairs.append((u, v))
				elif not has_u_to_v and not has_v_to_u:
					irrelevant_pairs.append((u, v))

		cycle_items = [('cycle', cyc) for cyc in valid_cycles]
		leaf_items = [('leaf_src', n) for n in leaf_source_candidates] + [('leaf_dst', n) for n in leaf_dest_candidates]
		direct_items = [('direct', p) for p in direct_pairs]
		indirect_items = [('indirect', p) for p in indirect_pairs]
		same_items = [('same', p) for p in same_pairs]
		irrelevant_items = [('irrelevant', p) for p in irrelevant_pairs]

		all_relevant_items = cycle_items + leaf_items + direct_items + indirect_items + same_items

		category_config = [
			('Cycle', cycle_items),
			('Single', leaf_items),
			('Direct', direct_items),
			('Indirect', indirect_items),
			('Same/Shared', same_items),
			('Irrelevant', irrelevant_items),
		]

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