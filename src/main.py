import os
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SRC_DIR)
if ROOT_DIR not in sys.path:
	sys.path.insert(0, ROOT_DIR)

import networkx as nx

from src.config import (
	COUNTER_CONNECTION_TYPES,
	apply_graph_dict_to_config,
	create_input_file,
	read_config_file,
)
from src.games.relationship.runner import run_relationship_guessing_game
from src.gui_app import run_gui
from src.html_exporter import generate_html_and_graphml
from src.io_graphml import read_from_graph_xml
from src.models import GraphContext
from src.progress_storage import load_graph_config

DEBUGGING = True
PREFIX = 'src//' if DEBUGGING else '_internal//src//'
INPUT_FILE = os.path.join(ROOT_DIR, PREFIX, 'input.txt')
if not os.path.exists(INPUT_FILE) and os.path.exists(os.path.join(SRC_DIR, 'input.txt')):
	INPUT_FILE = os.path.join(SRC_DIR, 'input.txt')
OUTPUT_FOLDER = os.path.join(ROOT_DIR, 'output')


def run_cli():
	if not os.path.exists(INPUT_FILE):
		create_input_file(INPUT_FILE)

	config = read_config_file(INPUT_FILE)

	if '/' in config.file_name or '\\' in config.file_name or os.path.isabs(config.file_name):
		input_graph_ml = config.file_name if config.file_name.endswith('.graphml') else config.file_name + '.graphml'
	else:
		input_graph_ml = config.folder_path + config.file_name + ('' if config.file_name.endswith('.graphml') else '.graphml')

	input_graph_ml = os.path.abspath(input_graph_ml)
	saved_graph_cfg = load_graph_config(input_graph_ml)
	if saved_graph_cfg:
		config = apply_graph_dict_to_config(config, saved_graph_cfg)
		print(f"Loaded per-GraphML properties for '{os.path.basename(input_graph_ml)}'.")

	nodes, edges, edge_values, node_values, edge_labels, node_colors = read_from_graph_xml(
		input_graph_ml, config.color_threshold, config.excluded_elements
	)

	if config.ignore_edge_colors or config.connection_type in COUNTER_CONNECTION_TYPES:
		edge_values = {k: 1 for k in edge_values}
		node_values = {k: 0 for k in node_values}
		print("Note: edge colors ignored — all edge values set to +1.")

	g = nx.DiGraph()
	g.add_nodes_from(nodes.keys())
	g.add_edges_from(edges)

	src_id = next((nid for nid, label in nodes.items() if label.lower() == config.source_node), None) if config.source_node else None
	tgt_id = next((nid for nid, label in nodes.items() if label.lower() == config.target_node), None) if config.target_node else None

	if config.source_node and not src_id:
		raise ValueError(f"Could not find source node: {config.source_node}")
	if config.target_node and not tgt_id:
		raise ValueError(f"Could not find target node: {config.target_node}")

	ctx = GraphContext(
		graph=g,
		nodes=nodes,
		node_values=node_values,
		edges=edges,
		edge_values=edge_values,
		config=config,
		source_node_id=src_id,
		target_node_id=tgt_id,
		edge_labels=edge_labels,
		node_colors=node_colors
	)

	generate_html_and_graphml(ctx, OUTPUT_FOLDER, input_graph_ml)

	print()
	print("Select Game Mode:")
	print("  [1] Relationship Guessing Game (Direct / Indirect / Same / Irrelevant)")
	print("  [0] Exit (HTML already generated)")
	choice = input("Enter choice (0-1): ").strip()

	if choice == '1':
		run_relationship_guessing_game(ctx)


def main():
	if '--cli' in sys.argv:
		run_cli()
	else:
		run_gui(INPUT_FILE, OUTPUT_FOLDER)


if __name__ == '__main__':
	main()