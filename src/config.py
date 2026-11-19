# Manage configuration defaults, parse input.txt, handle inline overrides, and return a clean, strongly typed Config dataclass.

import configparser
import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SECTION = 'SETTINGS'
COUNTER_CONNECTION_TYPES = {'counter', 'counters', 'game', 'game-counters'}
FAMILY_CONNECTION_TYPES = {'family', 'family-descendance', 'descendance', 'genealogy', 'tree', 'familytree', 'family-tree'}

APP_SETTING_KEYS = (
	'folder_path',
	'file_name',
)

GRAPH_SETTING_KEYS = (
	'connection_type',
	'ignore_edge_colors',
	'color_threshold',
	'show_connections_list',
	'connections_skipped',
	'show_only_edges',
	'show_edge_labels',
	'enable_non_cycle_printing',
	'sort_by_len',
	'sort_connections_alphabetically',
	'max_cycle_length_html',
	'max_indirectness',
	'source_node',
	'target_node',
	'block_starting_node',
	'excluded_elements',
	'chance_irrelevant',
	'max_cycle_length_game',
	'max_indirectness_game',
	'leaf_only',
	'include_secondary_cycles',
)


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
	sort_connections_alphabetically: bool = False
	color_threshold: int = 48
	max_cycle_length_html: int = 5
	max_cycle_length_game: int = 3
	folder_path: str = ""
	file_name: str = ""
	block_starting_node: List[str] = field(default_factory=list)
	excluded_elements: List[str] = field(default_factory=list)
	chance_irrelevant: float = 0.20
	max_indirectness: int = 1
	max_indirectness_game: int = 2
	leaf_only: bool = False
	ignore_edge_colors: bool = False
	connection_type: str = "correlation"
	include_secondary_cycles: bool = True

def _parse_list_setting(raw: str, lowercase: bool = False) -> List[str]:
	raw = (raw or "").strip()
	if not raw:
		return []
	items: List[str] = []
	if raw.startswith('['):
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, list):
				items = [str(x).strip() for x in parsed if str(x).strip()]
		except Exception:
			items = []
	if not items:
		if '\n' in raw:
			items = [x.strip() for x in raw.splitlines() if x.strip()]
		else:
			items = [x.strip() for x in raw.split(',') if x.strip()]
	return [x.lower() for x in items] if lowercase else items


def _serialize_list_setting(items: List[str]) -> str:
	clean = [str(x).strip() for x in items if str(x).strip()]
	if any(',' in x or '\n' in x for x in clean):
		return json.dumps(clean)
	return ', '.join(clean)


def config_to_graph_dict(cfg: Config) -> Dict[str, Any]:
	"""Extracts per-GraphML configurable properties as a JSON-serializable dict."""
	return {
		'source_node': cfg.source_node,
		'target_node': cfg.target_node,
		'show_only_edges': bool(cfg.show_only_edges),
		'show_connections_list': bool(cfg.show_connections_list),
		'show_edge_labels': bool(cfg.show_edge_labels),
		'connections_skipped': int(cfg.connections_skipped),
		'enable_non_cycle_printing': bool(cfg.enable_non_cycle_printing),
		'sort_by_len': bool(cfg.sort_by_len),
		'sort_connections_alphabetically': bool(cfg.sort_connections_alphabetically),
		'color_threshold': int(cfg.color_threshold),
		'max_cycle_length_html': int(cfg.max_cycle_length_html),
		'max_cycle_length_game': int(cfg.max_cycle_length_game),
		'block_starting_node': list(cfg.block_starting_node),
		'excluded_elements': list(cfg.excluded_elements),
		'chance_irrelevant': float(cfg.chance_irrelevant),
		'max_indirectness': int(cfg.max_indirectness),
		'max_indirectness_game': int(cfg.max_indirectness_game),
		'leaf_only': bool(cfg.leaf_only),
		'ignore_edge_colors': bool(cfg.ignore_edge_colors),
		'connection_type': cfg.connection_type,
		'include_secondary_cycles': bool(cfg.include_secondary_cycles),
	}


