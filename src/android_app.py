import copy
import os
import queue
import re
import shutil
import sys
import threading
from kivy.core.text import Label as CoreLabel, LabelBase
from kivy.graphics import Color, Line, Rectangle, Triangle
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

# I have to run this before `import networkx as nx` to prevent error `ModuleNotFoundError: No module named '_bz2'`
import types


def _ensure_optional_stdlib_stubs():
	try:
		import bz2  # noqa: F401
	except ImportError:
		bz2_stub = types.ModuleType('bz2')
		bz2_stub.BZ2File = type('BZ2File', (), {})
		bz2_stub.BZ2Compressor = type('BZ2Compressor', (), {})
		bz2_stub.BZ2Decompressor = type('BZ2Decompressor', (), {})
		bz2_stub.open = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('bz2 not available on Android'))
		bz2_stub.compress = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('bz2 not available on Android'))
		bz2_stub.decompress = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('bz2 not available on Android'))
		sys.modules['bz2'] = bz2_stub

	try:
		import lzma  # noqa: F401
	except ImportError:
		lzma_stub = types.ModuleType('lzma')
		lzma_stub.LZMAError = type('LZMAError', (Exception,), {})
		lzma_stub.LZMAFile = type('LZMAFile', (), {})
		lzma_stub.LZMACompressor = type('LZMACompressor', (), {})
		lzma_stub.LZMADecompressor = type('LZMADecompressor', (), {})
		lzma_stub.open = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('lzma not available on Android'))
		lzma_stub.compress = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('lzma not available on Android'))
		lzma_stub.decompress = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('lzma not available on Android'))
		sys.modules['lzma'] = lzma_stub


_ensure_optional_stdlib_stubs()

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
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput

from src.android_file_picker import (
	export_file_with_system_picker,
	open_graphml_with_system_picker,
	open_html_viewer, has_all_files_access, request_all_files_access, get_external_storage_root,
	list_directory_entries, request_storage_permissions, )
from src.config import (
	COUNTER_CONNECTION_TYPES,
	GRAPH_SETTING_KEYS,
	Config,
	build_effective_config,
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
from src.graph_diagram import (
	GraphDiagramData,
	compute_circular_layout,
	compute_edge_geometry, format_graph_node_label,
)
from src.html_exporter import generate_html_and_graphml
from src.io_graphml import list_graph_elements_and_groups, read_from_graph_xml
from src.models import GraphContext
from src.progress_storage import (
	clear_recent_files,
	load_app_state,
	load_graph_config,
	record_recent_file,
	save_graph_config, set_sync_folder, get_sync_folder,
)

ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')
MAX_CONSOLE_LINES = 250


def _hex_to_rgba(hex_color: str):
	h = hex_color.lstrip('#')
	return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0, 1.0)


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
	for candidate in ('data/fonts/DejaVuSans.ttf', 'DejaVuSans.ttf'):
		font_path = resource_find(candidate)
		if font_path and os.path.isfile(font_path):
			try:
				LabelBase.register(name='DejaVuSans', fn_regular=font_path)
				return 'DejaVuSans'
			except Exception:
				pass
	return 'Roboto'


