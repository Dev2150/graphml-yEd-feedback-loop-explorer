import json
import os


def get_save_file_path(file_name: str) -> str:
	appdata = os.getenv('APPDATA')
	if not appdata:
		appdata = os.path.expanduser('~')

	save_dir = os.path.join(appdata, 'YAMLGuessingGame')
	os.makedirs(save_dir, exist_ok=True)

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