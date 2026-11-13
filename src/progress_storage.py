import json
import os

MAX_RECENT_FILES = 50


def get_app_data_dir() -> str:
	appdata = os.getenv('APPDATA')
	if not appdata:
		appdata = os.path.expanduser('~')

	save_dir = os.path.join(appdata, 'YAMLGuessingGame')
	os.makedirs(save_dir, exist_ok=True)
	return save_dir


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


def get_app_state_path() -> str:
	return os.path.join(get_app_data_dir(), 'app_state.json')


def load_app_state() -> dict:
	state_path = get_app_state_path()
	default_state = {"last_file": "", "recent_files": []}
	if os.path.exists(state_path):
		try:
			with open(state_path, 'r', encoding='utf-8') as f:
				data = json.load(f)
			if isinstance(data, dict):
				last_file = data.get("last_file", "") or ""
				recent = data.get("recent_files", [])
				if not isinstance(recent, list):
					recent = []
				return {"last_file": last_file, "recent_files": recent[:MAX_RECENT_FILES]}
		except Exception as e:
			print(f"Error loading app state: {e}")
	return default_state


def save_app_state(state: dict):
	state_path = get_app_state_path()
	try:
		payload = {
			"last_file": state.get("last_file", ""),
			"recent_files": state.get("recent_files", [])[:MAX_RECENT_FILES],
		}
		with open(state_path, 'w', encoding='utf-8') as f:
			json.dump(payload, f, indent=4)
	except Exception as e:
		print(f"Error saving app state: {e}")


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