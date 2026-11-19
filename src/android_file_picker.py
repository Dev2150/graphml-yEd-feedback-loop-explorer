import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable, List, Optional, Tuple

def is_android() -> bool:
	return 'ANDROID_ARGUMENT' in os.environ


_OPEN_DOC_REQ = 41001
_SAVE_DOC_REQ = 41002


def has_all_files_access() -> bool:
	if not is_android():
		return True
	try:
		from jnius import autoclass
		BuildVersion = autoclass('android.os.Build$VERSION')
		if BuildVersion.SDK_INT < 30:
			try:
				from android.permissions import Permission, check_permission
				return bool(check_permission(Permission.READ_EXTERNAL_STORAGE))
			except Exception:
				return True
		Environment = autoclass('android.os.Environment')
		return bool(Environment.isExternalStorageManager())
	except Exception:
		return False


def request_all_files_access():
	if not is_android():
		return
	try:
		from jnius import autoclass
		PythonActivity = autoclass('org.kivy.android.PythonActivity')
		Intent = autoclass('android.content.Intent')
		Settings = autoclass('android.provider.Settings')
		Uri = autoclass('android.net.Uri')
		mActivity = PythonActivity.mActivity
		try:
			intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
			intent.setData(Uri.parse(f"package:{mActivity.getPackageName()}"))
			mActivity.startActivity(intent)
		except Exception:
			intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
			mActivity.startActivity(intent)
	except Exception as exc:
		print(f"Could not request All Files Access: {exc}")

def list_graphml_in_folder(folder_path: str) -> List[str]:
	if not folder_path or not os.path.isdir(folder_path):
		return []
	try:
		files = [
			os.path.join(folder_path, name)
			for name in os.listdir(folder_path)
			if name.lower().endswith('.graphml') and os.path.isfile(os.path.join(folder_path, name))
		]
		files.sort(key=lambda p: os.path.basename(p).lower())
		return files
	except Exception:
		return []


def open_graphml_with_system_picker(
	dest_dir: str,
	callback: Callable[[Optional[str], Optional[str]], None],
):
	"""
	Opens the Android system document picker (ACTION_OPEN_DOCUMENT).
	Copies the chosen content:// URI into `dest_dir` preserving its display name,
	then invokes callback(local_path, error_msg) on the Kivy main thread.
	"""
	if not is_android():
		_desktop_open_fallback(callback)
		return

	from android import activity
	from jnius import autoclass
	from kivy.clock import Clock

	PythonActivity = autoclass('org.kivy.android.PythonActivity')
	Intent = autoclass('android.content.Intent')
	Activity = autoclass('android.app.Activity')
	OpenableColumns = autoclass('android.provider.OpenableColumns')
	Channels = autoclass('java.nio.channels.Channels')
	ByteBuffer = autoclass('java.nio.ByteBuffer')
	FileOutputStream = autoclass('java.io.FileOutputStream')

	mActivity = PythonActivity.mActivity
	os.makedirs(dest_dir, exist_ok=True)

	def on_result(request_code, result_code, intent_data):
		if request_code != _OPEN_DOC_REQ:
			return
		activity.unbind(on_activity_result=on_result)

		if result_code != Activity.RESULT_OK or intent_data is None:
			Clock.schedule_once(lambda dt: callback(None, None), 0)
			return

		try:
			uri = intent_data.getData()
			if uri is None:
				Clock.schedule_once(lambda dt: callback(None, "No file selected."), 0)
				return

			resolver = mActivity.getContentResolver()
			display_name = "imported.graphml"
			cursor = resolver.query(uri, None, None, None, None)
			if cursor is not None:
				try:
					if cursor.moveToFirst():
						idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
						if idx >= 0:
							name = cursor.getString(idx)
							if name:
								display_name = os.path.basename(name)
				finally:
					cursor.close()

			if not display_name.lower().endswith('.graphml'):
				display_name += '.graphml'

			dest_path = os.path.join(dest_dir, display_name)
			inp = resolver.openInputStream(uri)
			if inp is None:
				Clock.schedule_once(lambda dt: callback(None, "Could not open selected file stream."), 0)
				return

			out = FileOutputStream(dest_path)
			in_channel = Channels.newChannel(inp)
			out_channel = out.getChannel()
			buf = ByteBuffer.allocateDirect(16384)
			try:
				while in_channel.read(buf) != -1:
					buf.flip()
					while buf.hasRemaining():
						out_channel.write(buf)
					buf.clear()
			finally:
				in_channel.close()
				out_channel.close()

			Clock.schedule_once(lambda dt, p=dest_path: callback(p, None), 0)
		except Exception as exc:
			err = str(exc)
			Clock.schedule_once(lambda dt, e=err: callback(None, e), 0)

	activity.bind(on_activity_result=on_result)
	intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
	intent.addCategory(Intent.CATEGORY_OPENABLE)
	intent.setType("*/*")
	mActivity.startActivityForResult(intent, _OPEN_DOC_REQ)


