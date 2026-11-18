import random
import sys
from collections import defaultdict
import networkx as nx

from src.family_utils import (
	FAMILY_CONNECTION_TYPES,
	build_family_structures,
	compute_all_ancestors,
	analyze_family_pair,
	detect_gender,
	get_parent_term,
	get_child_term
)
from src.formatters import (
	format_path_string, get_path_net_effect_arrow, get_edge_arrow,
	format_node_name, get_box_prefix, COUNTER_CONNECTION_TYPES
)
from src.graph_utils import find_bounded_cycles
from src.models import GraphContext
from src.progress_storage import get_save_file_path, load_progress, save_progress


class GameCancelledError(Exception):
	pass


def get_canonical_cycle_tuple(cycle_nodes, nodes_dict):
	n = len(cycle_nodes)
	rotations = [cycle_nodes[i:] + cycle_nodes[:i] for i in range(n)]
	return min(rotations, key=lambda rot: [nodes_dict.get(x, str(x)).lower() for x in rot])

# Add near top-level helpers (below GameCancelledError / get_canonical_cycle_tuple)

def _get_pair_key(u_node, v_node, nodes_dict):
	name1 = nodes_dict.get(u_node, str(u_node))
	name2 = nodes_dict.get(v_node, str(v_node))
	return ",".join(sorted([name1, name2]))


def _get_item_key(item, nodes_dict):
	itype, data = item
	if itype == 'leaf_src':
		return f"leaf_src:{nodes_dict.get(data, str(data))}"
	elif itype == 'leaf_dst':
		return f"leaf_dst:{nodes_dict.get(data, str(data))}"
	elif itype == 'cycle':
		canonical_names = [nodes_dict.get(x, str(x)) for x in data]
		return "cycle:" + "->".join(canonical_names) + f"->{canonical_names[0]}"
	else:
		return _get_pair_key(data[0], data[1], nodes_dict)


