import copy
import os
import queue
import re
import shutil
import sys
import threading
from kivy.core.text import LabelBase
from kivy.resources import resource_find

# Ensure project root is on sys.path when running src/android_app.py directly
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SRC_DIR)
if ROOT_DIR not in sys.path:
	sys.path.insert(0, ROOT_DIR)

from kivy.utils import platform

IS_DESKTOP = platform not in ('android', 'ios')

# Configure Galaxy A15 aspect ratio (1080x2340 -> 405x878) before importing Window
if IS_DESKTOP:
	from kivy.config import Config as KivyConfig
	KivyConfig.set('graphics', 'width', '405')
	KivyConfig.set('graphics', 'height', '878')
	KivyConfig.set('graphics', 'resizable', '1')

import networkx as nx
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from src.android_file_picker import (
	export_file_with_system_picker,
	open_graphml_with_system_picker,
	open_html_viewer,
)
from src.config import (
	COUNTER_CONNECTION_TYPES,
	Config,
	create_input_file,
	read_config_file,
	save_config_file,
)
from src.games.relationship_game import (
	GameCancelledError,
	compute_relationship_stats,
	prepare_relationship_game_data,
	run_relationship_guessing_game,
)
from src.html_exporter import generate_html_and_graphml
from src.io_graphml import read_from_graph_xml
from src.models import GraphContext
from src.progress_storage import (
	clear_recent_files,
	load_app_state,
	record_recent_file,
)

ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')
MAX_CONSOLE_LINES = 250


def _format_console_markup(text: str) -> str:
	# Escape Kivy markup characters first so [?], [V], [=], etc. render literally
	safe = text.replace('&', '&amp;').replace('[', '&bl;').replace(']', '&br;')
	# Replace emojis missing from DejaVuSans with colored ASCII badges
	safe = (
		safe.replace('🟦', '[color=#4DA6FF][B][/color]')
		.replace('🟥', '[color=#FF5C5C][R][/color]')
		.replace('💥', '[color=#FFB347]![/color]')
		.replace('⚖️', '[color=#66D9EF]=[/color]')
		.replace('⚖', '[color=#66D9EF]=[/color]')
		.replace('❤️', '[color=#FF6B6B]<3[/color]')
		.replace('↗', '[color=#6BCB77]↗[/color]')
		.replace('↘', '[color=#FF6B6B]↘[/color]')
	)
	return safe

def _resolve_console_font() -> str:
	from kivy.core.text import LabelBase
	from kivy.resources import resource_find

	for candidate in ('data/fonts/DejaVuSans.ttf', 'DejaVuSans.ttf'):
		font_path = resource_find(candidate)
		if font_path and os.path.isfile(font_path):
			try:
				LabelBase.register(name='DejaVuSans', fn_regular=font_path)
				return 'DejaVuSans'
			except Exception:
				pass
	return 'Roboto'


class ConsoleRedirector:
	encoding = 'utf-8'

	def __init__(self, msg_queue: queue.Queue, orig_stream=None):
		self.msg_queue = msg_queue
		self.orig_stream = orig_stream

	def write(self, text: str):
		if text:
			if self.orig_stream is not None:
				try:
					self.orig_stream.write(text)
				except Exception:
					pass
			clean = ANSI_ESCAPE_RE.sub('', text)
			self.msg_queue.put(('text', clean))

	def flush(self):
		if self.orig_stream is not None:
			try:
				self.orig_stream.flush()
			except Exception:
				pass

	def isatty(self) -> bool:
		return False

class GameSession:
	def __init__(self):
		self.input_queue: queue.Queue = queue.Queue()
		self.cancel_event: threading.Event = threading.Event()
		self.thread: threading.Thread = None
		self.waiting_for_input: bool = False