def export_file_with_system_picker(
	source_path: str,
	mime_type: str,
	callback: Callable[[bool, Optional[str]], None],
):
	"""Saves a generated file (.html / .graphml) using Android ACTION_CREATE_DOCUMENT."""
	if not os.path.isfile(source_path):
		callback(False, "Source file does not exist.")
		return

	if not is_android():
		callback(False, f"File saved locally at:\n{source_path}")
		return

	from android import activity
	from jnius import autoclass
	from kivy.clock import Clock

	PythonActivity = autoclass('org.kivy.android.PythonActivity')
	Intent = autoclass('android.content.Intent')
	Activity = autoclass('android.app.Activity')
	Channels = autoclass('java.nio.channels.Channels')
	ByteBuffer = autoclass('java.nio.ByteBuffer')
	FileInputStream = autoclass('java.io.FileInputStream')

	mActivity = PythonActivity.mActivity

	def on_result(request_code, result_code, intent_data):
		if request_code != _SAVE_DOC_REQ:
			return
		activity.unbind(on_activity_result=on_result)

		if result_code != Activity.RESULT_OK or intent_data is None:
			Clock.schedule_once(lambda dt: callback(False, None), 0)
			return

		try:
			uri = intent_data.getData()
			resolver = mActivity.getContentResolver()
			out = resolver.openOutputStream(uri)
			if out is None:
				Clock.schedule_once(lambda dt: callback(False, "Could not open destination file stream."), 0)
				return

			inp = FileInputStream(source_path)
			in_channel = inp.getChannel()
			out_channel = Channels.newChannel(out)
			buf = ByteBuffer.allocateDirect(16384)
			try:
				while in_channel.read(buf) != -1:
					buf.flip()
					while buf.hasRemaining():
						out_channel.write(buf)
					buf.clear()
			finally:
				in_channel.close()
				out_channel.close()

			Clock.schedule_once(lambda dt: callback(True, None), 0)
		except Exception as exc:
			err = str(exc)
			Clock.schedule_once(lambda dt, e=err: callback(False, e), 0)

	activity.bind(on_activity_result=on_result)
	intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
	intent.addCategory(Intent.CATEGORY_OPENABLE)
	intent.setType(mime_type)
	intent.putExtra(Intent.EXTRA_TITLE, os.path.basename(source_path))
	mActivity.startActivityForResult(intent, _SAVE_DOC_REQ)


import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HTML_SERVER_LOCK = threading.Lock()
_HTML_SERVER = None
_HTML_SERVER_PORT = 0
_SERVED_HTML_FILES = {}


class _LocalHtmlHandler(BaseHTTPRequestHandler):
	def _send_html(self, send_body: bool):
		req_path = urllib.parse.unquote(self.path.split('?', 1)[0]).lstrip('/')
		file_path = _SERVED_HTML_FILES.get(req_path)
		if not file_path or not os.path.isfile(file_path):
			self.send_response(404)
			self.end_headers()
			return
		with open(file_path, 'r', encoding='utf-8') as f:
			html_str = f.read().replace('charset="UTF-16"', 'charset="UTF-8"')
		data = html_str.encode('utf-8')
		self.send_response(200)
		self.send_header('Content-Type', 'text/html; charset=utf-8')
		self.send_header('Content-Length', str(len(data)))
		self.send_header('Cache-Control', 'no-store')
		self.end_headers()
		if send_body:
			self.wfile.write(data)

	def do_GET(self):
		self._send_html(True)

	def do_HEAD(self):
		self._send_html(False)

	def log_message(self, format, *args):
		pass


def _ensure_local_html_server() -> int:
	global _HTML_SERVER, _HTML_SERVER_PORT
	with _HTML_SERVER_LOCK:
		if _HTML_SERVER is None:
			server = ThreadingHTTPServer(('127.0.0.1', 0), _LocalHtmlHandler)
			server.daemon_threads = True
			_HTML_SERVER = server
			_HTML_SERVER_PORT = server.server_address[1]
			threading.Thread(target=server.serve_forever, daemon=True).start()
		return _HTML_SERVER_PORT