def build_stats_snapshot(nodes_dict: dict, category_config: list, game_progress: dict) -> dict:
	rows = []
	min_tier = sys.maxsize
	for cat_name, items in category_config:
		if not items:
			continue
		counts = [game_progress.get(_get_item_key(it, nodes_dict), 0) for it in items]
		tier = min(counts)
		total = len(counts)
		answered = total - sum(1 for c in counts if c == tier)
		pct = int(100 * answered / total) if total else 0
		if min_tier > tier:
			min_tier = tier
		rows.append({
			"category": cat_name,
			"answered": answered,
			"total": total,
			"pct": pct,
			"tier": tier,
			"left": total - answered,
		})
	return {
		"rows": rows,
		"current_tier": min_tier if min_tier != sys.maxsize else 0,
	}


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

	# Find direct leaf nodes
	root_nodes = {n for n in g.nodes() if g.in_degree(n) == 0}
	terminal_nodes = {n for n in g.nodes() if g.out_degree(n) == 0}
	leaf_nodes = root_nodes.union(terminal_nodes)

	# Precompute source and destination mappings for leaf connections
	leaf_sources_map = defaultdict(list)
	leaf_dests_map = defaultdict(list)

	for target in g.nodes():
		predecessors = list(g.predecessors(target))
		if not predecessors:
			continue
		if target in terminal_nodes or any(p in root_nodes for p in predecessors):
			leaf_sources_map[target] = predecessors

	for source in g.nodes():
		successors = list(g.successors(source))
		if not successors:
			continue
		if source in root_nodes or any(s in terminal_nodes for s in successors):
			leaf_dests_map[source] = successors

	leaf_source_candidates = [n for n in leaf_sources_map.keys() if str(nodes.get(n, n)).lower() not in block_starting_node]
	leaf_dest_candidates = [n for n in leaf_dests_map.keys() if str(nodes.get(n, n)).lower() not in block_starting_node]

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
	parents_map = children_map = spouses_map = ancestor_paths = ancestor_dist = None
	family_results_cache = {}

	if is_family:
		parents_map, children_map, spouses_map = build_family_structures(g, edge_labels)
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

				res = analyze_family_pair(u, v, nodes, node_colors, parents_map, children_map, spouses_map, ancestor_paths, ancestor_dist)
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
			cycle_items + leaf_items + parent_child_items + grandparent_items +
			sibling_items + uncle_nephew_items + first_cousin_items +
			second_third_cousin_items + in_law_items
		)

		category_config = [
			('Cycle', cycle_items),
			('Leaf', leaf_items),
			('Parent/Child', parent_child_items),
			('Grandparent+', grandparent_items),
			('Sibling', sibling_items),
			('Uncle/Aunt', uncle_nephew_items),
			('1st Cousin', first_cousin_items),
			('2nd/3rd Cous', second_third_cousin_items),
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
			('Leaf', leaf_items),
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


def compute_relationship_stats(ctx: GraphContext, prepared_data: dict = None) -> dict:
	if prepared_data is None:
		prepared_data = prepare_relationship_game_data(ctx)
	save_path = get_save_file_path(ctx.config.file_name)
	progress_data = load_progress(save_path)
	game_progress = progress_data.get("game2_relationship", {})
	return build_stats_snapshot(ctx.nodes, prepared_data["category_config"], game_progress)


def run_relationship_guessing_game(
	ctx: GraphContext,
	input_fn=None,
	exit_on_finish: bool = True,
	on_stats_update=None,
	prepared_data: dict = None,
):
	_input = input_fn if input_fn is not None else input
	print("\nGuess if the nodes connect Directly, Indirectly, Share a Source/Destination, Leaf (Source/Dest), Form a Cycle, or are Irrelevant.")

	g = ctx.graph
	nodes = ctx.nodes
	edge_values = ctx.edge_values
	edge_labels = ctx.edge_labels
	node_colors = ctx.node_colors
	config = ctx.config

	block_starting_node = config.block_starting_node
	max_indirectness_game = config.max_indirectness_game
	chance_irrelevant = config.chance_irrelevant
	max_cycle_length_game = config.max_cycle_length_game

	if prepared_data is None:
		prepared_data = prepare_relationship_game_data(ctx)

	is_counter = prepared_data["is_counter"]
	is_family = prepared_data["is_family"]
	ignore_edge_colors = prepared_data["ignore_edge_colors"]
	text_shared_source = prepared_data["text_shared_source"]
	text_shared_dest = prepared_data["text_shared_dest"]
	leaf_sources_map = prepared_data["leaf_sources_map"]
	leaf_dests_map = prepared_data["leaf_dests_map"]
	parents_map = prepared_data["parents_map"]
	children_map = prepared_data["children_map"]
	spouses_map = prepared_data["spouses_map"]
	ancestor_paths = prepared_data["ancestor_paths"]
	ancestor_dist = prepared_data["ancestor_dist"]
	family_results_cache = prepared_data["family_results_cache"]
	all_relevant_items = prepared_data["all_relevant_items"]
	irrelevant_items = prepared_data["irrelevant_items"]
	_category_config = prepared_data["category_config"]

	if not all_relevant_items and not irrelevant_items:
		print("No valid questions found matching your graph and filter settings.")
		if on_stats_update is not None:
			on_stats_update({"rows": [], "current_tier": 0})
		return

	# Load progress
	save_path = get_save_file_path(config.file_name)
	progress_data = load_progress(save_path)
	game2_key = "game2_relationship"
	if game2_key not in progress_data:
		progress_data[game2_key] = {}

	def get_item_count(item):
		return progress_data[game2_key].get(_get_item_key(item, nodes), 0)

	def get_global_tiers():
		rel_min = min((get_item_count(it) for it in all_relevant_items), default=0)
		irr_min = min((get_item_count(it) for it in irrelevant_items), default=0)
		return rel_min, irr_min

	def print_relationship_stats(stats: dict):
		print("\n--- Category Progress ---")
		for r in stats["rows"]:
			print(
				f"  {r['category']:12}: {r['answered']:3} / {r['total']:3} "
				f"({r['pct']:2}% + {r['tier']}) (Left: {r['left']:3})"
			)
		print(f"  Current tier: {stats['current_tier']}\n")

	def emit_stats(force_cli_print: bool = False):
		nonlocal current_tiers
		stats = build_stats_snapshot(nodes, _category_config, progress_data[game2_key])
		if on_stats_update is not None:
			on_stats_update(stats)
		else:
			new_tiers = get_global_tiers()
			if force_cli_print or new_tiers != current_tiers:
				current_tiers = new_tiers
				print_relationship_stats(stats)

	current_tiers = get_global_tiers()
	emit_stats(force_cli_print=True)
	question_num = 0

	while True:
		question_num += 1

		# Determine minimum count among all relevant items
		min_rel_count = min((get_item_count(it) for it in all_relevant_items), default=0)

		# Filter available items per category matching lowest counter
		eligible_by_cat = {}
		for cat_name, items in _category_config:
			if not items:
				continue
			if cat_name == 'Irrelevant':
				min_irr = min(get_item_count(it) for it in items)
				avail = [it for it in items if get_item_count(it) == min_irr]
				if avail:
					eligible_by_cat['irrelevant'] = avail
			else:
				avail = [it for it in items if get_item_count(it) == min_rel_count]
				if avail:
					eligible_by_cat[cat_name] = avail

		if not eligible_by_cat:
			print("No questions available.")
			break

		# Calculate weights dynamically to evenly distribute questions across categories
		active_cats = list(eligible_by_cat.keys())
		relevant_cats = [c for c in active_cats if c != 'irrelevant']
		total_rel_count = sum(len(eligible_by_cat[c]) for c in relevant_cats)

		active_weights = []
		for c in active_cats:
			if c == 'irrelevant':
				if relevant_cats and total_rel_count > 0:
					active_weights.append(chance_irrelevant)
				else:
					active_weights.append(1.0)
			else:
				if 'irrelevant' in active_cats:
					chance_relevant = max(0.0, 1.0 - chance_irrelevant)
					active_weights.append(chance_relevant * (len(eligible_by_cat[c]) / total_rel_count))
				else:
					active_weights.append(len(eligible_by_cat[c]) / total_rel_count)

		chosen_cat = random.choices(active_cats, weights=active_weights, k=1)[0]
		chosen_item = random.choice(eligible_by_cat[chosen_cat])

		itype, data = chosen_item

		# Handle Cycle Question
		if itype == 'cycle':
			rotated_cyc = data
			valid_m = [
				idx for idx in range(1, len(rotated_cyc))
				if str(nodes.get(rotated_cyc[idx], rotated_cyc[idx])).lower() not in block_starting_node
			]
			m = random.choice(valid_m) if valid_m else random.randint(1, len(rotated_cyc) - 1)

			full_path = rotated_cyc + [rotated_cyc[0]]
			chosen_middle = full_path[m]
			pred_node = full_path[m - 1]
			succ_node = full_path[m + 1]

			edge_val_in = edge_values.get((pred_node, chosen_middle), 1)
			edge_val_out = edge_values.get((chosen_middle, succ_node), 1)

			cum_val = 1
			q_parts = [format_node_name(full_path[0], nodes, 0, is_counter)]
			for k in range(len(full_path) - 1):
				u = full_path[k]
				v = full_path[k + 1]
				val = edge_values.get((u, v), 1)
				cum_val *= val
				arrow = get_edge_arrow(cum_val, ignore_edge_colors=ignore_edge_colors)
				if (k + 1) == m:
					node_text = f"{get_box_prefix(k + 1)} [?]" if is_counter else "[?]"
				else:
					node_text = format_node_name(v, nodes, k + 1, is_counter)
				q_parts.append(f"{arrow} {node_text}")

			question_str = " ".join(q_parts)
			print(f"Question {question_num}: {question_str}", end=' ')

			user_input = _input().strip()
			if user_input == '0':
				print("Stopping the game.")
				break

			# Find all candidate nodes in graph that complete the same cycle question
			known_nodes = set(rotated_cyc) - {chosen_middle}
			candidate_paths = []
			for cand in g.nodes():
				if cand in known_nodes:
					continue
				if str(nodes.get(cand, cand)).lower() in block_starting_node:
					continue
				if g.has_edge(pred_node, cand) and g.has_edge(cand, succ_node):
					val_in = edge_values.get((pred_node, cand), 1)
					val_out = edge_values.get((cand, succ_node), 1)
					if val_in == edge_val_in and val_out == edge_val_out:
						cand_path = full_path[:m] + [cand] + full_path[m + 1:]
						candidate_paths.append(cand_path)

			candidate_paths.sort(key=lambda p: [str(nodes.get(n, n)).lower() for n in p])

			if len(candidate_paths) <= 1:
				formatted_cycle = format_path_string(full_path, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
				if is_counter or ignore_edge_colors:
					print(f"{formatted_cycle}")
				else:
					cycle_corr = 1
					for k in range(len(full_path) - 1):
						cycle_corr *= edge_values.get((full_path[k], full_path[k + 1]), 1)
					polarity_icon = "[💥]" if cycle_corr > 0 else "[⚖️]"
					loop_type = "Reinforcing" if cycle_corr > 0 else "Balancing"
					print(f"{formatted_cycle} ({polarity_icon} {loop_type})")
			else:
				print("Answer(s):")
				for cand_p in candidate_paths:
					formatted_cycle = format_path_string(cand_p, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
					if is_counter or ignore_edge_colors:
						print(f"  • {formatted_cycle}")
					else:
						cycle_corr = 1
						for k in range(len(cand_p) - 1):
							cycle_corr *= edge_values.get((cand_p[k], cand_p[k + 1]), 1)
						polarity_icon = "[💥]" if cycle_corr > 0 else "[⚖️]"
						loop_type = "Reinforcing" if cycle_corr > 0 else "Balancing"
						print(f"  • {formatted_cycle} ({polarity_icon} {loop_type})")

			print()
			cycle_key = _get_item_key(chosen_item, nodes)
			current_counter = progress_data[game2_key].get(cycle_key, 0)
			progress_data[game2_key][cycle_key] = current_counter + 1
			save_progress(save_path, progress_data)
			emit_stats()
			continue

		# Handle Leaf Source Question ([?] → Target)
		elif itype == 'leaf_src':
			target_node = data
			target_name = nodes.get(target_node, str(target_node))
			leaf_key = f"leaf_src:{target_name}"
			current_counter = progress_data[game2_key].get(leaf_key, 0)

			if is_counter:
				print(f"Question {question_num}: 🟦 [?] → 🟥 {target_name}", end=' ')
			elif is_family:
				t_gender = detect_gender(node_colors.get(target_node, ''))
				t_child_term = get_child_term(t_gender)
				print(f"Question {question_num}: [?] (Parent) → {target_name} ({t_child_term})", end=' ')
			else:
				print(f"Question {question_num}: [?] → {target_name}", end=' ')

			user_input = _input().strip()
			if user_input == '0':
				print("Stopping the game.")
				break

			found_leaves = sorted(leaf_sources_map[target_node], key=lambda x: str(nodes.get(x, x)).lower())
			if len(found_leaves) == 1:
				p_nid = found_leaves[0]
				p_name = nodes.get(p_nid, str(p_nid))
				if is_family:
					p_term = get_parent_term(detect_gender(node_colors.get(p_nid, '')))
					print(f"{p_name} ({p_term}) → {target_name}")
				else:
					print(f"{format_path_string([p_nid, target_node], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)}")
			else:
				print("Answer(s):")
				for s in found_leaves:
					s_name = nodes.get(s, str(s))
					if is_family:
						p_term = get_parent_term(detect_gender(node_colors.get(s, '')))
						print(f"  • {s_name} ({p_term}) → {target_name}")
					else:
						print(f"  • {format_path_string([s, target_node], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)}")

			print()
			progress_data[game2_key][leaf_key] = current_counter + 1
			save_progress(save_path, progress_data)
			emit_stats()
			continue

		# Handle Leaf Destination Question (Source → [?])
		elif itype == 'leaf_dst':
			source_node = data
			source_name = nodes.get(source_node, str(source_node))
			leaf_key = f"leaf_dst:{source_name}"
			current_counter = progress_data[game2_key].get(leaf_key, 0)

			if is_counter:
				print(f"Question {question_num}: 🟦 {source_name} → 🟥 [?]", end=' ')
			elif is_family:
				s_gender = detect_gender(node_colors.get(source_node, ''))
				s_parent_term = get_parent_term(s_gender)
				print(f"Question {question_num}: {source_name} ({s_parent_term}) → [?] (Child)", end=' ')
			else:
				print(f"Question {question_num}: {source_name} → [?]", end=' ')

			user_input = _input().strip()
			if user_input == '0':
				print("Stopping the game.")
				break

			found_leaves = sorted(leaf_dests_map[source_node], key=lambda x: str(nodes.get(x, x)).lower())
			if len(found_leaves) == 1:
				c_nid = found_leaves[0]
				c_name = nodes.get(c_nid, str(c_nid))
				if is_family:
					c_term = get_child_term(detect_gender(node_colors.get(c_nid, '')))
					print(f"{source_name} → {c_name} ({c_term})")
				else:
					print(f"{format_path_string([source_node, c_nid], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)}")
			else:
				for d in found_leaves:
					d_name = nodes.get(d, str(d))
					if is_family:
						c_term = get_child_term(detect_gender(node_colors.get(d, '')))
						print(f"  • {source_name} → {d_name} ({c_term})")
					else:
						print(f"  • {format_path_string([source_node, d], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)}")

			print()
			progress_data[game2_key][leaf_key] = current_counter + 1
			save_progress(save_path, progress_data)
			emit_stats()
			continue

		# Handle Pair Question
		else:
			u, v = data
			if random.random() > 0.5:
				u, v = v, u

			u_name = nodes.get(u, str(u))
			v_name = nodes.get(v, str(v))

			print(f"Question {question_num}: {u_name} [?] {v_name}", end=' ')

			user_input = _input().strip()
			if user_input == '0':
				print("Stopping the game.")
				break

			# --- Family Relationship Mode ---
			if is_family:
				fam_res = family_results_cache.get((u, v))
				if not fam_res:
					fam_res = analyze_family_pair(u, v, nodes, node_colors, parents_map, children_map, spouses_map, ancestor_paths, ancestor_dist)

				if not fam_res.is_relevant:
					print("IRRELEVANT (No blood or marriage relationship found)")
				else:
					print(f"{fam_res.primary_title}")
					for d in fam_res.details:
						print(f"  • {d}")
					if fam_res.lineages:
						print("  Lineage:", end='')
						for l in fam_res.lineages:
							print(f"    {l}")

			# --- Correlation / Counter Mode ---
			else:
				cutoff_distance = max_indirectness_game + 1
				paths_u_v = list(nx.all_simple_paths(g, source=u, target=v, cutoff=cutoff_distance))
				paths_v_u = list(nx.all_simple_paths(g, source=v, target=u, cutoff=cutoff_distance))

				paths_u_v.sort(key=len)
				paths_v_u.sort(key=len)

				direct_u_v = [p for p in paths_u_v if len(p) == 2]
				direct_v_u = [p for p in paths_v_u if len(p) == 2]

				indirect_u_v = [p for p in paths_u_v if len(p) > 2]
				indirect_v_u = [p for p in paths_v_u if len(p) > 2]

				is_direct = bool(direct_u_v or direct_v_u)
				is_indirect = not is_direct and bool(indirect_u_v or indirect_v_u)

				# Find shared sources and shared destinations
				shared_srcs = [s for s in set(g.predecessors(u)).intersection(g.predecessors(v)) if s != u and s != v]
				shared_dsts = [d for d in set(g.successors(u)).intersection(g.successors(v)) if d != u and d != v]

				shared_srcs.sort(key=lambda s: str(nodes.get(s, s)).lower())
				shared_dsts.sort(key=lambda d: str(nodes.get(d, d)).lower())

				# Collect all distinct connection options
				connection_lines = []

				if is_counter:
					for s in shared_srcs:
						s_name = nodes.get(s, s)
						connection_lines.append(f"{text_shared_source}: 🟦 {s_name} → 🟥 {u_name} & 🟥 {v_name}")

					for d in shared_dsts:
						d_name = nodes.get(d, d)
						connection_lines.append(f"{text_shared_dest}: 🟦 {u_name} & 🟦 {v_name} → 🟥 {d_name}")
				else:
					for s in shared_srcs:
						val_u = edge_values.get((s, u), 1)
						val_v = edge_values.get((s, v), 1)
						arr_u = get_edge_arrow(val_u)
						arr_v = get_edge_arrow(val_v)
						if arr_u == arr_v:
							connection_lines.append(f"{text_shared_source}: {nodes.get(s, s)} {arr_u}")
						else:
							connection_lines.append(f"{text_shared_source}: {nodes.get(s, s)} {arr_u} {nodes.get(u, u)} + {arr_v} {nodes.get(v, v)}")

					for d in shared_dsts:
						val_u = edge_values.get((u, d), 1)
						val_v = edge_values.get((v, d), 1)
						arr_u = get_edge_arrow(val_u)
						arr_v = get_edge_arrow(val_v)
						if arr_u == arr_v:
							connection_lines.append(f"{text_shared_dest}: {arr_u} {nodes.get(d, d)}")
						else:
							connection_lines.append(f"{text_shared_dest}: {nodes.get(u, u)} ({arr_u}) + {nodes.get(v, v)} ({arr_v}) → {nodes.get(d, d)}")

				if is_direct:
					if direct_u_v and direct_v_u:
						p1_str = format_path_string([u, v], nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
						p2_str = format_path_string([v, u], nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
						lbl1 = edge_labels.get((u, v), '') if edge_labels else ''
						lbl2 = edge_labels.get((v, u), '') if edge_labels else ''
						lbl_lines = []
						if lbl1:
							lbl_lines.append(f"      ({nodes.get(u, u)} → {nodes.get(v, v)}: {lbl1})")
						if lbl2:
							lbl_lines.append(f"      ({nodes.get(v, v)} → {nodes.get(u, u)}: {lbl2})")
						lbl_suffix = ("\n" + "\n".join(lbl_lines)) if lbl_lines else ""
						connection_lines.append(f"Direct (⟳): {p1_str} ↔ {p2_str}{lbl_suffix}")
					elif direct_u_v:
						p_str = format_path_string([u, v], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
						connection_lines.append(f"Direct: {p_str}")
						for p in paths_v_u:
							is_p_direct = len(p) == 2
							prefix = "Direct ↩" if is_p_direct else f"Indirect ↩ ({len(p) - 2})"
							formatted_p = format_path_string(p, nodes, edge_values, edge_labels if is_p_direct else None, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
							suffix = "" if (is_counter or ignore_edge_colors or is_p_direct) else f" ({get_path_net_effect_arrow(p, edge_values)})"
							connection_lines.append(f"{prefix}: {formatted_p}{suffix}")
					elif direct_v_u:
						p_str = format_path_string([v, u], nodes, edge_values, edge_labels, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
						connection_lines.append(f"Direct: {p_str}")
						for p in paths_u_v:
							is_p_direct = len(p) == 2
							prefix = "Direct ↩" if is_p_direct else f"Indirect ↩ ({len(p) - 2})"
							formatted_p = format_path_string(p, nodes, edge_values, edge_labels if is_p_direct else None, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
							suffix = "" if (is_counter or ignore_edge_colors or is_p_direct) else f" ({get_path_net_effect_arrow(p, edge_values)})"
							connection_lines.append(f"{prefix}: {formatted_p}{suffix}")

					for p in indirect_u_v:
						formatted_p = format_path_string(p, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
						suffix = "" if (is_counter or ignore_edge_colors) else f" ({get_path_net_effect_arrow(p, edge_values)})"
						connection_lines.append(f"Indirect ({len(p) - 2}): {formatted_p}{suffix}")
				elif is_indirect:
					for p in indirect_u_v:
						formatted_p = format_path_string(p, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
						suffix = "" if (is_counter or ignore_edge_colors) else f" ({get_path_net_effect_arrow(p, edge_values)})"
						connection_lines.append(f"Indirect ({len(p) - 2}): {formatted_p}{suffix}")
					for p in indirect_v_u:
						prefix = "Indirect ↩" if indirect_u_v else "Indirect"
						formatted_p = format_path_string(p, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
						suffix = "" if (is_counter or ignore_edge_colors) else f" ({get_path_net_effect_arrow(p, edge_values)})"
						connection_lines.append(f"{prefix} ({len(p) - 2}): {formatted_p}{suffix}")

				# Find feedback loops / cycles
				if max_cycle_length_game >= 2:
					paths_fwd = list(nx.all_simple_paths(g, source=u, target=v, cutoff=max_cycle_length_game - 1))
					paths_bwd = list(nx.all_simple_paths(g, source=v, target=u, cutoff=max_cycle_length_game - 1))
					seen_pair_cycles = set()
					pair_cycles = []

					for p1 in paths_fwd:
						mid1 = set(p1[1:-1])
						for p2 in paths_bwd:
							total_nodes = (len(p1) - 1) + (len(p2) - 1)
							if total_nodes <= max_cycle_length_game and mid1.isdisjoint(p2[1:-1]):
								full_cycle = p1[:-1] + p2
								cycle_tuple = tuple(full_cycle[:-1])
								min_i = cycle_tuple.index(min(cycle_tuple))
								canonical = cycle_tuple[min_i:] + cycle_tuple[:min_i]
								if canonical not in seen_pair_cycles:
									seen_pair_cycles.add(canonical)
									pair_cycles.append(full_cycle)

					pair_cycles.sort(key=lambda c: (len(c), [str(nodes.get(n, n)) for n in c]))

					for cyc in pair_cycles:
						formatted_cyc = format_path_string(cyc, nodes, edge_values, ignore_edge_colors=ignore_edge_colors, is_counter=is_counter)
						cyc_len = len(cyc) - 1
						if is_counter or ignore_edge_colors:
							connection_lines.append(f"Cycle ({cyc_len}): {formatted_cyc}")
						else:
							cycle_corr = 1
							for k in range(len(cyc) - 1):
								cycle_corr *= edge_values.get((cyc[k], cyc[k + 1]), 1)
							polarity_icon = "[💥]" if cycle_corr > 0 else "[⚖️]"
							connection_lines.append(f"Cycle ({cyc_len}) {polarity_icon}: {formatted_cyc}")

				if not connection_lines:
					print("IRRELEVANT")
				elif len(connection_lines) == 1:
					print(f"{connection_lines[0]}")
				else:
					for line in connection_lines:
						print(f"  • {line}")

			print()
			pair_key_to_save = _get_item_key(chosen_item, nodes)
			current_counter = progress_data[game2_key].get(pair_key_to_save, 0)
			progress_data[game2_key][pair_key_to_save] = current_counter + 1
			save_progress(save_path, progress_data)
			emit_stats()

	print("Quiz finished.")
	if exit_on_finish:
		sys.exit(0)