class GraphMLAndroidApp(App):
	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.title = 'GraphML Feedback Loop Explorer'
		self.config_obj: Config = Config()
		self.ctx: GraphContext = None
		self.current_graph_path: str = ''
		self.last_html_path: str = ''
		self.is_busy: bool = False
		self.active_session: GameSession = None
		self.prepared_game_data = None
		self.output_queue: queue.Queue = queue.Queue()
		self._pending_line_buf: str = ''
		self._progress_visible: bool = True
		self._open_popups: list = []

	def build(self):
		Window.clearcolor = (0.118, 0.122, 0.133, 1)  # #1E1F22

		# Writable storage setup
		if IS_DESKTOP:
			# Keep desktop test data isolated in project_root/output_mobile_test or user_data_dir
			data_dir = self.user_data_dir
		else:
			data_dir = self.user_data_dir

		os.makedirs(data_dir, exist_ok=True)
		os.environ['GRAPHML_EXPLORER_DATA_DIR'] = data_dir

		self.input_file = os.path.join(data_dir, 'input.txt')
		self.output_folder = os.path.join(data_dir, 'output')
		self.imported_dir = os.path.join(data_dir, 'imported_graphs')
		os.makedirs(self.output_folder, exist_ok=True)
		os.makedirs(self.imported_dir, exist_ok=True)

		# Copy bundled src/input.txt on first run if available
		bundled_input = os.path.join(SRC_DIR, 'input.txt')
		if not os.path.exists(self.input_file) and os.path.isfile(bundled_input):
			try:
				shutil.copyfile(bundled_input, self.input_file)
			except Exception:
				pass

		root = BoxLayout(orientation='vertical', padding=dp(8), spacing=dp(6))

		# --- Top Action Bar ---
		top_bar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(4))
		self.btn_open = Button(text='Open', on_release=lambda *_: self.open_file_dialog())
		self.btn_recent = Button(text='Recent', on_release=lambda *_: self.open_recent_dialog())
		self.btn_reload = Button(text='Reload', on_release=lambda *_: self.reload_current_file())
		self.btn_html = Button(text='HTML', on_release=lambda *_: self.open_html_menu(), disabled=True)
		self.btn_config = Button(text='Config', on_release=lambda *_: self.open_config_dialog())

		for b in (self.btn_open, self.btn_recent, self.btn_reload, self.btn_html, self.btn_config):
			top_bar.add_widget(b)
		root.add_widget(top_bar)

		# --- File & Status Strip ---
		info_bar = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(6))
		self.lbl_file = Label(
			text='No file loaded',
			halign='left',
			valign='middle',
			bold=True,
			font_size=dp(13),
			color=(0.91, 0.92, 0.93, 1),
		)
		self.lbl_file.bind(size=lambda inst, val: setattr(inst, 'text_size', val))

		self.lbl_status = Label(
			text='Idle',
			size_hint_x=0.35,
			halign='right',
			valign='middle',
			font_size=dp(12),
			color=(0.68, 0.7, 0.73, 1),
		)
		self.lbl_status.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
		info_bar.add_widget(self.lbl_file)
		info_bar.add_widget(self.lbl_status)
		root.add_widget(info_bar)

		# --- Category Progress Header + Collapsible Table ---
		tier_bar = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(6))
		self.lbl_current_tier = Label(
			text='Current tier: —',
			halign='left',
			valign='middle',
			bold=True,
			font_size=dp(13),
			color=(0.85, 0.9, 1.0, 1),
		)
		self.lbl_current_tier.bind(size=lambda inst, val: setattr(inst, 'text_size', val))

		self.lbl_total_progress = Label(
			text='',
			halign='right',
			valign='middle',
			font_size=dp(12),
			color=(0.7, 0.72, 0.75, 1),
		)
		self.lbl_total_progress.bind(size=lambda inst, val: setattr(inst, 'text_size', val))

		self.btn_toggle_progress = Button(
			text='Hide Stats',
			size_hint_x=None,
			width=dp(90),
			font_size=dp(12),
			on_release=lambda *_: self._toggle_progress(),
		)
		tier_bar.add_widget(self.lbl_current_tier)
		tier_bar.add_widget(self.lbl_total_progress)
		tier_bar.add_widget(self.btn_toggle_progress)
		root.add_widget(tier_bar)

		self.progress_scroll = ScrollView(size_hint_y=None, height=dp(115))
		self.progress_grid = GridLayout(cols=5, size_hint_y=None, spacing=dp(2), padding=(dp(2), dp(2)))
		self.progress_grid.bind(minimum_height=self.progress_grid.setter('height'))
		self.progress_scroll.add_widget(self.progress_grid)
		root.add_widget(self.progress_scroll)

		# --- Scrollable Console Output ---
		self.console_scroll = ScrollView(do_scroll_x=False, bar_width=dp(6))
		self.console_box = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(2), padding=(dp(4), dp(4)))
		self.console_box.bind(minimum_height=self.console_box.setter('height'))
		self.console_scroll.add_widget(self.console_box)
		root.add_widget(self.console_scroll)

		# --- Bottom Game Controls ---
		bottom_bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
		self.btn_start_game = Button(
			text='Start Game',
			background_color=(0.18, 0.52, 0.32, 1),
			on_release=lambda *_: self.start_game(),
		)
		self.btn_reveal = Button(
			text='Next / Reveal',
			background_color=(0.2, 0.45, 0.72, 1),
			on_release=lambda *_: self.send_reveal_next(),
			disabled=True,
		)
		self.btn_stop_game = Button(
			text='Stop (0)',
			background_color=(0.68, 0.24, 0.24, 1),
			on_release=lambda *_: self.send_stop_game(),
			disabled=True,
		)
		self.btn_clear = Button(
			text='Clear',
			size_hint_x=0.65,
			on_release=lambda *_: self.clear_console(),
		)

		bottom_bar.add_widget(self.btn_start_game)
		bottom_bar.add_widget(self.btn_reveal)
		bottom_bar.add_widget(self.btn_stop_game)
		bottom_bar.add_widget(self.btn_clear)
		root.add_widget(bottom_bar)

		self.console_font = _resolve_console_font()

		# Redirect stdout/stderr into UI queue (while still forwarding to logcat)
		self._orig_stdout = sys.stdout
		self._orig_stderr = sys.stderr
		sys.stdout = ConsoleRedirector(self.output_queue, self._orig_stdout)
		sys.stderr = ConsoleRedirector(self.output_queue, self._orig_stderr)

		# Hook Android hardware back button (and Esc on desktop)
		Window.bind(on_keyboard=self._handle_hardware_back)

		Clock.schedule_interval(self._poll_output_queue, 0.05)
		Clock.schedule_once(lambda dt: self._startup(), 0.1)

		if IS_DESKTOP:
			# Lightweight Galaxy A15 simulator wrapper for desktop testing
			sim_wrapper = BoxLayout(orientation='vertical')
			sim_wrapper.add_widget(root)
			nav_bar = BoxLayout(size_hint_y=None, height=dp(36), padding=(dp(8), dp(2)), spacing=dp(8))
			nav_bar.add_widget(Button(
				text='◀ Back (HW)',
				size_hint_x=0.38,
				font_size=dp(12),
				background_color=(0.22, 0.23, 0.26, 1),
				on_release=lambda *_: self.handle_back_press(),
			))
			nav_bar.add_widget(Label(
				text='Galaxy A15 Preview (405×878)',
				font_size=dp(11),
				color=(0.6, 0.62, 0.65, 1),
			))
			sim_wrapper.add_widget(nav_bar)
			return sim_wrapper

		return root

	# ------------------------------------------------------------------
	# Android Lifecycle & Hardware Back Button
	# ------------------------------------------------------------------
	def on_pause(self):
		"""
		Returning True prevents Android from tearing down the OpenGL ES context
		or killing the process when ACTION_OPEN_DOCUMENT / backgrounding occurs.
		"""
		return True

	def on_resume(self):
		"""Force redraw to clear any stale black EGL buffer on resume."""
		def _force_redraw(dt):
			Window.canvas.ask_update()
			if hasattr(Window, 'update_viewport'):
				Window.update_viewport()

		Clock.schedule_once(_force_redraw, 0.05)
		Clock.schedule_once(_force_redraw, 0.2)

	def on_stop(self):
		self._cancel_active_game()
		sys.stdout = self._orig_stdout
		sys.stderr = self._orig_stderr

	def handle_back_press(self) -> bool:
		if self._open_popups:
			top_popup = self._open_popups[-1]
			top_popup.dismiss()
			return True
		return False

	def _handle_hardware_back(self, window, key, *args):
		if key == 27:  # Android Back button / Desktop Escape
			return self.handle_back_press()
		return False

	def _open_tracked_popup(self, popup: Popup):
		self._open_popups.append(popup)

		def _on_dismiss(*_):
			if popup in self._open_popups:
				self._open_popups.remove(popup)

		popup.bind(on_dismiss=_on_dismiss)
		popup.open()

	# ------------------------------------------------------------------
	# Startup & Path Resolution
	# ------------------------------------------------------------------

	def _startup(self):
		try:
			if not os.path.exists(self.input_file):
				create_input_file(self.input_file)

			self.config_obj = read_config_file(self.input_file)
			app_state = load_app_state()
			last_file = app_state.get('last_file', '')

			candidate = ''
			if last_file and os.path.isfile(last_file):
				candidate = last_file
			else:
				cfg_path = self._resolve_graph_path_from_config(self.config_obj)
				if cfg_path and os.path.isfile(cfg_path):
					candidate = os.path.abspath(cfg_path)

			if candidate:
				cfg_path = self._resolve_graph_path_from_config(self.config_obj)
				same_as_cfg = (
					cfg_path
					and os.path.normcase(os.path.abspath(cfg_path)) == os.path.normcase(os.path.abspath(candidate))
				)
				if not same_as_cfg:
					self.config_obj.folder_path = os.path.dirname(candidate) + os.sep
					self.config_obj.file_name = os.path.basename(candidate)
				self.load_graph_file(candidate)
			else:
				self._append_console_text(
					'No GraphML file loaded yet.\n'
					'Tap "Open" to select a .graphml file.\n'
				)
				self._update_button_states()
		except Exception:
			import traceback
			self._append_console_text(f'\nStartup Error:\n{traceback.format_exc()}\n')
			self._update_button_states()

	def _resolve_graph_path_from_config(self, cfg: Config) -> str:
		if not cfg.file_name:
			return ''
		if '/' in cfg.file_name or '\\' in cfg.file_name or os.path.isabs(cfg.file_name):
			return cfg.file_name if cfg.file_name.endswith('.graphml') else cfg.file_name + '.graphml'
		return os.path.join(cfg.folder_path, cfg.file_name + ('' if cfg.file_name.endswith('.graphml') else '.graphml'))

	# ------------------------------------------------------------------
	# File Opening, Recent & HTML Menu
	# ------------------------------------------------------------------
	def open_file_dialog(self):
		if self.is_busy:
			return

		def on_picked(filepath, err):
			if err:
				self._show_message('Open File Error', err)
				return
			if filepath:
				self.open_specific_file(filepath)

		open_graphml_with_system_picker(self.imported_dir, on_picked)

	def open_specific_file(self, filepath: str):
		if not os.path.isfile(filepath):
			self._show_message('File Not Found', f'Could not find file:\n{filepath}')
			return
		self.config_obj.folder_path = os.path.dirname(os.path.abspath(filepath)) + os.sep
		self.config_obj.file_name = os.path.basename(filepath)
		self.load_graph_file(filepath)

	def reload_current_file(self):
		if self.current_graph_path and os.path.isfile(self.current_graph_path):
			self.load_graph_file(self.current_graph_path)
		else:
			self.open_file_dialog()

	def open_recent_dialog(self):
		state = load_app_state()
		recent = [p for p in state.get('recent_files', []) if os.path.isfile(p)]

		content = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
		scroll = ScrollView()
		lst = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(6))
		lst.bind(minimum_height=lst.setter('height'))

		popup = Popup(title='Recent GraphML Files', content=content, size_hint=(0.92, 0.78))

		if not recent:
			lst.add_widget(Label(text='No recent files found.', size_hint_y=None, height=dp(40)))
		else:
			for p in recent[:50]:
				btn = Button(
					text=os.path.basename(p),
					size_hint_y=None,
					height=dp(44),
					on_release=lambda _b, path=p: (popup.dismiss(), self.open_specific_file(path)),
				)
				lst.add_widget(btn)

		scroll.add_widget(lst)
		content.add_widget(scroll)

		btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
		btn_row.add_widget(Button(
			text='Clear Recent',
			on_release=lambda *_: (clear_recent_files(), popup.dismiss()),
		))
		btn_row.add_widget(Button(text='Close', on_release=lambda *_: popup.dismiss()))
		content.add_widget(btn_row)
		self._open_tracked_popup(popup)

	def open_html_menu(self):
		content = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(10))
		popup = Popup(title='HTML & GraphML Output', content=content, size_hint=(0.88, 0.52))

		def _export(src_path: str, mime: str):
			popup.dismiss()
			export_file_with_system_picker(
				src_path,
				mime,
				lambda ok, err: self._show_message(
					'Export',
					'File exported successfully.' if ok else (err or 'Export cancelled.'),
				) if (ok or err) else None,
			)

		content.add_widget(Button(
			text='View Generated HTML',
			on_release=lambda *_: (popup.dismiss(), open_html_viewer(self.last_html_path)),
		))
		content.add_widget(Button(
			text='Regenerate HTML & GraphML',
			on_release=lambda *_: (popup.dismiss(), self.regenerate_html()),
		))
		content.add_widget(Button(
			text='Export HTML File...',
			on_release=lambda *_: _export(self.last_html_path, 'text/html'),
		))
		out_graphml = os.path.join(self.output_folder, 'output.graphml')
		content.add_widget(Button(
			text='Export Filtered output.graphml...',
			on_release=lambda *_: _export(out_graphml, 'application/xml'),
		))
		content.add_widget(Button(text='Close', on_release=lambda *_: popup.dismiss()))
		self._open_tracked_popup(popup)

	# ------------------------------------------------------------------
	# Graph Loading & HTML Generation
	# ------------------------------------------------------------------
	def _cancel_active_game(self):
		if self.active_session is not None:
			self.active_session.cancel_event.set()
			self.active_session.input_queue.put(None)
			self.active_session.waiting_for_input = False
			self.active_session = None

	def load_graph_file(self, filepath: str):
		self.prepared_game_data = None
		self._cancel_active_game()
		norm_path = os.path.abspath(filepath)
		self.current_graph_path = norm_path
		self.is_busy = True
		self.lbl_status.text = 'Loading...'
		self.lbl_file.text = f'Loading: {os.path.basename(norm_path)}'
		self._update_button_states()

		record_recent_file(norm_path)
		cfg_snapshot = copy.deepcopy(self.config_obj)
		self._append_console_text(f"\n{'=' * 40}\nLoading: {os.path.basename(norm_path)}\n{'=' * 40}\n")

		def worker():
			try:
				nodes, edges, edge_values, node_values, edge_labels, node_colors = read_from_graph_xml(
					norm_path, cfg_snapshot.color_threshold
				)

				if cfg_snapshot.ignore_edge_colors or cfg_snapshot.connection_type in COUNTER_CONNECTION_TYPES:
					edge_values = {k: 1 for k in edge_values}
					node_values = {k: 0 for k in node_values}
					print('Note: edge colors ignored — all edge values set to +1.')

				g = nx.DiGraph()
				g.add_nodes_from(nodes.keys())
				g.add_edges_from(edges)

				src_id = (
					next((nid for nid, label in nodes.items() if label.lower() == cfg_snapshot.source_node), None)
					if cfg_snapshot.source_node
					else None
				)
				tgt_id = (
					next((nid for nid, label in nodes.items() if label.lower() == cfg_snapshot.target_node), None)
					if cfg_snapshot.target_node
					else None
				)

				if cfg_snapshot.source_node and not src_id:
					raise ValueError(f"Could not find source node '{cfg_snapshot.source_node}' in this graph.")
				if cfg_snapshot.target_node and not tgt_id:
					raise ValueError(f"Could not find target node '{cfg_snapshot.target_node}' in this graph.")

				ctx = GraphContext(
					graph=g,
					nodes=nodes,
					node_values=node_values,
					edges=edges,
					edge_values=edge_values,
					config=cfg_snapshot,
					source_node_id=src_id,
					target_node_id=tgt_id,
					edge_labels=edge_labels,
					node_colors=node_colors,
				)

				html_path = generate_html_and_graphml(ctx, self.output_folder, norm_path)
				prepared = prepare_relationship_game_data(ctx)
				stats = compute_relationship_stats(ctx, prepared)
				self.output_queue.put(('loaded', (ctx, html_path, norm_path, prepared, stats)))
			except Exception as exc:
				self.output_queue.put(('load_error', str(exc)))

		threading.Thread(target=worker, daemon=True).start()

	def regenerate_html(self):
		if self.is_busy or not self.ctx or not self.current_graph_path:
			return
		self._cancel_active_game()
		self.is_busy = True
		self.lbl_status.text = 'Generating HTML...'
		self._update_button_states()

		ctx_ref = self.ctx
		ctx_ref.nodes_printed.clear()
		graph_path = self.current_graph_path

		def worker():
			try:
				html_path = generate_html_and_graphml(ctx_ref, self.output_folder, graph_path)
				self.output_queue.put(('html_done', html_path))
			except Exception as exc:
				self.output_queue.put(('load_error', str(exc)))

		threading.Thread(target=worker, daemon=True).start()

	# ------------------------------------------------------------------
	# Configuration Popup
	# ------------------------------------------------------------------
	def open_config_dialog(self):
		cfg = self.config_obj
		outer = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
		scroll = ScrollView()
		form = GridLayout(cols=2, size_hint_y=None, spacing=dp(6), padding=dp(4))
		form.bind(minimum_height=form.setter('height'))

		fields = {}

		def add_text(key: str, label: str, val: str):
			lbl = Label(text=label, size_hint_y=None, height=dp(40), halign='left', valign='middle', font_size=dp(13))
			lbl.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
			ti = TextInput(text=str(val), multiline=False, size_hint_y=None, height=dp(40))
			fields[key] = ti
			form.add_widget(lbl)
			form.add_widget(ti)

		def add_spinner(key: str, label: str, val: str, values: tuple):
			lbl = Label(text=label, size_hint_y=None, height=dp(40), halign='left', valign='middle', font_size=dp(13))
			lbl.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
			sp = Spinner(text=str(val), values=values, size_hint_y=None, height=dp(40))
			fields[key] = sp
			form.add_widget(lbl)
			form.add_widget(sp)

		def add_bool(key: str, label: str, val: bool):
			lbl = Label(text=label, size_hint_y=None, height=dp(36), halign='left', valign='middle', font_size=dp(13))
			lbl.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
			cb = CheckBox(active=bool(val), size_hint_y=None, height=dp(36))
			fields[key] = cb
			form.add_widget(lbl)
			form.add_widget(cb)

		add_spinner('connection_type', 'Connection Type', cfg.connection_type, ('correlation', 'counter', 'family'))
		add_bool('ignore_edge_colors', 'Ignore Edge Colors', cfg.ignore_edge_colors)
		add_text('color_threshold', 'Color Threshold', str(cfg.color_threshold))
		add_bool('show_connections_list', 'Show Connections List', cfg.show_connections_list)
		add_text('connections_skipped', 'Connections Skipped', str(cfg.connections_skipped))
		add_bool('show_only_edges', 'Show Only Edges', cfg.show_only_edges)
		add_bool('show_edge_labels', 'Show Edge Labels', cfg.show_edge_labels)
		add_bool('enable_non_cycle_printing', 'Non-Cycle Printing', cfg.enable_non_cycle_printing)
		add_bool('sort_by_len', 'Sort Cycles by Length', cfg.sort_by_len)
		add_bool('sort_connections_alphabetically', 'Sort Connections Alpha', cfg.sort_connections_alphabetically)
		add_text('max_cycle_length_html', 'Max Cycle Len (HTML)', str(cfg.max_cycle_length_html))
		add_text('max_indirectness', 'Max Indirectness (HTML)', str(cfg.max_indirectness))
		add_text('source_node', 'Source Node', cfg.source_node)
		add_text('target_node', 'Target Node', cfg.target_node)
		add_text('block_starting_node', 'Block Starting Nodes', ', '.join(cfg.block_starting_node))
		add_text('chance_irrelevant', 'Chance Irrelevant', str(cfg.chance_irrelevant))
		add_text('max_cycle_length_game', 'Max Cycle Len (Game)', str(cfg.max_cycle_length_game))
		add_text('max_indirectness_game', 'Max Indirectness (Game)', str(cfg.max_indirectness_game))
		add_bool('leaf_only', 'Leaf Nodes Only', cfg.leaf_only)

		scroll.add_widget(form)
		outer.add_widget(scroll)

		popup = Popup(title='Configuration', content=outer, size_hint=(0.94, 0.88))

		def _apply(save_disk: bool):
			try:
				new_cfg = copy.deepcopy(self.config_obj)
				new_cfg.connection_type = fields['connection_type'].text.strip().lower() or 'correlation'
				new_cfg.ignore_edge_colors = bool(fields['ignore_edge_colors'].active) or (
					new_cfg.connection_type in COUNTER_CONNECTION_TYPES
				)
				new_cfg.color_threshold = int(fields['color_threshold'].text.strip())
				new_cfg.show_connections_list = bool(fields['show_connections_list'].active)
				new_cfg.connections_skipped = int(fields['connections_skipped'].text.strip())
				new_cfg.show_only_edges = bool(fields['show_only_edges'].active)
				new_cfg.show_edge_labels = bool(fields['show_edge_labels'].active)
				new_cfg.enable_non_cycle_printing = bool(fields['enable_non_cycle_printing'].active)
				new_cfg.sort_by_len = bool(fields['sort_by_len'].active)
				new_cfg.sort_connections_alphabetically = bool(fields['sort_connections_alphabetically'].active)
				new_cfg.max_cycle_length_html = int(fields['max_cycle_length_html'].text.strip())
				new_cfg.max_indirectness = int(fields['max_indirectness'].text.strip())
				new_cfg.source_node = fields['source_node'].text.strip().lower()
				new_cfg.target_node = fields['target_node'].text.strip().lower()
				block_raw = fields['block_starting_node'].text.strip()
				new_cfg.block_starting_node = [x.strip().lower() for x in block_raw.split(',') if x.strip()]
				chance = float(fields['chance_irrelevant'].text.strip())
				if chance > 1.0:
					chance /= 100.0
				new_cfg.chance_irrelevant = chance
				new_cfg.max_cycle_length_game = int(fields['max_cycle_length_game'].text.strip())
				new_cfg.max_indirectness_game = int(fields['max_indirectness_game'].text.strip())
				new_cfg.leaf_only = bool(fields['leaf_only'].active)
			except ValueError as exc:
				self._show_message('Invalid Value', f'Check numeric fields:\n{exc}')
				return

			if save_disk:
				try:
					save_config_file(self.input_file, new_cfg)
				except Exception as exc:
					self._show_message('Save Error', str(exc))
					return

			self.config_obj = new_cfg
			popup.dismiss()
			if self.current_graph_path and os.path.isfile(self.current_graph_path):
				self.load_graph_file(self.current_graph_path)

		btn_bar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
		btn_bar.add_widget(Button(text='Apply', on_release=lambda *_: _apply(False)))
		btn_bar.add_widget(Button(text='Save & Apply', on_release=lambda *_: _apply(True)))
		btn_bar.add_widget(Button(text='Cancel', on_release=lambda *_: popup.dismiss()))
		outer.add_widget(btn_bar)
		self._open_tracked_popup(popup)

	# ------------------------------------------------------------------
	# Relationship Game Controls
	# ------------------------------------------------------------------
	def start_game(self):
		if self.is_busy:
			return
		if not self.ctx:
			self._show_message('No Graph Loaded', 'Tap "Open" to load a GraphML file first.')
			return

		self._cancel_active_game()
		session = GameSession()
		self.active_session = session
		self.lbl_status.text = 'Game running'
		self._update_button_states()

		ctx_ref = self.ctx
		prepared_ref = self.prepared_game_data

		def on_stats(stats_dict: dict):
			self.output_queue.put(('stats', (session, stats_dict)))

		def gui_input() -> str:
			if session.cancel_event.is_set():
				raise GameCancelledError()
			self.output_queue.put(('waiting_input', (session, True)))
			while True:
				if session.cancel_event.is_set():
					raise GameCancelledError()
				try:
					val = session.input_queue.get(timeout=0.1)
					if val is None or session.cancel_event.is_set():
						raise GameCancelledError()
					self.output_queue.put(('waiting_input', (session, False)))
					return val
				except queue.Empty:
					continue

		def game_worker():
			try:
				run_relationship_guessing_game(
					ctx_ref,
					input_fn=gui_input,
					exit_on_finish=False,
					on_stats_update=on_stats,
					prepared_data=prepared_ref,
				)
				self.output_queue.put(('game_finished', session))
			except GameCancelledError:
				pass
			except Exception as exc:
				self.output_queue.put(('game_error', (session, str(exc))))

		session.thread = threading.Thread(target=game_worker, daemon=True)
		session.thread.start()

	def send_reveal_next(self):
		if self.active_session and self.active_session.waiting_for_input:
			self._append_console_text('\n')
			self.active_session.waiting_for_input = False
			self.active_session.input_queue.put('')
			self._update_button_states()

	def send_stop_game(self):
		if self.active_session and self.active_session.waiting_for_input:
			self._append_console_text('0\n')
			self.active_session.waiting_for_input = False
			self.active_session.input_queue.put('0')
			self._update_button_states()
		elif self.active_session:
			self._cancel_active_game()
			self._append_console_text('\nGame stopped.\n')
			self.lbl_status.text = 'Ready'
			self._update_button_states()

	# ------------------------------------------------------------------
	# Console, Progress Table & Queue Polling
	# ------------------------------------------------------------------
	def clear_console(self):
		self._pending_line_buf = ''
		self.console_box.clear_widgets()

	def _append_console_text(self, text: str):
		self._pending_line_buf += text
		if '\n' in self._pending_line_buf:
			lines = self._pending_line_buf.split('\n')
			self._pending_line_buf = lines.pop()
			for line in lines:
				self._add_console_line(line)
		elif len(self._pending_line_buf) > 0:
			# Update or create trailing line for prompts ending without newline (e.g. "Question 1: ... ")
			self._flush_partial_line()

	def _flush_partial_line(self):
		if not self._pending_line_buf:
			return
		line = self._pending_line_buf
		self._pending_line_buf = ''
		self._add_console_line(line)

	def _add_console_line(self, line: str):
		lbl = Label(
			text=_format_console_markup(line if line else ' '),
			markup=True,
			font_name=getattr(self, 'console_font', 'Roboto'),
			font_size=dp(13),
			color=(0.91, 0.92, 0.93, 1),
			size_hint_y=None,
			halign='left',
			valign='top',
		)
		lbl.bind(width=lambda inst, w: setattr(inst, 'text_size', (w, None)))
		lbl.bind(texture_size=lambda inst, ts: setattr(inst, 'height', max(dp(18), ts[1] + dp(2))))
		self.console_box.add_widget(lbl)

		while len(self.console_box.children) > MAX_CONSOLE_LINES:
			self.console_box.remove_widget(self.console_box.children[-1])

		Clock.schedule_once(lambda dt: setattr(self.console_scroll, 'scroll_y', 0), 0.02)

	def _toggle_progress(self):
		self._progress_visible = not self._progress_visible
		if self._progress_visible:
			self.progress_scroll.height = dp(115)
			self.progress_scroll.opacity = 1
			self.btn_toggle_progress.text = 'Hide Stats'
		else:
			self.progress_scroll.height = 0
			self.progress_scroll.opacity = 0
			self.btn_toggle_progress.text = 'Show Stats'

	def _update_progress_table(self, stats: dict):
		self.progress_grid.clear_widgets()
		if not stats or not stats.get('rows'):
			self.lbl_current_tier.text = 'Current tier: —'
			self.lbl_total_progress.text = ''
			return

		rows = stats['rows']
		current_tier = stats.get('current_tier', 0)
		total_answered = sum(r['answered'] for r in rows)
		total_items = sum(r['total'] for r in rows)
		overall_pct = int(100 * total_answered / total_items) if total_items else 0

		self.lbl_current_tier.text = f'Current tier: {current_tier}'
		self.lbl_total_progress.text = f'{total_answered} / {total_items} ({overall_pct}%)'

		for hdr in ('Category', 'Done', '%', 'Tier', 'Left'):
			self.progress_grid.add_widget(Label(
				text=hdr,
				bold=True,
				size_hint_y=None,
				height=dp(22),
				font_size=dp(12),
				color=(0.75, 0.78, 0.85, 1),
			))

		for r in rows:
			col = (0.4, 0.88, 0.52, 1) if r['left'] == 0 else (0.9, 0.91, 0.93, 1)
			vals = (
				r['category'],
				f"{r['answered']}/{r['total']}",
				f"{r['pct']}%",
				str(r['tier']),
				str(r['left']),
			)
			for v in vals:
				self.progress_grid.add_widget(Label(
					text=v,
					size_hint_y=None,
					height=dp(20),
					font_size=dp(12),
					color=col,
				))

	def _poll_output_queue(self, dt):
		try:
			while True:
				kind, payload = self.output_queue.get_nowait()

				if kind == 'text':
					self._append_console_text(payload)

				elif kind == 'loaded':
					ctx, html_path, norm_path, prepared, stats = payload
					self.ctx = ctx
					self.prepared_game_data = prepared
					self.last_html_path = html_path or ''
					self.is_busy = False
					conn_mode = ctx.config.connection_type
					self.lbl_file.text = f"{os.path.basename(norm_path)} ({len(ctx.nodes)}N / {len(ctx.edges)}E | {conn_mode})"
					self.lbl_status.text = 'Ready'
					self._update_progress_table(stats)
					self._append_console_text('Ready! Tap "Start Game" to begin.\n')
					self._update_button_states()

				elif kind == 'html_done':
					self.last_html_path = payload or self.last_html_path
					self.is_busy = False
					self.lbl_status.text = 'Ready'
					self._update_button_states()

				elif kind == 'load_error':
					self.is_busy = False
					self.prepared_game_data = None
					self._update_progress_table(None)
					self.lbl_status.text = 'Load Error'
					self._append_console_text(f'\nERROR: {payload}\n')
					self._update_button_states()
					self._show_message('Load Error', payload)

				elif kind == 'waiting_input':
					session, is_waiting = payload
					if session is self.active_session:
						session.waiting_for_input = is_waiting
						self.lbl_status.text = 'Waiting for input' if is_waiting else 'Processing...'
						self._update_button_states()

				elif kind == 'game_finished':
					session = payload
					if session is self.active_session:
						self.active_session = None
						self.lbl_status.text = 'Ready'
						self._append_console_text('\nTap "Start Game" to play again.\n')
						self._update_button_states()

				elif kind == 'game_error':
					session, err_msg = payload
					if session is self.active_session:
						self.active_session = None
						self.lbl_status.text = 'Game Error'
						self._append_console_text(f'\nGame Error: {err_msg}\n')
						self._update_button_states()

				elif kind == 'stats':
					session, stats_dict = payload
					if session is self.active_session:
						self._update_progress_table(stats_dict)

		except queue.Empty:
			pass

	def _update_button_states(self):
		has_ctx = self.ctx is not None
		has_html = bool(self.last_html_path and os.path.isfile(self.last_html_path))
		game_active = self.active_session is not None
		waiting = bool(game_active and self.active_session.waiting_for_input)

		self.btn_open.disabled = self.is_busy
		self.btn_recent.disabled = self.is_busy
		self.btn_reload.disabled = self.is_busy or not self.current_graph_path
		self.btn_html.disabled = not has_html
		self.btn_config.disabled = self.is_busy

		self.btn_start_game.text = 'Restart' if game_active else 'Start Game'
		self.btn_start_game.disabled = self.is_busy or not has_ctx
		self.btn_reveal.disabled = not waiting
		self.btn_stop_game.disabled = not game_active

	def _show_message(self, title: str, msg: str):
		box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(10))
		lbl = Label(text=msg, halign='left', valign='middle')
		lbl.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
		box.add_widget(lbl)
		popup = Popup(title=title, content=box, size_hint=(0.85, 0.42))
		box.add_widget(Button(text='OK', size_hint_y=None, height=dp(42), on_release=lambda *_: popup.dismiss()))
		self._open_tracked_popup(popup)

def run_android_app():
	GraphMLAndroidApp().run()


if __name__ == '__main__':
	run_android_app()