def apply_graph_dict_to_config(base_cfg: Config, data: Dict[str, Any]) -> Config:
	"""Returns a copy of base_cfg with per-GraphML properties overlaid from data."""
	cfg = copy.deepcopy(base_cfg)
	if not isinstance(data, dict):
		return cfg

	if 'source_node' in data:
		cfg.source_node = str(data['source_node'] or '').strip().lower()
	if 'target_node' in data:
		cfg.target_node = str(data['target_node'] or '').strip().lower()
	if 'show_only_edges' in data:
		cfg.show_only_edges = bool(data['show_only_edges'])
	if 'show_connections_list' in data:
		cfg.show_connections_list = bool(data['show_connections_list'])
	if 'show_edge_labels' in data:
		cfg.show_edge_labels = bool(data['show_edge_labels'])
	if 'connections_skipped' in data:
		cfg.connections_skipped = int(data['connections_skipped'])
	if 'enable_non_cycle_printing' in data:
		cfg.enable_non_cycle_printing = bool(data['enable_non_cycle_printing'])
	if 'sort_by_len' in data:
		cfg.sort_by_len = bool(data['sort_by_len'])
	if 'sort_connections_alphabetically' in data:
		cfg.sort_connections_alphabetically = bool(data['sort_connections_alphabetically'])
	if 'color_threshold' in data:
		cfg.color_threshold = int(data['color_threshold'])
	if 'max_cycle_length_html' in data:
		cfg.max_cycle_length_html = int(data['max_cycle_length_html'])
	if 'max_cycle_length_game' in data:
		cfg.max_cycle_length_game = int(data['max_cycle_length_game'])
	if 'block_starting_node' in data and isinstance(data['block_starting_node'], list):
		cfg.block_starting_node = [str(x).strip().lower() for x in data['block_starting_node'] if str(x).strip()]
	if 'excluded_elements' in data and isinstance(data['excluded_elements'], list):
		cfg.excluded_elements = [str(x).strip() for x in data['excluded_elements'] if str(x).strip()]
	if 'chance_irrelevant' in data:
		chance = float(data['chance_irrelevant'])
		if chance > 1.0:
			chance /= 100.0
		cfg.chance_irrelevant = chance
	if 'max_indirectness' in data:
		cfg.max_indirectness = int(data['max_indirectness'])
	if 'max_indirectness_game' in data:
		cfg.max_indirectness_game = int(data['max_indirectness_game'])
	if 'leaf_only' in data:
		cfg.leaf_only = bool(data['leaf_only'])
	if 'connection_type' in data:
		cfg.connection_type = str(data['connection_type'] or 'correlation').strip().lower()
	if 'ignore_edge_colors' in data:
		cfg.ignore_edge_colors = bool(data['ignore_edge_colors'])
	if 'include_secondary_cycles' in data:
		cfg.include_secondary_cycles = bool(data['include_secondary_cycles'])

	return cfg


def build_effective_config(
	base_cfg: Config,
	local_overrides: Optional[Dict[str, Any]] = None,
	filepath: str = "",
) -> Config:
	"""Merges global defaults with per-file overrides without mutating base_cfg's app settings."""
	effective = apply_graph_dict_to_config(base_cfg, local_overrides or {})
	if filepath:
		norm_path = os.path.abspath(filepath)
		effective.folder_path = os.path.dirname(norm_path) + os.sep
		effective.file_name = os.path.basename(norm_path)
	return effective


