# Manage configuration defaults, parse input.txt, handle inline overrides, and return a clean, strongly typed Config dataclass instead of an 18-element tuple.

import configparser
import os
from dataclasses import dataclass, field
from typing import List

SECTION = 'SETTINGS'
COUNTER_CONNECTION_TYPES = {'counter', 'counters', 'game', 'game-counters'}


@dataclass
class Config:
	source_node: str = ""
	target_node: str = ""
	show_only_edges: bool = False
	show_connections_list: bool = False
	show_edge_labels: bool = False
	connections_skipped: int = 0
	enable_non_cycle_printing: bool = False
	sort_by_len: bool = False
	color_threshold: int = 48
	max_cycle_length_html: int = 5
	max_cycle_length_game: int = 3
	folder_path: str = ""
	file_name: str = ""
	block_starting_node: List[str] = field(default_factory=list)
	chance_irrelevant: float = 0.20
	max_indirectness: int = 1
	max_indirectness_game: int = 2
	leaf_only: bool = False
	ignore_edge_colors: bool = False
	connection_type: str = "correlation"


def read_config_file(p_input_file: str) -> Config:
	config = configparser.ConfigParser()
	config.read(p_input_file)

	# Safely get values with type conversion and defaults
	p_source_node = config.get(SECTION, 'source_node', fallback='').strip().lower()
	p_target_node = config.get(SECTION, 'target_node', fallback='').strip().lower()

	# configparser has built-in methods for booleans and integers
	show_only_edges = config.getboolean(SECTION, 'show_only_edges', fallback=False)
	show_connections_list = config.getboolean(SECTION, 'show_connections_list', fallback=False)
	show_edge_labels = config.getboolean(SECTION, 'show_edge_labels', fallback=False)
	connections_skipped = config.getint(SECTION, 'connections_skipped', fallback=0)
	enable_non_cycle_printing = config.getboolean(SECTION, 'enable_non_cycle_printing', fallback=False)
	sort_by_len = config.getboolean(SECTION, 'sort_by_len', fallback=False)

	color_threshold = config.getint(SECTION, 'color_threshold', fallback=48)
	folder_path = config.get(SECTION, 'folder_path', fallback='').strip()
	file_name_raw = config.get(SECTION, 'file_name', fallback='').strip()

	block_starting_node_str = config.get(SECTION, 'block_starting_node', fallback='')
	block_starting_node = [x.strip().lower() for x in block_starting_node_str.split(',') if
						   x.strip()] if block_starting_node_str else []

	# Game settings
	chance_irrelevant = config.getfloat(SECTION, 'chance_irrelevant', fallback=0.20)
	if chance_irrelevant > 1.0:
		chance_irrelevant /= 100.0

	max_cycle_length_html = config.getint(SECTION, 'max_cycle_length_html',
										  fallback=config.getint(SECTION, 'max_cycle_length', fallback=0))
	max_cycle_length_game = config.getint(SECTION, 'max_cycle_length_game', fallback=3)
	max_indirectness = config.getint(SECTION, 'max_indirectness', fallback=3)
	max_indirectness_game = config.getint(SECTION, 'max_indirectness_game', fallback=3)
	leaf_only = config.getboolean(SECTION, 'leaf_only', fallback=False)
	connection_type = config.get(SECTION, 'connection_type', fallback='correlation').strip().lower()
	ignore_edge_colors = connection_type in COUNTER_CONNECTION_TYPES

	# Parse inline overrides appended after the filename with commas:
	# FILE_NAME=My Graph, ignore_edge_colors=True, connection_type=family
	if ',' in file_name_raw:
		parts = file_name_raw.split(',')
		file_name = parts[0].strip()
		for override in parts[1:]:
			if '=' not in override:
				continue
			key, _, val = override.strip().partition('=')
			key = key.strip().lower()
			val = val.strip()
			try:
				if key == 'ignore_edge_colors':
					ignore_edge_colors = val.lower() in ('true', '1', 'yes')
				elif key == 'show_edge_labels':
					show_edge_labels = val.lower() in ('true', '1', 'yes')
				elif key == 'connection_type':
					connection_type = val.lower()
					if connection_type in COUNTER_CONNECTION_TYPES:
						ignore_edge_colors = True
				elif key == 'max_cycle_length_html':
					max_cycle_length_html = int(val)
				elif key == 'max_cycle_length_game':
					max_cycle_length_game = int(val)
				elif key == 'max_indirectness':
					max_indirectness = int(val)
				elif key == 'max_indirectness_game':
					max_indirectness_game = int(val)
				elif key == 'chance_irrelevant':
					chance_irrelevant = float(val)
					if chance_irrelevant > 1.0:
						chance_irrelevant /= 100.0
				else:
					print(f"Warning: unknown inline override '{key}' ignored.")
			except ValueError:
				print(f"Warning: could not parse inline override '{override.strip()}', skipping.")
	else:
		file_name = file_name_raw

	if connection_type in COUNTER_CONNECTION_TYPES:
		ignore_edge_colors = True

	return Config(
		source_node=p_source_node,
		target_node=p_target_node,
		show_only_edges=show_only_edges,
		show_connections_list=show_connections_list,
		show_edge_labels=show_edge_labels,
		connections_skipped=connections_skipped,
		enable_non_cycle_printing=enable_non_cycle_printing,
		sort_by_len=sort_by_len,
		color_threshold=color_threshold,
		max_cycle_length_html=max_cycle_length_html,
		max_cycle_length_game=max_cycle_length_game,
		folder_path=folder_path,
		file_name=file_name,
		block_starting_node=block_starting_node,
		chance_irrelevant=chance_irrelevant,
		max_indirectness=max_indirectness,
		max_indirectness_game=max_indirectness_game,
		leaf_only=leaf_only,
		ignore_edge_colors=ignore_edge_colors,
		connection_type=connection_type
	)


def create_input_file(p_input_file: str):
	print(f"Configuration file '{p_input_file}' not found. Creating a default one.")
	default_content = f"""[{SECTION}]
SOURCE_NODE=
TARGET_NODE=
SHOW_ONLY_EDGES=False
SHOW_CONNECTIONS_LIST=False
SHOW_EDGE_LABELS=False
CONNECTIONS_SKIPPED=0
ENABLE_NON_CYCLE_PRINTING=True
SORT_BY_LEN=False
COLOR_THRESHOLD=48
MAX_CYCLE_LENGTH_HTML=5
MAX_CYCLE_LENGTH_GAME=3
FOLDER_PATH=
FILE_NAME=
BLOCK_STARTING_NODE=
CHANCE_IRRELEVANT=0.20
MAX_INDIRECTNESS=1
MAX_INDIRECTNESS_GAME=2
LEAF_ONLY=False
CONNECTION_TYPE=correlation
"""
	try:
		os.makedirs(os.path.dirname(p_input_file), exist_ok=True)
		with open(p_input_file, 'w') as f:
			f.write(default_content)
		print("Default configuration file created successfully.")
	except Exception as e:
		print(f"Error creating default configuration file: {e}")