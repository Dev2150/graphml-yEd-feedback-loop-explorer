import json
import os

MAX_RECENT_FILES = 50


def get_local_data_dir() -> str:
	override = os.environ.get('GRAPHML_EXPLORER_DATA_DIR')
	if override:
		os.makedirs(override, exist_ok=True)
		return override

	appdata = os.getenv('APPDATA')
	if not appdata:
		appdata = os.path.expanduser('~')

	save_dir = os.path.join(appdata, 'YAMLGuessingGame')
	os.makedirs(save_dir, exist_ok=True)
	return save_dir


def get_sync_settings_path() -> str:
	return os.path.join(get_local_data_dir(), 'sync_settings.json')


def get_sync_folder() -> str:
	settings_path = get_sync_settings_path()
	if os.path.exists(settings_path):
		try:
			with open(settings_path, 'r', encoding='utf-8') as f:
				data = json.load(f)
			if isinstance(data, dict):
				return str(data.get('sync_folder', '') or '').strip()
		except Exception as e:
			print(f"Error loading sync settings: {e}")
	return ''


def set_sync_folder(folder_path: str):
	clean = str(folder_path or '').strip()
	settings_path = get_sync_settings_path()
	try:
		with open(settings_path, 'w', encoding='utf-8') as f:
			json.dump({'sync_folder': clean}, f, indent=4)
	except Exception as e:
		print(f"Error saving sync settings: {e}")


def get_app_data_dir() -> str:
	sync_dir = get_sync_folder()
	if sync_dir:
		try:
			os.makedirs(sync_dir, exist_ok=True)
			if os.path.isdir(sync_dir):
				return sync_dir
		except Exception as e:
			print(f"Warning: could not access sync folder '{sync_dir}': {e}")

	return get_local_data_dir()


def get_app_state_path() -> str:
	return os.path.join(get_local_data_dir(), 'app_state.json')


def load_app_state() -> dict:
	state_path = get_app_state_path()
	default_state = {"last_file": "", "recent_files": [], "show_progress": True}
	if os.path.exists(state_path):
		try:
			with open(state_path, 'r', encoding='utf-8') as f:
				data = json.load(f)
			if isinstance(data, dict):
				last_file = data.get("last_file", "") or ""
				recent = data.get("recent_files", [])
				if not isinstance(recent, list):
					recent = []
				return {
					"last_file": last_file,
					"recent_files": recent[:MAX_RECENT_FILES],
					"show_progress": bool(data.get("show_progress", True)),
				}
		except Exception as e:
			print(f"Error loading app state: {e}")
	return default_state


def save_app_state(state: dict):
	state_path = get_app_state_path()
	try:
		payload = {
			"last_file": state.get("last_file", ""),
			"recent_files": state.get("recent_files", [])[:MAX_RECENT_FILES],
			"show_progress": bool(state.get("show_progress", True)),
		}
		with open(state_path, 'w', encoding='utf-8') as f:
			json.dump(payload, f, indent=4)
	except Exception as e:
		print(f"Error saving app state: {e}")


def get_show_progress() -> bool:
	return bool(load_app_state().get("show_progress", True))


def set_show_progress(visible: bool) -> dict:
	state = load_app_state()
	state["show_progress"] = bool(visible)
	save_app_state(state)
	return state


def record_recent_file(filepath: str) -> dict:
	norm_path = os.path.abspath(filepath)
	norm_key = os.path.normcase(norm_path)
	state = load_app_state()
	recent = [p for p in state.get("recent_files", []) if os.path.normcase(os.path.abspath(p)) != norm_key]
	recent.insert(0, norm_path)
	state["last_file"] = norm_path
	state["recent_files"] = recent[:MAX_RECENT_FILES]
	save_app_state(state)
	return state


def clear_recent_files() -> dict:
	state = load_app_state()
	state["recent_files"] = []
	save_app_state(state)
	return state