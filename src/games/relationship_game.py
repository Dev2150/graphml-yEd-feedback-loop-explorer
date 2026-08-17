import random
import sys
from collections import defaultdict
import networkx as nx

from src.formatters import format_path_string, get_path_net_effect_arrow
from src.models import GraphContext
from src.progress_storage import get_save_file_path, load_progress, save_progress


def run_relationship_guessing_game(ctx: GraphContext):
	print("\n--- Relationship Guessing Game ---")
	print("Guess if the nodes connect Directly, Indirectly, Share a Source/Destination, Leaf (Source/Dest), or are Irrelevant. Enter 0 to stop.")
	print("[Direct / Indirect / Shared sources/destinations / Leaf Source/Dest / Irrelevant] (Press Enter to reveal answer, or 0 to quit).\n")

	g = ctx.graph
	nodes = ctx.nodes
	edge_values = ctx.edge_values
	config = ctx.config

	block_starting_node = config.block_starting_node
	max_indirectness = config.max_indirectness
	max_indirectness_game = config.max_indirectness_game
	leaf_only = config.leaf_only
	chance_irrelevant = config.chance_irrelevant
	max_cycle_length_game = config.max_cycle_length_game

	# Find direct leaf nodes
	root_nodes = {n for n in g.nodes() if g.in_degree(n) == 0}
	terminal_nodes = {n for n in g.nodes() if g.out_degree(n) == 0}
	leaf_nodes = root_nodes.union(terminal_nodes)

	# Precompute direct source-leaf and direct destination-leaf mappings
	leaf_sources_map = defaultdict(list)
	leaf_dests_map = defaultdict(list)

	for target in g.nodes():
		for pred in g.predecessors(target):
			if pred in root_nodes:
				leaf_sources_map[target].append(pred)

	for source in g.nodes():
		for succ in g.successors(source):
			if succ in terminal_nodes:
				leaf_dests_map[source].append(succ)

	leaf_source_candidates = [n for n in leaf_sources_map.keys() if str(nodes.get(n, n)).lower() not in block_starting_node]
	leaf_dest_candidates = [n for n in leaf_dests_map.keys() if str(nodes.get(n, n)).lower() not in block_starting_node]

	# Categorize all unordered node pairs
	all_node_list = list(g.nodes())
	direct_pairs = []
	indirect_pairs = []
	same_pairs = []
	irrelevant_pairs = []

	max_cutoff = max_indirectness + 1

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

	# Define question item pools
	leaf_items = [('leaf_src', n) for n in leaf_source_candidates] + [('leaf_dst', n) for n in leaf_dest_candidates]
	direct_items = [('direct', p) for p in direct_pairs]
	indirect_items = [('indirect', p) for p in indirect_pairs]
	same_items = [('same', p) for p in same_pairs]
	irrelevant_items = [('irrelevant', p) for p in irrelevant_pairs]

	all_relevant_items = leaf_items + direct_items + indirect_items + same_items

	if not all_relevant_items and not irrelevant_items:
		print("No valid questions found matching your graph and filter settings.")
		return

	# Load progress
	save_path = get_save_file_path(config.file_name)
	progress_data = load_progress(save_path)
	game2_key = "game2_relationship"
	if game2_key not in progress_data:
		progress_data[game2_key] = {}

	def get_pair_key(u_node, v_node):
		name1 = nodes.get(u_node, u_node)
		name2 = nodes.get(v_node, v_node)
		return ",".join(sorted([name1, name2]))

	def get_item_key(item):
		itype, data = item
		if itype == 'leaf_src':
			return f"leaf_src:{nodes.get(data, data)}"
		elif itype == 'leaf_dst':
			return f"leaf_dst:{nodes.get(data, data)}"
		else:
			return get_pair_key(data[0], data[1])

	def get_item_count(item):
		return progress_data[game2_key].get(get_item_key(item), 0)

	_category_config = [
		('Leaf', leaf_items),
		('Direct', direct_items),
		('Indirect', indirect_items),
		('Same/Shared', same_items),
		('Irrelevant', irrelevant_items),
	]

	def get_category_stats(items):
		if not items:
			return None
		counts = [get_item_count(it) for it in items]
		tier = min(counts)
		total = len(counts)
		questions_answered = total - sum(1 for c in counts if c == tier)
		pct = int(100 * questions_answered / total) if total else 0
		return tier, questions_answered, total, pct

	def get_global_tiers():
		rel_min = min((get_item_count(it) for it in all_relevant_items), default=0)
		irr_min = min((get_item_count(it) for it in irrelevant_items), default=0)
		return rel_min, irr_min

	def print_relationship_stats():
		print("\n--- Category Progress ---")
		min_tier = sys.maxsize
		for cat_name, items in _category_config:
			if not items:
				continue
			tier, at_min, total, pct = get_category_stats(items)
			if min_tier > tier:
				min_tier = tier
			print(f"  {cat_name}: {at_min}/{total} ({pct}%)")
		print(f"  Current tier: {min_tier}\n")

	print_relationship_stats()
	current_tiers = get_global_tiers()
	question_num = 0
	while True:
		question_num += 1

		# Determine minimum count among all relevant items
		min_rel_count = min((get_item_count(it) for it in all_relevant_items), default=0)

		# Filter available items per category matching lowest counter
		eligible_by_cat = {}

		if leaf_items:
			leaf_avail = [it for it in leaf_items if get_item_count(it) == min_rel_count]
			if leaf_avail:
				eligible_by_cat['leaf'] = leaf_avail

		if direct_items:
			direct_avail = [it for it in direct_items if get_item_count(it) == min_rel_count]
			if direct_avail:
				eligible_by_cat['direct'] = direct_avail

		if indirect_items:
			indirect_avail = [it for it in indirect_items if get_item_count(it) == min_rel_count]
			if indirect_avail:
				eligible_by_cat['indirect'] = indirect_avail

		if same_items:
			same_avail = [it for it in same_items if get_item_count(it) == min_rel_count]
			if same_avail:
				eligible_by_cat['same'] = same_avail

		# Irrelevant items are isolated from min_rel_count so they don't block progression
		if irrelevant_items:
			min_irrel_count = min(get_item_count(it) for it in irrelevant_items)
			irrel_avail = [it for it in irrelevant_items if get_item_count(it) == min_irrel_count]
			if irrel_avail:
				eligible_by_cat['irrelevant'] = irrel_avail

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

		print(f"DEBUG: {[x for pair in sorted(zip(active_cats, active_weights), key=lambda p: -p[1]) if pair[0] != 'irrelevant' for x in (pair[0], f'{100 * pair[1]:.2f}')]}")

		chosen_cat = random.choices(active_cats, weights=active_weights, k=1)[0]
		chosen_item = random.choice(eligible_by_cat[chosen_cat])

		itype, data = chosen_item

		# Handle Leaf Source Question
		if itype == 'leaf_src':
			target_node = data
			target_name = nodes.get(target_node, target_node)
			leaf_key = f"leaf_src:{target_name}"
			current_counter = progress_data[game2_key].get(leaf_key, 0)

			print(f"Question {question_num}: [?] → {target_name}", end=' ')
			user_input = input().strip()
			if user_input == '0':
				print("Stopping the game.")
				break

			found_leaves = sorted(leaf_sources_map[target_node], key=lambda x: str(nodes.get(x, x)).lower())
			if len(found_leaves) == 1:
				print(f"Answer: {format_path_string([found_leaves[0], target_node], nodes, edge_values)}")
			else:
				print("Answer(s):")
				for s in found_leaves:
					print(f"  • {format_path_string([s, target_node], nodes, edge_values)}")

			print()
			progress_data[game2_key][leaf_key] = current_counter + 1
			save_progress(save_path, progress_data)
			new_tiers = get_global_tiers()
			if new_tiers != current_tiers:
				current_tiers = new_tiers
				print_relationship_stats()
			continue

		# Handle Leaf Destination Question
		elif itype == 'leaf_dst':
			source_node = data
			source_name = nodes.get(source_node, source_node)
			leaf_key = f"leaf_dst:{source_name}"
			current_counter = progress_data[game2_key].get(leaf_key, 0)

			print(f"Question {question_num}: {source_name} → [?]", end=' ')
			user_input = input().strip()
			if user_input == '0':
				print("Stopping the game.")
				break

			found_leaves = sorted(leaf_dests_map[source_node], key=lambda x: str(nodes.get(x, x)).lower())
			if len(found_leaves) == 1:
				print(f"Answer: {format_path_string([source_node, found_leaves[0]], nodes, edge_values)}")
			else:
				print("Answer(s):")
				for d in found_leaves:
					print(f"  • {format_path_string([source_node, d], nodes, edge_values)}")

			print()
			progress_data[game2_key][leaf_key] = current_counter + 1
			save_progress(save_path, progress_data)
			new_tiers = get_global_tiers()
			if new_tiers != current_tiers:
				current_tiers = new_tiers
				print_relationship_stats()
			continue

		# Handle Pair Question
		else:
			u, v = data
			if random.random() > 0.5:
				u, v = v, u

			u_name = nodes.get(u, u)
			v_name = nodes.get(v, v)
			pair_key = get_pair_key(u, v)
			current_counter = progress_data[game2_key].get(pair_key, 0)

			print(f"Question {question_num}: {u_name} [?] {v_name}", end=' ')

			user_input = input().strip()
			if user_input == '0':
				print("Stopping the game.")
				break

			has_u_v = nx.has_path(g, u, v)
			has_v_u = nx.has_path(g, v, u)
			paths_u_v = list(nx.all_shortest_paths(g, u, v)) if has_u_v else []
			paths_v_u = list(nx.all_shortest_paths(g, v, u)) if has_v_u else []

			# Filter out paths exceeding MAX_INDIRECTNESS_GAME (intermediate nodes > MAX_INDIRECTNESS_GAME)
			paths_u_v = [p for p in paths_u_v if (len(p) - 2) <= max_indirectness_game]
			paths_v_u = [p for p in paths_v_u if (len(p) - 2) <= max_indirectness_game]

			has_disp_u_v = bool(paths_u_v)
			has_disp_v_u = bool(paths_v_u)

			len_u_v = len(paths_u_v[0]) - 1 if paths_u_v else float('inf')
			len_v_u = len(paths_v_u[0]) - 1 if paths_v_u else float('inf')

			is_direct = (len_u_v == 1 or len_v_u == 1)
			is_indirect = not is_direct and (has_disp_u_v or has_disp_v_u)

			# Find shared sources and shared destinations
			shared_srcs = [s for s in set(g.predecessors(u)).intersection(g.predecessors(v)) if s != u and s != v]
			shared_dsts = [d for d in set(g.successors(u)).intersection(g.successors(v)) if d != u and d != v]

			shared_srcs.sort(key=lambda s: str(nodes.get(s, s)).lower())
			shared_dsts.sort(key=lambda d: str(nodes.get(d, d)).lower())

			# Collect all distinct connection options
			connection_lines = []
			if is_direct:
				if len_u_v == 1 and len_v_u == 1:
					connection_lines.append(f"Direct (⟳): {format_path_string([u, v], nodes, edge_values)} ↔ {format_path_string([v, u], nodes, edge_values)}")
				elif len_u_v == 1:
					connection_lines.append(f"Direct: {format_path_string([u, v], nodes, edge_values)}")
					if has_disp_v_u:
						for p in paths_v_u:
							connection_lines.append(f"Indirect ↩ ({len(p) - 2}): {format_path_string(p, nodes, edge_values)} ({get_path_net_effect_arrow(p, edge_values)})")
				elif len_v_u == 1:
					connection_lines.append(f"Direct: {format_path_string([v, u], nodes, edge_values)}")
					if has_disp_u_v:
						for p in paths_u_v:
							connection_lines.append(f"Indirect ↩ ({len(p) - 2}): {format_path_string(p, nodes, edge_values)} ({get_path_net_effect_arrow(p, edge_values)})")
			elif is_indirect:
				if has_disp_u_v:
					for p in paths_u_v:
						connection_lines.append(f"Indirect ({len(p) - 2}): {format_path_string(p, nodes, edge_values)} ({get_path_net_effect_arrow(p, edge_values)})")
				if has_disp_v_u:
					for p in paths_v_u:
						prefix = "Indirect ↩" if has_disp_u_v else "Indirect"
						connection_lines.append(f"{prefix} ({len(p) - 2}): {format_path_string(p, nodes, edge_values)} ({get_path_net_effect_arrow(p, edge_values)})")

			for s in shared_srcs:
				val_u = edge_values.get((s, u), 1)
				val_v = edge_values.get((s, v), 1)
				arr_u = "📉" if val_u < 0 else "📈"
				arr_v = "📉" if val_v < 0 else "📈"
				if arr_u == arr_v:
					connection_lines.append(f"Shared Source: {nodes.get(s, s)} {arr_u} 🅰️&🅱️")
				else:
					connection_lines.append(f"Shared Source: {nodes.get(s, s)} {arr_u} {nodes.get(u, u)} + {arr_v} {nodes.get(v, v)}")

			for d in shared_dsts:
				val_u = edge_values.get((u, d), 1)
				val_v = edge_values.get((v, d), 1)
				arr_u = "📉" if val_u < 0 else "📈"
				arr_v = "📉" if val_v < 0 else "📈"
				if arr_u == arr_v:
					connection_lines.append(f"Shared Destination: 🅰️&🅱️ {arr_u} {nodes.get(d, d)}")
				else:
					connection_lines.append(f"Shared Destination: {nodes.get(u, u)} ({arr_u}) + {nodes.get(v, v)} ({arr_v}) → {nodes.get(d, d)}")

			# Find feedback loops / cycles
			if max_cycle_length_game >= 2:
				paths_fwd = list(nx.all_simple_paths(g, source=u, target=v, cutoff=max_cycle_length_game - 1))
				paths_bwd = list(nx.all_simple_paths(g, source=v, target=u, cutoff=max_cycle_length_game - 1))
				seen_cycles = set()
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
							if canonical not in seen_cycles:
								seen_cycles.add(canonical)
								pair_cycles.append(full_cycle)

				pair_cycles.sort(key=lambda c: (len(c), [str(nodes.get(n, n)) for n in c]))

				for cyc in pair_cycles:
					cycle_corr = 1
					for k in range(len(cyc) - 1):
						cycle_corr *= edge_values.get((cyc[k], cyc[k + 1]), 1)
					polarity_icon = "[💥]" if cycle_corr > 0 else "[⚖️]"
					cyc_len = len(cyc) - 1
					connection_lines.append(f"Cycle ({cyc_len}) {polarity_icon}: {format_path_string(cyc, nodes, edge_values)}")

			if not connection_lines:
				print("Answer: IRRELEVANT")
			elif len(connection_lines) == 1:
				print(f"Answer: {connection_lines[0]}")
			else:
				for line in connection_lines:
					print(f"  • {line}")

			print()
			progress_data[game2_key][pair_key] = current_counter + 1
			save_progress(save_path, progress_data)
			new_tiers = get_global_tiers()
			if new_tiers != current_tiers:
				current_tiers = new_tiers
				print_relationship_stats()

	print("Quiz finished.")
	sys.exit(0)
