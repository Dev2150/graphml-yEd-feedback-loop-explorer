import random
import sys
from collections import defaultdict

import networkx as nx

from src.models import GraphContext
from src.progress_storage import get_save_file_path, load_progress, save_progress


def run_connection_guessing_game(ctx: GraphContext):
	g = ctx.graph
	nodes = ctx.nodes
	edge_values = ctx.edge_values
	config = ctx.config
	block_starting_node = config.block_starting_node

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

	for source in g.nodes():
		if str(nodes.get(source, source)).lower() in block_starting_node:
			continue
		stack = [(source, [source])]
		while stack:
			curr, path = stack.pop()
			if len(path) - 1 == target_length:
				all_paths.append(path)
				continue
			for neighbor in g.successors(curr):
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

	save_path = get_save_file_path(config.file_name)
	progress_data = load_progress(save_path)

	skip_key = str(con_skipped)
	if skip_key not in progress_data:
		progress_data[skip_key] = {}

	def get_connection_game_stats():
		counts = [progress_data[skip_key].get(f"{nodes.get(s, s)},{nodes.get(t, t)}", 0)
				  for s, t in paths_by_pair]
		if not counts:
			return 0, 0, 0, 0
		min_c = min(counts)
		at_min = sum(1 for c in counts if c == min_c)
		total = len(counts)
		pct = int(100 * (total - at_min) / total) if total else 0
		return min_c, at_min, total, pct

	def print_connection_game_stats():
		min_c, at_min, total, pct = get_connection_game_stats()
		print(f"\n--- Progress [Tier {min_c}] ---")
		print(f"  Connections: {at_min}/{total} ({pct}%)\n")

	def get_counter_by_node_text(case):
		src_text = nodes.get(case[0], case[0])
		tgt_text = nodes.get(case[1], case[1])
		return progress_data[skip_key].get(f"{src_text},{tgt_text}", 0)

	quiz_cases.sort(key=lambda case: (
		get_counter_by_node_text(case),
		random.random()
	))

	print_connection_game_stats()
	current_tier = get_connection_game_stats()[0]
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
			arrow = "📉" if edge_val < 0 else "📈"

			if k < len(first_full_path) - 2:
				q_parts.append(f"{arrow} [?]")
			else:
				q_parts.append(f"{arrow} {tgt_name}")

		question_str = " ".join(q_parts)
		print(f"Question {i + 1}/{len(quiz_cases)}: {question_str}", end=' ')

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
				arrow = "📉" if edge_val < 0 else "📈"
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
					arrow = "📉" if edge_val < 0 else "📈"
					ans_parts.append(f"{arrow} {nodes.get(v, v)}")
				print(f"  Option {idx + 1}: {' '.join(ans_parts)}")

		shorter_paths = list(nx.all_simple_paths(g, source=src, target=tgt, cutoff=target_length - 1))
		if shorter_paths:
			print("More direct connection(s) also exist:")
			shorter_paths.sort(key=len)
			for sp in shorter_paths:
				sp_parts = [nodes.get(sp[0], sp[0])]
				for k in range(len(sp) - 1):
					u = sp[k]
					v = sp[k + 1]
					edge_val = edge_values.get((u, v), 1)
					arrow = "📉" if edge_val < 0 else "📈"
					sp_parts.append(f"{arrow} {nodes.get(v, v)}")
				print(f"  {' '.join(sp_parts)}")

		print()
		progress_data[skip_key][pair_key] = current_counter + 1
		save_progress(save_path, progress_data)
		new_tier = get_connection_game_stats()[0]
		if new_tier != current_tier:
			current_tier = new_tier
			print_connection_game_stats()

	print("Quiz finished.")
	sys.exit(0)