def read_config_file(p_input_file: str) -> Config:
	config = configparser.ConfigParser()
	config.read(p_input_file, encoding='utf-8')

	p_source_node = config.get(SECTION, 'source_node', fallback='').strip().lower()
	p_target_node = config.get(SECTION, 'target_node', fallback='').strip().lower()

	show_only_edges = config.getboolean(SECTION, 'show_only_edges', fallback=False)
	show_connections_list = config.getboolean(SECTION, 'show_connections_list', fallback=False)
	show_edge_labels = config.getboolean(SECTION, 'show_edge_labels', fallback=False)
	connections_skipped = config.getint(SECTION, 'connections_skipped', fallback=0)
	enable_non_cycle_printing = config.getboolean(SECTION, 'enable_non_cycle_printing', fallback=False)
	sort_by_len = config.getboolean(SECTION, 'sort_by_len', fallback=False)

	raw_sort_conn = config.get(
		SECTION,
		'sort_connections_alphabetically',
		fallback=config.get(
			SECTION,
			'connections_sort_order',
			fallback=config.get(SECTION, 'sort_connections', fallback='false'),
		),
	).strip().lower()
	sort_connections_alphabetically = raw_sort_conn in ('true', '1', 'yes', 'alphabetical', 'alphabetic', 'alpha')

	color_threshold = config.getint(SECTION, 'color_threshold', fallback=48)
	folder_path = config.get(SECTION, 'folder_path', fallback='').strip()
	file_name_raw = config.get(SECTION, 'file_name', fallback='').strip()

	block_starting_node_str = config.get(SECTION, 'block_starting_node', fallback='')
	block_starting_node = _parse_list_setting(block_starting_node_str, lowercase=True)

	excluded_elements_str = config.get(SECTION, 'excluded_elements', fallback='')
	excluded_elements = _parse_list_setting(excluded_elements_str, lowercase=False)

	chance_irrelevant = config.getfloat(SECTION, 'chance_irrelevant', fallback=0.20)
	if chance_irrelevant > 1.0:
		chance_irrelevant /= 100.0

	max_cycle_length_html = config.getint(
		SECTION, 'max_cycle_length_html',
		fallback=config.getint(SECTION, 'max_cycle_length', fallback=0),
	)
	max_cycle_length_game = config.getint(SECTION, 'max_cycle_length_game', fallback=3)
	max_indirectness = config.getint(SECTION, 'max_indirectness', fallback=3)
	max_indirectness_game = config.getint(SECTION, 'max_indirectness_game', fallback=3)
	leaf_only = config.getboolean(SECTION, 'leaf_only', fallback=False)
	connection_type = config.get(SECTION, 'connection_type', fallback='correlation').strip().lower()
	ignore_edge_colors = config.getboolean(SECTION, 'ignore_edge_colors', fallback=False)
	include_secondary_cycles = config.getboolean(SECTION, 'include_secondary_cycles', fallback=True)

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
				elif key in ('sort_connections_alphabetically', 'sort_connections', 'connections_sort_order'):
					sort_connections_alphabetically = val.lower() in ('true', '1', 'yes', 'alphabetical', 'alphabetic', 'alpha')
				elif key == 'connection_type':
					connection_type = val.lower()
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
				elif key == 'excluded_elements':
					excluded_elements = [x.strip() for x in val.split(';') if x.strip()]
				elif key == 'include_secondary_cycles':
					include_secondary_cycles = val.lower() in ('true', '1', 'yes')
				else:
					print(f"Warning: unknown inline override '{key}' ignored.")
			except ValueError:
				print(f"Warning: could not parse inline override '{override.strip()}', skipping.")
	else:
		file_name = file_name_raw

	return Config(
		source_node=p_source_node,
		target_node=p_target_node,
		show_only_edges=show_only_edges,
		show_connections_list=show_connections_list,
		show_edge_labels=show_edge_labels,
		connections_skipped=connections_skipped,
		enable_non_cycle_printing=enable_non_cycle_printing,
		sort_by_len=sort_by_len,
		sort_connections_alphabetically=sort_connections_alphabetically,
		color_threshold=color_threshold,
		max_cycle_length_html=max_cycle_length_html,
		max_cycle_length_game=max_cycle_length_game,
		folder_path=folder_path,
		file_name=file_name,
		block_starting_node=block_starting_node,
		excluded_elements=excluded_elements,
		chance_irrelevant=chance_irrelevant,
		max_indirectness=max_indirectness,
		max_indirectness_game=max_indirectness_game,
		leaf_only=leaf_only,
		ignore_edge_colors=ignore_edge_colors,
		connection_type=connection_type,
		include_secondary_cycles=include_secondary_cycles,
	)