def open_html_viewer(html_path: str) -> Optional[str]:
	"""Opens generated HTML directly in the system browser (e.g. Firefox on Android)."""
	if not html_path or not os.path.isfile(html_path):
		return "HTML file not found."

	if not is_android():
		webbrowser.open(Path(html_path).resolve().as_uri())
		return None

	try:
		from jnius import autoclass

		port = _ensure_local_html_server()
		filename = os.path.basename(html_path)
		_SERVED_HTML_FILES[filename] = os.path.abspath(html_path)
		url = f"http://127.0.0.1:{port}/{urllib.parse.quote(filename)}"

		PythonActivity = autoclass('org.kivy.android.PythonActivity')
		Intent = autoclass('android.content.Intent')
		Uri = autoclass('android.net.Uri')

		mActivity = PythonActivity.mActivity
		intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
		intent.addCategory(Intent.CATEGORY_BROWSABLE)
		mActivity.startActivity(intent)
		return None
	except Exception as exc:
		return f"Could not open mobile browser:\n{exc}"


def _desktop_open_fallback(callback: Callable[[Optional[str], Optional[str]], None]):
	try:
		script = (
			"import tkinter as tk; from tkinter import filedialog; "
			"r = tk.Tk(); r.withdraw(); "
			"p = filedialog.askopenfilename(title='Open GraphML File', "
			"filetypes=[('GraphML files', '*.graphml'), ('All files', '*.*')]); "
			"r.destroy(); print(p or '', end='')"
		)
		res = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
		path = res.stdout.strip()
		callback(path or None, None)
	except Exception as exc:
		callback(None, str(exc))


def pick_folder_desktop(initial_dir: str = "") -> Optional[str]:
	try:
		script = (
			"import sys, tkinter as tk; from tkinter import filedialog; "
			"r = tk.Tk(); r.withdraw(); "
			"p = filedialog.askdirectory(title='Select Sync Folder', initialdir=sys.argv[1] or None); "
			"r.destroy(); print(p or '', end='')"
		)
		res = subprocess.run([sys.executable, "-c", script, initial_dir or ""], capture_output=True, text=True, check=False)
		path = res.stdout.strip()
		return path or None
	except Exception:
		return None

def request_storage_permissions(callback: Optional[Callable[[bool], None]] = None):
	if not is_android():
		if callback:
			callback(True)
		return
	try:
		from jnius import autoclass
		BuildVersion = autoclass('android.os.Build$VERSION')
		if BuildVersion.SDK_INT >= 30:
			request_all_files_access()
			if callback:
				callback(has_all_files_access())
			return

		from android.permissions import Permission, request_permissions
		from kivy.clock import Clock

		def _on_perm(_perms, results):
			if callback:
				granted = bool(results) and all(results)
				Clock.schedule_once(lambda dt: callback(granted), 0)

		request_permissions(
			[Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE],
			_on_perm,
		)
	except Exception as exc:
		print(f"Could not request storage permissions: {exc}")
		if callback:
			callback(False)


def get_external_storage_root() -> str:
	if not is_android():
		return os.path.expanduser('~')
	try:
		from jnius import autoclass
		Environment = autoclass('android.os.Environment')
		path = Environment.getExternalStorageDirectory().getAbsolutePath()
		if path and os.path.isdir(path):
			return path
	except Exception:
		pass
	if os.path.isdir('/storage/emulated/0'):
		return '/storage/emulated/0'
	return os.path.expanduser('~')


def list_directory_entries(
	folder_path: str,
	show_all_files: bool = False,
) -> Tuple[List[str], List[str], Optional[str]]:
	"""Returns (sorted_dirs, sorted_files, error_code_or_msg)."""
	if not folder_path or not os.path.isdir(folder_path):
		return [], [], f"Folder not found: {folder_path}"
	dirs: List[str] = []
	files: List[str] = []
	try:
		with os.scandir(folder_path) as entries:
			for entry in entries:
				name = entry.name
				if name.startswith('.'):
					continue
				try:
					if entry.is_dir():
						dirs.append(name)
					elif entry.is_file():
						if show_all_files or name.lower().endswith('.graphml'):
							files.append(name)
				except OSError:
					continue
		dirs.sort(key=str.lower)
		files.sort(key=str.lower)
		return dirs, files, None
	except PermissionError:
		return [], [], "permission_denied"
	except OSError as exc:
		return [], [], str(exc)