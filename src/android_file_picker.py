import os
import webbrowser
from pathlib import Path
from typing import Callable, Optional


def is_android() -> bool:
	return 'ANDROID_ARGUMENT' in os.environ


_OPEN_DOC_REQ = 41001
_SAVE_DOC_REQ = 41002


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
	Array = autoclass('java.lang.reflect.Array')
	Byte = autoclass('java.lang.Byte')
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
			buf = Array.newInstance(Byte.TYPE, 16384)
			try:
				while True:
					n = inp.read(buf)
					if n == -1:
						break
					out.write(buf, 0, n)
			finally:
				inp.close()
				out.close()

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
	Array = autoclass('java.lang.reflect.Array')
	Byte = autoclass('java.lang.Byte')
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
			inp = FileInputStream(source_path)
			buf = Array.newInstance(Byte.TYPE, 16384)
			try:
				while True:
					n = inp.read(buf)
					if n == -1:
						break
					out.write(buf, 0, n)
			finally:
				inp.close()
				out.close()

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


def open_html_viewer(html_path: str):
	"""Displays generated HTML in an Android WebView dialog (or desktop browser)."""
	if not os.path.isfile(html_path):
		return

	if not is_android():
		webbrowser.open(Path(html_path).resolve().as_uri())
		return

	from android.runnable import run_on_ui_thread
	from jnius import autoclass

	with open(html_path, 'r', encoding='utf-8') as f:
		html_str = f.read()
	html_str = html_str.replace('charset="UTF-16"', 'charset="utf-8"')
	title = os.path.basename(html_path)

	@run_on_ui_thread
	def _show():
		PythonActivity = autoclass('org.kivy.android.PythonActivity')
		WebView = autoclass('android.webkit.WebView')
		AlertDialogBuilder = autoclass('android.app.AlertDialog$Builder')

		mActivity = PythonActivity.mActivity
		webview = WebView(mActivity)
		settings = webview.getSettings()
		settings.setBuiltInZoomControls(True)
		settings.setDisplayZoomControls(False)
		webview.loadDataWithBaseURL("file:///android_asset/", html_str, "text/html", "utf-8", None)

		builder = AlertDialogBuilder(mActivity)
		builder.setTitle(title)
		builder.setView(webview)
		builder.setPositiveButton("Close", None)
		builder.show()

	_show()


def _desktop_open_fallback(callback: Callable[[Optional[str], Optional[str]], None]):
	try:
		import tkinter as tk
		from tkinter import filedialog
		root = tk.Tk()
		root.withdraw()
		path = filedialog.askopenfilename(
			title="Open GraphML File",
			filetypes=[("GraphML files", "*.graphml"), ("All files", "*.*")],
		)
		root.destroy()
		callback(path or None, None)
	except Exception as exc:
		callback(None, str(exc))