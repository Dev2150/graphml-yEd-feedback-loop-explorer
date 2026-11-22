import json
import os
from typing import Any, Dict, Optional

from src.storage.app_state import get_app_data_dir, get_sync_folder


def get_save_file_path(file_name: str) -> str:
	save_dir = get_app_data_dir()

	base_name = os.path.splitext(os.path.basename(file_name))[0]
	safe_name = "".join([c for c in base_name if c.isalnum() or c == ' ']).rstrip()
	if not safe_name:
		safe_name = "default_graph"

	return os.path.join(save_dir, f"{safe_name}_progress.json")


def load_progress(save_path: str) -> dict:
	if os.path.exists(save_path):
		try:
			with open(save_path, 'r', encoding='utf-8') as f:
				return json.load(f)
		except Exception as e:
			print(f"Error loading progress: {e}")
	return {}


def save_progress(save_path: str, progress_data: dict):
	try:
		with open(save_path, 'w', encoding='utf-8') as f:
			json.dump(progress_data, f, indent=4)
	except Exception as e:
		print(f"Error saving progress: {e}")


# ------------------------------------------------------------------
# Per-GraphML Configuration Storage
# ------------------------------------------------------------------
def get_graph_configs_path() -> str:
	return os.path.join(get_app_data_dir(), 'graph_configs.json')


def _graph_config_key(filepath: str) -> str:
	return os.path.normcase(os.path.abspath(filepath))


def _portable_graph_config_key(filepath: str) -> str:
	return os.path.basename(filepath).strip().lower()


def load_all_graph_configs() -> Dict[str, Dict[str, Any]]:
	cfg_path = get_graph_configs_path()
	if os.path.exists(cfg_path):
		try:
			with open(cfg_path, 'r', encoding='utf-8') as f:
				data = json.load(f)
			if isinstance(data, dict):
				return data
		except Exception as e:
			print(f"Error loading graph configs: {e}")
	return {}


def load_graph_config(filepath: str) -> Optional[Dict[str, Any]]:
	if not filepath:
		return None
	all_cfgs = load_all_graph_configs()
	entry = all_cfgs.get(_graph_config_key(filepath))
	if not isinstance(entry, dict):
		entry = all_cfgs.get(_portable_graph_config_key(filepath))
	return entry if isinstance(entry, dict) else None


def save_graph_config(filepath: str, config_dict: Dict[str, Any]):
	if not filepath:
		return
	if not config_dict:
		delete_graph_config(filepath)
		return
	all_cfgs = load_all_graph_configs()
	full_key = _graph_config_key(filepath)
	portable_key = _portable_graph_config_key(filepath)
	if get_sync_folder():
		all_cfgs.pop(full_key, None)
		all_cfgs[portable_key] = config_dict
	else:
		all_cfgs[full_key] = config_dict
	try:
		with open(get_graph_configs_path(), 'w', encoding='utf-8') as f:
			json.dump(all_cfgs, f, indent=4)
	except Exception as e:
		print(f"Error saving graph config: {e}")


def delete_graph_config(filepath: str) -> bool:
	if not filepath:
		return False
	all_cfgs = load_all_graph_configs()
	changed = False
	for key in (_graph_config_key(filepath), _portable_graph_config_key(filepath)):
		if key in all_cfgs:
			del all_cfgs[key]
			changed = True
	if changed:
		try:
			with open(get_graph_configs_path(), 'w', encoding='utf-8') as f:
				json.dump(all_cfgs, f, indent=4)
			return True
		except Exception as e:
			print(f"Error deleting graph config: {e}")
	return False