def create_input_file(p_input_file: str):
	print(f"Configuration file '{p_input_file}' not found. Creating a default one.")
	default_content = f"""[{SECTION}]
SOURCE_NODE=
TARGET_NODE=
SHOW_ONLY_EDGES=False
SHOW_CONNECTIONS_LIST=True
SHOW_EDGE_LABELS=False
CONNECTIONS_SKIPPED=0
ENABLE_NON_CYCLE_PRINTING=True
SORT_BY_LEN=False
SORT_CONNECTIONS_ALPHABETICALLY=False
COLOR_THRESHOLD=48
MAX_CYCLE_LENGTH_HTML=5
MAX_CYCLE_LENGTH_GAME=3
FOLDER_PATH=
FILE_NAME=
BLOCK_STARTING_NODE=
EXCLUDED_ELEMENTS=
CHANCE_IRRELEVANT=0.20
MAX_INDIRECTNESS=1
MAX_INDIRECTNESS_GAME=2
LEAF_ONLY=False
INCLUDE_SECONDARY_CYCLES=True
CONNECTION_TYPE=correlation
"""
	try:
		parent = os.path.dirname(p_input_file)
		if parent:
			os.makedirs(parent, exist_ok=True)
		with open(p_input_file, 'w', encoding='utf-8') as f:
			f.write(default_content)
		print("Default configuration file created successfully.")
	except Exception as e:
		print(f"Error creating default configuration file: {e}")


def save_config_file(p_input_file: str, cfg: Config):
	config = configparser.ConfigParser()
	config.optionxform = str
	config[SECTION] = {
		'SOURCE_NODE': cfg.source_node,
		'TARGET_NODE': cfg.target_node,
		'SHOW_ONLY_EDGES': str(cfg.show_only_edges),
		'SHOW_CONNECTIONS_LIST': str(cfg.show_connections_list),
		'SHOW_EDGE_LABELS': str(cfg.show_edge_labels),
		'CONNECTIONS_SKIPPED': str(cfg.connections_skipped),
		'ENABLE_NON_CYCLE_PRINTING': str(cfg.enable_non_cycle_printing),
		'SORT_BY_LEN': str(cfg.sort_by_len),
		'SORT_CONNECTIONS_ALPHABETICALLY': str(cfg.sort_connections_alphabetically),
		'COLOR_THRESHOLD': str(cfg.color_threshold),
		'MAX_CYCLE_LENGTH_HTML': str(cfg.max_cycle_length_html),
		'MAX_CYCLE_LENGTH_GAME': str(cfg.max_cycle_length_game),
		'FOLDER_PATH': cfg.folder_path,
		'FILE_NAME': cfg.file_name,
		'BLOCK_STARTING_NODE': _serialize_list_setting(cfg.block_starting_node),
		'EXCLUDED_ELEMENTS': _serialize_list_setting(cfg.excluded_elements),
		'CHANCE_IRRELEVANT': str(cfg.chance_irrelevant),
		'MAX_INDIRECTNESS': str(cfg.max_indirectness),
		'MAX_INDIRECTNESS_GAME': str(cfg.max_indirectness_game),
		'LEAF_ONLY': str(cfg.leaf_only),
		'INCLUDE_SECONDARY_CYCLES': str(cfg.include_secondary_cycles),
		'IGNORE_EDGE_COLORS': str(cfg.ignore_edge_colors),
		'CONNECTION_TYPE': cfg.connection_type,
	}
	parent_dir = os.path.dirname(os.path.abspath(p_input_file))
	if parent_dir:
		os.makedirs(parent_dir, exist_ok=True)
	with open(p_input_file, 'w', encoding='utf-8') as f:
		config.write(f, space_around_delimiters=False)