class CircularGraphWidget(StencilView):
	def __init__(self, font_name: str = 'Roboto', **kwargs):
		super().__init__(**kwargs)
		self.font_name = font_name
		self.diagram: GraphDiagramData = None
		self.bind(pos=self._redraw, size=self._redraw)

	def set_diagram(self, diagram: GraphDiagramData):
		self.diagram = diagram
		self._redraw()

	def _build_node_texture(self, text: str, text_rgba, max_text_w: float):
		formatted = format_graph_node_label(text)
		line_count = formatted.count('\n') + 1
		if line_count > 5:
			font_sz = dp(7.5)
		elif line_count > 3:
			font_sz = dp(8.5)
		elif line_count > 1:
			font_sz = dp(10)
		else:
			font_sz = dp(11)

		lbl = CoreLabel(
			text=formatted,
			font_size=font_sz,
			font_name=self.font_name,
			color=text_rgba,
			halign='center',
		)
		lbl.refresh()
		return lbl.texture

	def _redraw(self, *_):
		self.canvas.clear()
		if self.width < 20 or self.height < 20:
			return

		ox, oy = self.x, self.y
		with self.canvas:
			Color(1, 1, 1, 1)
			Rectangle(pos=self.pos, size=self.size)

			if self.diagram is None or not self.diagram.nodes:
				lbl = CoreLabel(
					text='Reveal an answer to view graph',
					font_size=dp(12),
					font_name=self.font_name,
					color=(0.45, 0.45, 0.45, 1),
				)
				lbl.refresh()
				tex = lbl.texture
				Color(1, 1, 1, 1)
				Rectangle(
					texture=tex,
					pos=(ox + (self.width - tex.width) / 2.0, oy + (self.height - tex.height) / 2.0),
					size=tex.size,
				)
				return

			max_text_w = max(dp(55), min(dp(105), self.width * 0.28))
			textures = {}
			node_sizes = {}

			for node in self.diagram.nodes:
				tex = self._build_node_texture(node.label, _hex_to_rgba(node.text_color))
				textures[node.node_id] = tex
				node_sizes[node.node_id] = (
					max(dp(40), tex.width + dp(10)),
					max(dp(22), tex.height + dp(6)),
				)

			rects = compute_circular_layout(
				self.diagram,
				self.width,
				self.height,
				node_sizes,
				margin=dp(8),
				flip_y=True,
			)
			edges_geom = compute_edge_geometry(
				self.diagram,
				rects,
				parallel_offset=dp(6),
				target_pad=dp(1),
			)

			arrow_len = dp(8)
			arrow_hw = dp(3.5)
			for edge, x1, y1, x2, y2, ux, uy in edges_geom:
				Color(*_hex_to_rgba(edge.color))
				base_x = x2 - ux * arrow_len
				base_y = y2 - uy * arrow_len
				lx = base_x - uy * arrow_hw
				ly = base_y + ux * arrow_hw
				rx = base_x + uy * arrow_hw
				ry = base_y - ux * arrow_hw

				Line(points=[ox + x1, oy + y1, ox + base_x, oy + base_y], width=dp(1.1))
				Triangle(points=[ox + x2, oy + y2, ox + lx, oy + ly, ox + rx, oy + ry])

			for node in self.diagram.nodes:
				cx, cy, nw, nh = rects[node.node_id]
				tex = textures[node.node_id]
				bx = ox + cx - nw / 2.0
				by = oy + cy - nh / 2.0

				Color(*_hex_to_rgba(node.fill_color))
				Rectangle(pos=(bx, by), size=(nw, nh))

				Color(0, 0, 0, 1)
				Line(rectangle=(bx, by, nw, nh), width=1.05)

				Color(1, 1, 1, 1)
				Rectangle(
					texture=tex,
					pos=(ox + cx - tex.width / 2.0, oy + cy - tex.height / 2.0),
					size=tex.size,
				)


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
		self.base_config: Config = Config()
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
		self._progress_expanded_height: float = dp(164)
		self._graph_visible: bool = True
		self._graph_expanded_height: float = dp(230)
		self._open_popups: list = []
		self._last_browse_dir: str = ''
		self._on_resume_refresh = None

	def build(self):
		Window.clearcolor = (0.118, 0.122, 0.133, 1)  # #1E1F22

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

		self.console_font = _resolve_console_font()

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

		self.progress_scroll = ScrollView(size_hint_y=None, height=0)
		self.progress_grid = GridLayout(cols=5, size_hint_y=None, spacing=dp(2), padding=(dp(2), dp(2)))
		self.progress_grid.bind(minimum_height=self.progress_grid.setter('height'))
		self.progress_scroll.add_widget(self.progress_grid)
		root.add_widget(self.progress_scroll)

		# --- Collapsible Circular Graph Panel ---
		graph_bar = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(6))
		self.lbl_graph_title = Label(
			text='Graph: —',
			halign='left',
			valign='middle',
			bold=True,
			font_size=dp(12),
			color=(0.85, 0.9, 1.0, 1),
		)
		self.lbl_graph_title.bind(size=lambda inst, val: setattr(inst, 'text_size', val))

		self.btn_toggle_graph = Button(
			text='Hide Graph',
			size_hint_x=None,
			width=dp(90),
			font_size=dp(12),
			on_release=lambda *_: self._toggle_graph(),
		)
		graph_bar.add_widget(self.lbl_graph_title)
		graph_bar.add_widget(self.btn_toggle_graph)
		root.add_widget(graph_bar)

		self.graph_widget = CircularGraphWidget(
			font_name=self.console_font,
			size_hint_y=None,
			height=self._graph_expanded_height,
		)
		root.add_widget(self.graph_widget)

		# --- Scrollable Console Output ---
		self.console_scroll = ScrollView(do_scroll_x=False, bar_width=dp(6))
		self.console_box = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(2), padding=(dp(4), dp(4)))
		self.console_box.bind(minimum_height=self.console_box.setter('height'))
		self.console_scroll.add_widget(self.console_box)
		root.add_widget(self.console_scroll)

		# --- Bottom Game Controls ---
		self.bottom_bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
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

		self.bottom_bar.add_widget(self.btn_start_game)
		root.add_widget(self.bottom_bar)

		# Redirect stdout/stderr into UI queue (while still forwarding to logcat)
		self._orig_stdout = sys.stdout
		self._orig_stderr = sys.stderr
		sys.stdout = ConsoleRedirector(self.output_queue, self._orig_stdout)
		sys.stderr = ConsoleRedirector(self.output_queue, self._orig_stderr)

		# Hook Android hardware back button (and Esc on desktop)
		Window.bind(on_keyboard=self._handle_hardware_back)
		if IS_DESKTOP:
			Window.bind(on_request_close=self._on_request_close)

		self._cleaned_up = False
		self._poll_event = Clock.schedule_interval(self._poll_output_queue, 0.05)
		Clock.schedule_once(lambda dt: self._startup(), 0.1)

		if IS_DESKTOP:
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
		if self._on_resume_refresh is not None:
			Clock.schedule_once(lambda dt: self._on_resume_refresh() if self._on_resume_refresh else None, 0.25)

	def _on_request_close(self, *args):
		self._cleanup_on_exit()
		return False

	def _cleanup_on_exit(self):
		if getattr(self, '_cleaned_up', False):
			return
		self._cleaned_up = True
		if getattr(self, '_poll_event', None) is not None:
			self._poll_event.cancel()
			self._poll_event = None
		try:
			Window.unbind(on_keyboard=self._handle_hardware_back)
			if IS_DESKTOP:
				Window.unbind(on_request_close=self._on_request_close)
		except Exception:
			pass
		for p in list(self._open_popups):
			try:
				p.dismiss()
			except Exception:
				pass
		self._open_popups.clear()
		session = self.active_session
		self._cancel_active_game()
		if session is not None and session.thread is not None and session.thread.is_alive():
			session.thread.join(timeout=0.3)
		if hasattr(self, '_orig_stdout'):
			sys.stdout = self._orig_stdout
		if hasattr(self, '_orig_stderr'):
			sys.stderr = self._orig_stderr

	def on_stop(self):
		self._cleanup_on_exit()

	def handle_back_press(self) -> bool:
		if self._open_popups:
			top_popup = self._open_popups[-1]
			top_popup.dismiss()
			return True
		return False

	def _handle_hardware_back(self, window, key, *args):
		if key == 27:  # Android Back button / Desktop Escape
			return self.handle_back_press()
		if self._open_popups or self.is_busy or not self.ctx:
			return False
		if key in (13, 271, 32):  # Enter, Numpad Enter, Space
			if self.active_session and self.active_session.waiting_for_input:
				self.send_reveal_next()
				return True
			if self.active_session is None:
				self.start_game()
				return True
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

			self.base_config = read_config_file(self.input_file)
			self.config_obj = copy.deepcopy(self.base_config)
			app_state = load_app_state()
			last_file = app_state.get('last_file', '')

			candidate = ''
			if last_file and os.path.isfile(last_file):
				candidate = last_file
			else:
				cfg_path = self._resolve_graph_path_from_config(self.base_config)
				if cfg_path and os.path.isfile(cfg_path):
					candidate = os.path.abspath(cfg_path)

			if candidate:
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

	def _resolve_effective_config(self, filepath: str):
		norm_path = os.path.abspath(filepath)
		saved_dict = load_graph_config(norm_path) or {}
		local_overrides = {k: v for k, v in saved_dict.items() if k in GRAPH_SETTING_KEYS}
		return build_effective_config(self.base_config, local_overrides, norm_path), local_overrides

	# ------------------------------------------------------------------
	# File Opening, Recent & HTML Menu
	# ------------------------------------------------------------------
	def _use_system_file_picker(self):
		def on_picked(filepath, err):
			if err:
				self._show_message('Open File Error', err)
				return
			if filepath:
				self.open_specific_file(filepath)

		open_graphml_with_system_picker(self.imported_dir, on_picked)

	def open_file_dialog(self):
		if self.is_busy:
			return

		sync_dir = get_sync_folder()
		start_dir = ''
		for candidate in (
				self._last_browse_dir,
				os.path.dirname(self.current_graph_path)
				if self.current_graph_path and os.path.dirname(self.current_graph_path) != self.imported_dir
				else '',
				sync_dir,
				self.base_config.folder_path,
				get_external_storage_root(),
		):
			if candidate and os.path.isdir(candidate):
				start_dir = os.path.abspath(candidate)
				break
		if not start_dir:
			start_dir = os.getcwd()

		state = {'dir': start_dir}
		content = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))

		lbl_path = Label(
			text=state['dir'],
			size_hint_y=None,
			height=dp(32),
			halign='left',
			valign='middle',
			font_size=dp(11),
			color=(0.78, 0.85, 0.98, 1),
		)
		lbl_path.bind(size=lambda inst, sz: setattr(inst, 'text_size', sz))
		content.add_widget(lbl_path)

		nav_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
		btn_up = Button(text='Up (..)', font_size=dp(12))
		btn_storage = Button(text='Storage', font_size=dp(12))
		nav_row.add_widget(btn_up)
		nav_row.add_widget(btn_storage)
		if sync_dir and os.path.isdir(sync_dir):
			btn_sync = Button(text='Sync Folder', font_size=dp(12))
			btn_sync.bind(on_release=lambda *_: _go_to(sync_dir))
			nav_row.add_widget(btn_sync)
		content.add_widget(nav_row)

		filter_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
		ti_filter = TextInput(hint_text='Filter files...', multiline=False, font_size=dp(12))
		cb_all = CheckBox(active=False, size_hint_x=None, width=dp(34))
		lbl_all = Label(text='All files', size_hint_x=None, width=dp(58), font_size=dp(12))
		filter_row.add_widget(ti_filter)
		filter_row.add_widget(cb_all)
		filter_row.add_widget(lbl_all)
		content.add_widget(filter_row)

		sv = ScrollView(do_scroll_x=False)
		lst = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4), padding=(0, dp(2)))
		lst.bind(minimum_height=lst.setter('height'))
		sv.add_widget(lst)
		content.add_widget(sv)

		popup = Popup(title='Open GraphML File', content=content, size_hint=(0.95, 0.9))

		def _make_list_btn(label_text: str, bg_color, on_tap):
			btn = Button(
				text=label_text,
				size_hint_y=None,
				height=dp(42),
				font_size=dp(13),
				halign='left',
				valign='middle',
				shorten=True,
				shorten_from='right',
				background_color=bg_color,
				on_release=on_tap,
			)
			btn.bind(size=lambda inst, sz: setattr(inst, 'text_size', (max(0, sz[0] - dp(16)), sz[1])))
			return btn

		def _refresh_list(*_):
			lst.clear_widgets()
			lbl_path.text = state['dir']
			sv.scroll_y = 1

			dirs, files, err = list_directory_entries(state['dir'], show_all_files=cb_all.active)
			if err == 'permission_denied' or (not has_all_files_access() and not dirs and not files):
				msg = Label(
					text=(
						'Storage access is required to browse folders directly.\n'
						'Tap "Grant Storage Access" below, or use "System Picker".'
					),
					size_hint_y=None,
					height=dp(72),
					halign='center',
					valign='middle',
					font_size=dp(12),
				)
				msg.bind(size=lambda inst, sz: setattr(inst, 'text_size', sz))
				lst.add_widget(msg)
				lst.add_widget(Button(
					text='Grant Storage Access',
					size_hint_y=None,
					height=dp(44),
					background_color=(0.2, 0.5, 0.78, 1),
					on_release=lambda *_: request_storage_permissions(lambda _ok: _refresh_list()),
				))
				return

			if err:
				lst.add_widget(Label(text=err, size_hint_y=None, height=dp(44), font_size=dp(12)))
				return

			q = ti_filter.text.strip().lower()
			shown = 0
			for d in dirs:
				if q and q not in d.lower():
					continue
				full_d = os.path.join(state['dir'], d)
				lst.add_widget(_make_list_btn(f'[DIR] {d}', (0.24, 0.30, 0.38, 1), lambda _b, p=full_d: _go_to(p)))
				shown += 1

			for fname in files:
				if q and q not in fname.lower():
					continue
				full_f = os.path.join(state['dir'], fname)
				is_gml = fname.lower().endswith('.graphml')
				bg = (0.18, 0.45, 0.30, 1) if is_gml else (0.24, 0.24, 0.26, 1)

				def _on_file(_b, path=full_f, ok=is_gml):
					if not ok:
						self._show_message('Unsupported File', 'Please select a .graphml file.')
						return
					self._last_browse_dir = state['dir']
					popup.dismiss()
					self.open_specific_file(path)

				lst.add_widget(_make_list_btn(fname, bg, _on_file))
				shown += 1

			if shown == 0:
				hint = 'No matching files in this folder.'
				if not cb_all.active:
					hint += '\nCheck "All files" to view non-GraphML files.'
				empty_lbl = Label(text=hint, size_hint_y=None, height=dp(56), halign='center', font_size=dp(12))
				empty_lbl.bind(size=lambda inst, sz: setattr(inst, 'text_size', sz))
				lst.add_widget(empty_lbl)

		def _go_to(path: str):
			if path and os.path.isdir(path):
				state['dir'] = os.path.abspath(path)
				self._last_browse_dir = state['dir']
				_refresh_list()

		btn_up.bind(on_release=lambda *_: _go_to(os.path.dirname(state['dir'])))
		btn_storage.bind(on_release=lambda *_: _go_to(get_external_storage_root()))
		ti_filter.bind(text=_refresh_list)
		cb_all.bind(active=_refresh_list)

		bottom_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
		bottom_row.add_widget(Button(
			text='System Picker',
			font_size=dp(12),
			on_release=lambda *_: (popup.dismiss(), self._use_system_file_picker()),
		))
		bottom_row.add_widget(Button(text='Refresh', font_size=dp(12), on_release=_refresh_list))
		bottom_row.add_widget(Button(text='Cancel', font_size=dp(12), on_release=lambda *_: popup.dismiss()))
		content.add_widget(bottom_row)

		self._on_resume_refresh = _refresh_list
		popup.bind(on_dismiss=lambda *_: setattr(self, '_on_resume_refresh', None))
		_refresh_list()
		self._open_tracked_popup(popup)

	def open_specific_file(self, filepath: str):
		if not os.path.isfile(filepath):
			self._show_message('File Not Found', f'Could not find file:\n{filepath}')
			return
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

	def load_graph_file(self, filepath: str, override_config: Config = None, override_local: dict = None):
		self.prepared_game_data = None
		self._cancel_active_game()
		norm_path = os.path.abspath(filepath)
		self.current_graph_path = norm_path
		if override_local is not None:
			self.local_overrides = copy.deepcopy(override_local)
		else:
			saved_dict = load_graph_config(norm_path) or {}
			self.local_overrides = {k: v for k, v in saved_dict.items() if k in GRAPH_SETTING_KEYS}

		self.config_obj = (
			copy.deepcopy(override_config)
			if override_config is not None
			else build_effective_config(self.base_config, self.local_overrides, norm_path)
		)
		self.is_busy = True
		self.lbl_status.text = 'Loading...'
		self.lbl_file.text = f'Loading: {os.path.basename(norm_path)}'
		self._update_button_states()

		record_recent_file(norm_path)
		cfg_snapshot = copy.deepcopy(self.config_obj)
		self._append_console_text(f"\nLoading: {os.path.basename(norm_path)}\n")

		def worker():
			try:
				if cfg_snapshot.excluded_elements:
					print(
						f"Excluding {len(cfg_snapshot.excluded_elements)} element/group(s): "
						f"{', '.join(cfg_snapshot.excluded_elements)}"
					)

				nodes, edges, edge_values, node_values, edge_labels, node_colors = read_from_graph_xml(
					norm_path, cfg_snapshot.color_threshold, cfg_snapshot.excluded_elements
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
	# Configuration Popup & Exclusion Picker
	# ------------------------------------------------------------------
	def _open_exclusion_picker(self, ti_excluded: TextInput):
		if not self.current_graph_path or not os.path.isfile(self.current_graph_path):
			self._show_message('No Graph Loaded', 'Load a GraphML file first to pick elements or groups.')
			return

		try:
			groups, elements = list_graph_elements_and_groups(self.current_graph_path)
		except Exception as exc:
			self._show_message('Inspect Error', f'Could not read GraphML elements:\n{exc}')
			return

		all_items = [('Group', g) for g in groups] + [('Node', e) for e in elements]
		current_lower = {line.strip().lower(): line.strip() for line in ti_excluded.text.splitlines() if line.strip()}
		selected_map = {}

		content = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))
		search_ti = TextInput(hint_text='Filter groups / nodes...', multiline=False, size_hint_y=None, height=dp(38))
		content.add_widget(search_ti)

		sv = ScrollView()
		lst = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(2))
		lst.bind(minimum_height=lst.setter('height'))
		sv.add_widget(lst)
		content.add_widget(sv)

		for kind, name in all_items:
			selected_map[(kind, name)] = (name.lower() in current_lower)

		def _render_rows(*_):
			lst.clear_widgets()
			q = search_ti.text.strip().lower()
			for kind, name in all_items:
				if q and q not in name.lower() and q not in kind.lower():
					continue
				row_box = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
				cb = CheckBox(active=selected_map[(kind, name)], size_hint_x=None, width=dp(36))
				cb.bind(active=lambda _inst, val, k=(kind, name): selected_map.__setitem__(k, bool(val)))
				lbl = Label(
					text=f'[{kind}] {name}',
					halign='left',
					valign='middle',
					font_size=dp(13),
				)
				lbl.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
				row_box.add_widget(cb)
				row_box.add_widget(lbl)
				lst.add_widget(row_box)

		search_ti.bind(text=_render_rows)
		_render_rows()

		popup = Popup(title='Pick Excluded Groups / Nodes', content=content, size_hint=(0.94, 0.86))

		def _confirm(*_):
			seen = set()
			result = []
			for (kind, name), is_checked in selected_map.items():
				if is_checked and name.lower() not in seen:
					seen.add(name.lower())
					result.append(name)
			known_lower = {name.lower() for _, name in all_items}
			for low, orig in current_lower.items():
				if low not in known_lower and low not in seen:
					seen.add(low)
					result.append(orig)
			ti_excluded.text = '\n'.join(result)
			popup.dismiss()

		def _clear_all(*_):
			for k in selected_map:
				selected_map[k] = False
			_render_rows()

		btn_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
		btn_row.add_widget(Button(text='Clear All', on_release=_clear_all))
		btn_row.add_widget(Button(text='Apply Selection', on_release=_confirm))
		btn_row.add_widget(Button(text='Cancel', on_release=lambda *_: popup.dismiss()))
		content.add_widget(btn_row)
		self._open_tracked_popup(popup)

	def open_config_dialog(self):
		g_cfg = self.base_config
		loc = self.local_overrides
		has_file = bool(self.current_graph_path and os.path.isfile(self.current_graph_path))

		outer = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))
		if has_file:
			active_count = sum(1 for k in GRAPH_SETTING_KEYS if k in loc)
			status_text = f"{os.path.basename(self.current_graph_path)} ({active_count}/{len(GRAPH_SETTING_KEYS)} local)"
		else:
			status_text = 'No file loaded — Global & App Settings only'

		status_lbl = Label(
			text=status_text,
			size_hint_y=None,
			height=dp(22),
			font_size=dp(12),
			bold=True,
			color=(0.75, 0.85, 1.0, 1),
		)
		outer.add_widget(status_lbl)

		# Tab switcher: Graph Settings (Global / Local) vs App Settings
		tab_bar = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
		btn_tab_graph = Button(text='Graph (Global/Local)', font_size=dp(12), background_color=(0.24, 0.45, 0.70, 1))
		btn_tab_app = Button(text='App Settings', font_size=dp(12), background_color=(0.25, 0.27, 0.30, 1))
		tab_bar.add_widget(btn_tab_graph)
		tab_bar.add_widget(btn_tab_app)
		outer.add_widget(tab_bar)

		content_area = BoxLayout()
		outer.add_widget(content_area)

		# ------------------------------------------------------------------
		# View 1: Graph Settings (Global + Local Checkbox + Local)
		# ------------------------------------------------------------------
		graph_scroll = ScrollView()
		form = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(8), padding=dp(4))
		form.bind(minimum_height=form.setter('height'))
		graph_scroll.add_widget(form)

		global_fields = {}
		local_enabled_cbs = {}
		local_fields = {}
		local_widgets = {}

		def update_local_state(key: str):
			enabled = bool(has_file and local_enabled_cbs[key].active)
			for w in local_widgets.get(key, []):
				w.disabled = not enabled

		def add_card_header(key: str, label: str):
			hdr = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(4))
			lbl = Label(text=label, halign='left', valign='middle', bold=True, font_size=dp(12))
			lbl.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
			hdr.add_widget(lbl)

			is_local = has_file and (key in loc)
			hdr.add_widget(Label(text='Local', size_hint_x=None, width=dp(38), font_size=dp(11), color=(0.75, 0.85, 1.0, 1)))
			en_cb = CheckBox(active=is_local, disabled=not has_file, size_hint_x=None, width=dp(34))
			en_cb.bind(active=lambda _inst, _val, k=key: update_local_state(k))
			local_enabled_cbs[key] = en_cb
			hdr.add_widget(en_cb)
			return hdr, is_local

		def add_text_pair(key: str, label: str, g_val, l_raw_val=None, fmt_fn=str):
			card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(70), spacing=dp(2))
			hdr, is_local = add_card_header(key, label)
			card.add_widget(hdr)

			g_str = fmt_fn(g_val)
			l_str = fmt_fn(l_raw_val) if is_local else g_str

			row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
			g_box = BoxLayout(spacing=dp(3))
			g_box.add_widget(Label(text='G:', size_hint_x=None, width=dp(20), font_size=dp(11)))
			g_ti = TextInput(text=g_str, multiline=False, font_size=dp(12))
			g_box.add_widget(g_ti)

			l_box = BoxLayout(spacing=dp(3))
			l_box.add_widget(Label(text='L:', size_hint_x=None, width=dp(20), font_size=dp(11)))
			l_ti = TextInput(text=l_str, multiline=False, font_size=dp(12))
			l_box.add_widget(l_ti)

			row.add_widget(g_box)
			row.add_widget(l_box)
			card.add_widget(row)
			form.add_widget(card)

			global_fields[key] = g_ti
			local_fields[key] = l_ti
			local_widgets[key] = [l_ti]
			update_local_state(key)

		def add_spinner_pair(key: str, label: str, g_val: str, l_raw_val, values: tuple):
			card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(70), spacing=dp(2))
			hdr, is_local = add_card_header(key, label)
			card.add_widget(hdr)

			row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
			g_box = BoxLayout(spacing=dp(3))
			g_box.add_widget(Label(text='G:', size_hint_x=None, width=dp(20), font_size=dp(11)))
			g_sp = Spinner(text=str(g_val), values=values, font_size=dp(12))
			g_box.add_widget(g_sp)

			l_box = BoxLayout(spacing=dp(3))
			l_box.add_widget(Label(text='L:', size_hint_x=None, width=dp(20), font_size=dp(11)))
			l_sp = Spinner(text=str(l_raw_val) if is_local else str(g_val), values=values, font_size=dp(12))
			l_box.add_widget(l_sp)

			row.add_widget(g_box)
			row.add_widget(l_box)
			card.add_widget(row)
			form.add_widget(card)

			global_fields[key] = g_sp
			local_fields[key] = l_sp
			local_widgets[key] = [l_sp]
			update_local_state(key)

		def add_bool_pair(key: str, label: str, g_val: bool, l_raw_val):
			card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(66), spacing=dp(2))
			hdr, is_local = add_card_header(key, label)
			card.add_widget(hdr)

			row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
			g_box = BoxLayout(spacing=dp(4))
			g_box.add_widget(Label(text='Global:', size_hint_x=None, width=dp(50), font_size=dp(12)))
			g_cb = CheckBox(active=bool(g_val), size_hint_x=None, width=dp(36))
			g_box.add_widget(g_cb)

			l_box = BoxLayout(spacing=dp(4))
			l_box.add_widget(Label(text='Local:', size_hint_x=None, width=dp(46), font_size=dp(12)))
			l_cb = CheckBox(active=bool(l_raw_val) if is_local else bool(g_val), size_hint_x=None, width=dp(36))
			l_box.add_widget(l_cb)

			row.add_widget(g_box)
			row.add_widget(l_box)
			card.add_widget(row)
			form.add_widget(card)

			global_fields[key] = g_cb
			local_fields[key] = l_cb
			local_widgets[key] = [l_cb]
			update_local_state(key)

		add_spinner_pair('connection_type', 'Connection Type', g_cfg.connection_type, loc.get('connection_type'), ('correlation', 'counter', 'family'))
		add_bool_pair('ignore_edge_colors', 'Ignore Edge Colors', g_cfg.ignore_edge_colors, loc.get('ignore_edge_colors'))
		add_text_pair('color_threshold', 'Color Threshold', g_cfg.color_threshold, loc.get('color_threshold'))
		add_bool_pair('show_connections_list', 'Show Connections List', g_cfg.show_connections_list, loc.get('show_connections_list'))
		add_text_pair('connections_skipped', 'Connections Skipped', g_cfg.connections_skipped, loc.get('connections_skipped'))
		add_bool_pair('show_only_edges', 'Show Only Edges', g_cfg.show_only_edges, loc.get('show_only_edges'))
		add_bool_pair('show_edge_labels', 'Show Edge Labels', g_cfg.show_edge_labels, loc.get('show_edge_labels'))
		add_bool_pair('enable_non_cycle_printing', 'Non-Cycle Printing', g_cfg.enable_non_cycle_printing, loc.get('enable_non_cycle_printing'))
		add_bool_pair('sort_by_len', 'Sort Cycles by Length', g_cfg.sort_by_len, loc.get('sort_by_len'))
		add_bool_pair('sort_connections_alphabetically', 'Sort Connections Alpha', g_cfg.sort_connections_alphabetically, loc.get('sort_connections_alphabetically'))
		add_text_pair('max_cycle_length_html', 'Max Cycle Len (HTML)', g_cfg.max_cycle_length_html, loc.get('max_cycle_length_html'))
		add_text_pair('max_indirectness', 'Max Indirectness (HTML)', g_cfg.max_indirectness, loc.get('max_indirectness'))
		add_text_pair('source_node', 'Source Node', g_cfg.source_node, loc.get('source_node'))
		add_text_pair('target_node', 'Target Node', g_cfg.target_node, loc.get('target_node'))
		add_text_pair(
			'block_starting_node',
			'Block Starting Nodes',
			g_cfg.block_starting_node,
			loc.get('block_starting_node'),
			fmt_fn=lambda xs: ', '.join(xs) if isinstance(xs, list) else str(xs or ''),
		)

		# Excluded Elements / Groups (Global + Local)
		excl_card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(132), spacing=dp(2))
		excl_hdr, is_local_excl = add_card_header('excluded_elements', 'Excluded Elements / Groups (1/line)')
		excl_card.add_widget(excl_hdr)

		l_excl_list = (
			loc.get('excluded_elements')
			if (is_local_excl and isinstance(loc.get('excluded_elements'), list))
			else g_cfg.excluded_elements
		)
		excl_row = BoxLayout(size_hint_y=None, height=dp(96), spacing=dp(6))

		g_excl_box = BoxLayout(orientation='vertical', spacing=dp(2))
		g_ti_excl = TextInput(text='\n'.join(g_cfg.excluded_elements), multiline=True, font_size=dp(11))
		g_excl_box.add_widget(g_ti_excl)
		if has_file:
			g_excl_box.add_widget(Button(
				text='Pick Global...',
				size_hint_y=None,
				height=dp(26),
				font_size=dp(11),
				on_release=lambda *_: self._open_exclusion_picker(g_ti_excl),
			))

		l_excl_box = BoxLayout(orientation='vertical', spacing=dp(2))
		l_ti_excl = TextInput(text='\n'.join(l_excl_list), multiline=True, font_size=dp(11))
		l_excl_box.add_widget(l_ti_excl)
		l_excl_widgets = [l_ti_excl]
		if has_file:
			btn_l_pick = Button(
				text='Pick Local...',
				size_hint_y=None,
				height=dp(26),
				font_size=dp(11),
				on_release=lambda *_: self._open_exclusion_picker(l_ti_excl),
			)
			l_excl_box.add_widget(btn_l_pick)
			l_excl_widgets.append(btn_l_pick)

		excl_row.add_widget(g_excl_box)
		excl_row.add_widget(l_excl_box)
		excl_card.add_widget(excl_row)
		form.add_widget(excl_card)

		global_fields['excluded_elements'] = g_ti_excl
		local_fields['excluded_elements'] = l_ti_excl
		local_widgets['excluded_elements'] = l_excl_widgets
		update_local_state('excluded_elements')

		add_text_pair('chance_irrelevant', 'Chance Irrelevant', g_cfg.chance_irrelevant, loc.get('chance_irrelevant'))
		add_text_pair('max_cycle_length_game', 'Max Cycle Len (Game)', g_cfg.max_cycle_length_game, loc.get('max_cycle_length_game'))
		add_text_pair('max_indirectness_game', 'Max Indirectness (Game)', g_cfg.max_indirectness_game, loc.get('max_indirectness_game'))
		add_bool_pair('leaf_only', 'Leaf Nodes Only', g_cfg.leaf_only, loc.get('leaf_only'))

		# ------------------------------------------------------------------
		# View 2: App Settings (Separate from Graph Global / Local)
		# ------------------------------------------------------------------
		app_scroll = ScrollView()
		app_form = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(8), padding=dp(6))
		app_form.bind(minimum_height=app_form.setter('height'))
		app_scroll.add_widget(app_form)

		app_info = Label(
			text='App Settings (stored in input.txt; independent of per-file Graph Settings):',
			size_hint_y=None,
			height=dp(36),
			halign='left',
			valign='middle',
			font_size=dp(12),
			color=(0.75, 0.85, 1.0, 1),
		)
		app_info.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
		app_form.add_widget(app_info)

		app_form.add_widget(Label(text='Default Folder Path:', size_hint_y=None, height=dp(24), halign='left', font_size=dp(12)))
		ti_app_folder = TextInput(text=g_cfg.folder_path, multiline=False, size_hint_y=None, height=dp(40))
		app_form.add_widget(ti_app_folder)

		app_form.add_widget(Label(text='Default File Name / Path:', size_hint_y=None, height=dp(24), halign='left', font_size=dp(12)))
		ti_app_file = TextInput(text=g_cfg.file_name, multiline=False, size_hint_y=None, height=dp(40))
		app_form.add_widget(ti_app_file)

		app_form.add_widget(Label(
			text='Sync Folder (for Syncthing):',
			size_hint_y=None,
			height=dp(24),
			halign='left',
			font_size=dp(12),
		))
		ti_sync_folder = TextInput(
			text=get_sync_folder(),
			hint_text='/storage/emulated/0/Syncthing/GraphML',
			multiline=False,
			size_hint_y=None,
			height=dp(40),
		)
		app_form.add_widget(ti_sync_folder)


		def _show_tab(tab_name: str):
			content_area.clear_widgets()
			if tab_name == 'graph':
				content_area.add_widget(graph_scroll)
				btn_tab_graph.background_color = (0.24, 0.45, 0.70, 1)
				btn_tab_app.background_color = (0.25, 0.27, 0.30, 1)
			else:
				content_area.add_widget(app_scroll)
				btn_tab_app.background_color = (0.24, 0.45, 0.70, 1)
				btn_tab_graph.background_color = (0.25, 0.27, 0.30, 1)

		btn_tab_graph.bind(on_release=lambda *_: _show_tab('graph'))
		btn_tab_app.bind(on_release=lambda *_: _show_tab('app'))
		_show_tab('graph')

		popup_title = f'Config — {os.path.basename(self.current_graph_path)}' if has_file else 'Configuration'
		popup = Popup(title=popup_title, content=outer, size_hint=(0.96, 0.92))

		def _parse_fields(fmap: dict, scope_label: str) -> dict:
			out = {}
			out['connection_type'] = fmap['connection_type'].text.strip().lower() or 'correlation'
			out['ignore_edge_colors'] = bool(fmap['ignore_edge_colors'].active)
			try:
				out['color_threshold'] = int(fmap['color_threshold'].text.strip())
				out['connections_skipped'] = int(fmap['connections_skipped'].text.strip())
				out['max_cycle_length_html'] = int(fmap['max_cycle_length_html'].text.strip())
				out['max_indirectness'] = int(fmap['max_indirectness'].text.strip())
				out['max_cycle_length_game'] = int(fmap['max_cycle_length_game'].text.strip())
				out['max_indirectness_game'] = int(fmap['max_indirectness_game'].text.strip())
				chance = float(fmap['chance_irrelevant'].text.strip())
			except ValueError as exc:
				raise ValueError(f"[{scope_label}] Check numeric fields:\n{exc}") from exc

			if chance > 1.0:
				chance /= 100.0
			out['chance_irrelevant'] = chance
			out['show_connections_list'] = bool(fmap['show_connections_list'].active)
			out['show_only_edges'] = bool(fmap['show_only_edges'].active)
			out['show_edge_labels'] = bool(fmap['show_edge_labels'].active)
			out['enable_non_cycle_printing'] = bool(fmap['enable_non_cycle_printing'].active)
			out['sort_by_len'] = bool(fmap['sort_by_len'].active)
			out['sort_connections_alphabetically'] = bool(fmap['sort_connections_alphabetically'].active)
			out['source_node'] = fmap['source_node'].text.strip().lower()
			out['target_node'] = fmap['target_node'].text.strip().lower()
			block_raw = fmap['block_starting_node'].text.strip()
			out['block_starting_node'] = [x.strip().lower() for x in block_raw.split(',') if x.strip()]
			out['excluded_elements'] = [line.strip() for line in fmap['excluded_elements'].text.splitlines() if line.strip()]
			out['leaf_only'] = bool(fmap['leaf_only'].active)
			return out

		def _apply(mode: str):
			try:
				global_dict = _parse_fields(global_fields, 'Global')
				new_base = copy.deepcopy(self.base_config)
				new_base.folder_path = ti_app_folder.text.strip()
				new_base.file_name = ti_app_file.text.strip()
				for k, v in global_dict.items():
					setattr(new_base, k, v)

				new_local = {}
				if has_file:
					local_parsed = _parse_fields(local_fields, 'Local')
					for k in GRAPH_SETTING_KEYS:
						if local_enabled_cbs[k].active:
							new_local[k] = local_parsed[k]
			except ValueError as exc:
				self._show_message('Invalid Value', str(exc))
				return

			if mode == 'save':
				try:
					sync_path = ti_sync_folder.text.strip()
					set_sync_folder(sync_path)
					if sync_path and not IS_DESKTOP and not has_all_files_access():
						request_all_files_access()
					save_config_file(self.input_file, new_base)
					if has_file:
						save_graph_config(self.current_graph_path, new_local)
				except Exception as exc:
					self._show_message('Save Error', str(exc))
					return

			self.base_config = new_base
			self.local_overrides = new_local
			popup.dismiss()

			if has_file:
				effective = build_effective_config(self.base_config, self.local_overrides, self.current_graph_path)
				self.load_graph_file(
					self.current_graph_path,
					override_config=effective,
					override_local=self.local_overrides,
				)
			else:
				self.config_obj = copy.deepcopy(self.base_config)
				cfg_path = self._resolve_graph_path_from_config(self.base_config)
				if cfg_path and os.path.isfile(cfg_path):
					self.load_graph_file(os.path.abspath(cfg_path))

		def _clear_all_local(*_):
			for k, cb in local_enabled_cbs.items():
				cb.active = False
				update_local_state(k)

		btn_bar = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
		btn_bar.add_widget(Button(text='Apply (Session)', font_size=dp(12), on_release=lambda *_: _apply('session')))
		btn_bar.add_widget(Button(text='Save & Apply', font_size=dp(12), on_release=lambda *_: _apply('save')))
		btn_bar.add_widget(Button(text='Cancel', font_size=dp(12), on_release=lambda *_: popup.dismiss()))
		outer.add_widget(btn_bar)

		if has_file:
			btn_bar2 = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
			btn_bar2.add_widget(Button(text='Clear All Local', font_size=dp(11), on_release=_clear_all_local))
			outer.add_widget(btn_bar2)

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

		def on_graph(diagram_data: GraphDiagramData):
			self.output_queue.put(('graph', (session, diagram_data)))

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
					on_graph_update=on_graph,
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

	# ------------------------------------------------------------------
	# Console, Progress Table, Graph Panel & Queue Polling
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
			self.progress_scroll.height = self._progress_expanded_height
			self.progress_scroll.opacity = 1
			self.btn_toggle_progress.text = 'Hide Stats'
		else:
			self.progress_scroll.height = 0
			self.progress_scroll.opacity = 0
			self.btn_toggle_progress.text = 'Show Stats'

	def _toggle_graph(self):
		self._graph_visible = not self._graph_visible
		if self._graph_visible:
			self.graph_widget.height = self._graph_expanded_height
			self.graph_widget.opacity = 1
			self.btn_toggle_graph.text = 'Hide Graph'
		else:
			self.graph_widget.height = 0
			self.graph_widget.opacity = 0
			self.btn_toggle_graph.text = 'Show Graph'

	def _update_graph_panel(self, diagram_data: GraphDiagramData):
		if diagram_data is None:
			self.lbl_graph_title.text = 'Graph: —'
		else:
			self.lbl_graph_title.text = f'Graph: {diagram_data.title}'
		self.graph_widget.set_diagram(diagram_data)

	def _update_progress_table(self, stats: dict):
		self.progress_grid.clear_widgets()
		if not stats or not stats.get('rows'):
			self.lbl_current_tier.text = 'Current tier: —'
			self.lbl_total_progress.text = ''
			self._progress_expanded_height = 0
			if self._progress_visible:
				self.progress_scroll.height = 0
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

		# Header (22dp) + rows (20dp each) + spacing (2dp each) + padding (4dp) + 4dp margin
		needed_height = dp(22 + 4 + len(rows) * 22 + 4)
		self._progress_expanded_height = min(needed_height, dp(168))
		if self._progress_visible:
			self.progress_scroll.height = self._progress_expanded_height

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
					self._update_graph_panel(None)
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
					self._update_graph_panel(None)
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

				elif kind == 'graph':
					session, diagram_data = payload
					if session is self.active_session:
						self._update_graph_panel(diagram_data)

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

		self.btn_start_game.disabled = self.is_busy or not has_ctx
		self.btn_reveal.disabled = not waiting

		target_btn = self.btn_reveal if game_active else self.btn_start_game
		if target_btn.parent is not self.bottom_bar:
			self.bottom_bar.clear_widgets()
			self.bottom_bar.add_widget(target_btn)

	def _show_message(self, title: str, msg: str):
		box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(10))
		lbl = Label(text=msg, halign='left', valign='middle')
		lbl.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
		box.add_widget(lbl)
		popup = Popup(title=title, content=box, size_hint=(0.85, 0.42))
		box.add_widget(Button(text='OK', size_hint_y=None, height=dp(42), on_release=lambda *_: popup.dismiss()))
		self._open_tracked_popup(popup)


def run_android_app():
	app = GraphMLAndroidApp()
	try:
		app.run()
	finally:
		app._cleanup_on_exit()
		if IS_DESKTOP:
			try:
				sys.stdout.flush()
				sys.stderr.flush()
			except Exception:
				pass
			os._exit(0)

if __name__ == '__main__':
	run_android_app()