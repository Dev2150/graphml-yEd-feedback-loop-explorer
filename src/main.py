import os

import networkx as nx

from games.relationship_game import run_relationship_guessing_game
from html_exporter import generate_html_and_graphml
from io_graphml import read_from_graph_xml
from src.config import read_config_file, create_input_file, COUNTER_CONNECTION_TYPES
from src.models import GraphContext

DEBUGGING = True
PREFIX = 'src//' if DEBUGGING else '_internal//src//'
INPUT_FILE = PREFIX + 'input.txt'
OUTPUT_FOLDER = 'output//'

# Define the section name
SECTION = 'SETTINGS'


def main():
	if not os.path.exists(INPUT_FILE):
		create_input_file(INPUT_FILE)

	config = read_config_file(INPUT_FILE)

	# Determine input path
	if '/' in config.file_name or '\\' in config.file_name or os.path.isabs(config.file_name):
		input_graph_ml = config.file_name if config.file_name.endswith('.graphml') else config.file_name + '.graphml'
	else:
		input_graph_ml = config.folder_path + config.file_name + ('' if config.file_name.endswith('.graphml') else '.graphml')

	# Parse GraphML
	nodes, edges, edge_values, node_values, edge_labels, node_colors = read_from_graph_xml(input_graph_ml, config.color_threshold)

	if config.ignore_edge_colors or config.connection_type in COUNTER_CONNECTION_TYPES:
		edge_values = {k: 1 for k in edge_values}
		node_values = {k: 0 for k in node_values}
		print("Note: edge colors ignored — all edge values set to +1.")

	g = nx.DiGraph()
	g.add_nodes_from(nodes.keys())
	g.add_edges_from(edges)

	# Resolve source/target IDs
	src_id = next((nid for nid, label in nodes.items() if label.lower() == config.source_node), None) if config.source_node else None
	tgt_id = next((nid for nid, label in nodes.items() if label.lower() == config.target_node), None) if config.target_node else None

	if config.source_node and not src_id:
		raise ValueError(f"Could not find source node: {config.source_node}")
	if config.target_node and not tgt_id:
		raise ValueError(f"Could not find target node: {config.target_node}")

	# Build Context
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

	# Always generate HTML & GraphML first
	generate_html_and_graphml(ctx, OUTPUT_FOLDER, input_graph_ml)

	# Menu
	print("=" * 50)
	print("Select Game Mode:")
	print("  [1] Relationship Guessing Game (Direct / Indirect / Same / Irrelevant)")
	print("  [0] Exit (HTML already generated)")
	print("=" * 50)
	choice = input("Enter choice (0-1): ").strip()

	if choice == '1':
		run_relationship_guessing_game(ctx)


if __name__ == '__main__':
	main()