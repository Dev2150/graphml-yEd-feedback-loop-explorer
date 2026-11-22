import random
import sys

from src.games.relationship.handlers import (
	handle_cycle_question,
	handle_leaf_dest_question,
	handle_leaf_source_question,
	handle_pair_question,
)
from src.games.relationship.preparer import prepare_relationship_game_data
from src.games.relationship.progress import (
	build_stats_snapshot,
	choose_next_item,
	get_item_key,
)
from src.diagram import AnswerHighlight
from src.models import GraphContext
from src.storage import get_save_file_path, load_progress, save_progress


class GameCancelledError(Exception):
	pass


def run_relationship_guessing_game(
	ctx: GraphContext,
	input_fn=None,
	exit_on_finish: bool = True,
	on_stats_update=None,
	prepared_data: dict = None,
	on_graph_update=None,
	on_answer_output=None,
):
	_input = input_fn if input_fn is not None else input
	print("\nGuess if the nodes connect directly, indirectly, share a source/destination, are a leaf (source/dest), form a cycle, or are irrelevant.\n")

	def emit_answer(text: str, highlight: AnswerHighlight = None):
		if on_answer_output is not None:
			on_answer_output(text, highlight)
		else:
			print(text)

	nodes = ctx.nodes
	config = ctx.config
	chance_irrelevant = config.chance_irrelevant

	if prepared_data is None:
		prepared_data = prepare_relationship_game_data(ctx)

	all_relevant_items = prepared_data["all_relevant_items"]
	irrelevant_items = prepared_data["irrelevant_items"]
	category_config = prepared_data["category_config"]

	if not all_relevant_items and not irrelevant_items:
		print("No valid questions found matching your graph and filter settings.")
		if on_stats_update is not None:
			on_stats_update({"rows": [], "current_tier": 0})
		if on_graph_update is not None:
			on_graph_update(None)
		return

	# Load progress
	save_path = get_save_file_path(config.file_name)
	progress_data = load_progress(save_path)
	game2_key = "game2_relationship"
	if game2_key not in progress_data:
		progress_data[game2_key] = {}

	def get_item_count(item):
		return progress_data[game2_key].get(get_item_key(item, nodes), 0)

	def get_global_tiers():
		rel_min = min((get_item_count(it) for it in all_relevant_items), default=0)
		if chance_irrelevant <= 0.0 and all_relevant_items:
			return (rel_min, None)
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
		stats = build_stats_snapshot(
			nodes,
			category_config,
			progress_data[game2_key],
			chance_irrelevant=chance_irrelevant,
		)
		if on_stats_update is not None:
			on_stats_update(stats)
		else:
			new_tiers = get_global_tiers()
			if force_cli_print or new_tiers != current_tiers:
				current_tiers = new_tiers
				print_relationship_stats(stats)

	current_tiers = get_global_tiers()
	emit_stats(force_cli_print=True)
	if on_graph_update is not None:
		on_graph_update(None)
	question_num = 0

	while True:
		question_num += 1

		chosen_item = choose_next_item(
			category_config=category_config,
			all_relevant_items=all_relevant_items,
			game_progress=progress_data[game2_key],
			nodes_dict=nodes,
			chance_irrelevant=chance_irrelevant,
		)
		if chosen_item is None:
			print("No questions available.")
			break

		itype, data = chosen_item

		if itype == 'cycle':
			should_continue = handle_cycle_question(
				question_num, data, ctx, prepared_data, _input, emit_answer, on_graph_update
			)
		elif itype == 'leaf_src':
			should_continue = handle_leaf_source_question(
				question_num, data, ctx, prepared_data, _input, emit_answer, on_graph_update
			)
		elif itype == 'leaf_dst':
			should_continue = handle_leaf_dest_question(
				question_num, data, ctx, prepared_data, _input, emit_answer, on_graph_update
			)
		else:
			should_continue = handle_pair_question(
				question_num, data, ctx, prepared_data, _input, emit_answer, on_graph_update
			)

		if not should_continue:
			break

		item_key = get_item_key(chosen_item, nodes)
		progress_data[game2_key][item_key] = progress_data[game2_key].get(item_key, 0) + 1
		save_progress(save_path, progress_data)
		emit_stats()

	print("Quiz finished.")
	if exit_on_finish:
		sys.exit(0)

def compute_relationship_stats(ctx: GraphContext, prepared_data: dict = None) -> dict:
	if prepared_data is None:
		prepared_data = prepare_relationship_game_data(ctx)
	save_path = get_save_file_path(ctx.config.file_name)
	progress_data = load_progress(save_path)
	game_progress = progress_data.get("game2_relationship", {})
	return build_stats_snapshot(
		ctx.nodes,
		prepared_data["category_config"],
		game_progress,
		chance_irrelevant=ctx.config.chance_irrelevant,
	)