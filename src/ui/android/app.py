import os
import shutil
import sys

from src.ui.android.graph_widget import CircularGraphWidget
# Must run before importing Window or networkx (via AppController)
from src.ui.android.platform_setup import IS_DESKTOP, resolve_console_font

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from src.android_file_picker import open_graphml_with_system_picker, open_html_viewer
from src.app_controller import AppController
from src.config import Config
from src.diagram import AnswerHighlight, GraphDiagramData
from src.storage import get_show_progress, set_show_progress
from src.ui.android.config_popup import open_config_popup
from src.ui.android.console_widget import AndroidConsole
from src.ui.android.file_browser_popup import (
	open_file_browser_popup,
	open_folder_picker_popup,
	open_recent_files_popup,
)

SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class GraphMLAndroidApp(App):
	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.title = 'GraphML Feedback Loop Explorer'
		self.controller: AppController = None
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
		self._progress_visible = get_show_progress()

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

		self.controller = AppController(self.input_file, self.output_folder)
		self.console_font = resolve_console_font()

		root = BoxLayout(orientation='vertical', padding=dp(8), spacing=dp(6))

		# --- Top Action Bar ---
		top_bar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(4))
		self.btn_open = Button(text='Open', on_release=lambda *_: self.open_file_dialog())
		self.btn_recent = Button(text='Recent', on_release=lambda *_: self.open_recent_dialog())
		self.btn_reload = Button(text='Reload', on_release=lambda *_: self.reload_current_file())
		self.btn_html = Button(text='HTML', on_release=lambda *_: self.open_generated_html(), disabled=True)
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
			text='Hide Stats' if self._progress_visible else 'Show Stats',
			size_hint_x=None,
			width=dp(90),
			font_size=dp(12),
			on_release=lambda *_: self._toggle_progress(),
		)
		tier_bar.add_widget(self.lbl_current_tier)
		tier_bar.add_widget(self.lbl_total_progress)
		tier_bar.add_widget(self.btn_toggle_progress)
		root.add_widget(tier_bar)

		self.progress_scroll = ScrollView(
			size_hint_y=None,
			height=0,
			opacity=1 if self._progress_visible else 0,
		)
		self.progress_grid = GridLayout(cols=5, size_hint_y=None, spacing=dp(2), padding=(dp(2), dp(2)))
		self.progress_grid.bind(minimum_height=self.progress_grid.setter('height'))
		self.progress_scroll.add_widget(self.progress_grid)
		root.add_widget(self.progress_scroll)

		# --- Collapsible Circular Graph Panel ---
		graph_bar = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(6))
		self.lbl_graph_title = Label(
			text='Graph: —',
			font_name=self.console_font,
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
		self.console = AndroidConsole(
			font_name=self.console_font,
			on_answer_selected=self._on_answer_selected,
		)
		root.add_widget(self.console)

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

		self.controller.install_console_redirect()

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
		if self.controller is not None:
			self.controller.cleanup(join_timeout=0.3)

	def on_stop(self):
		self._cleanup_on_exit()

	def handle_back_press(self) -> bool:
		if self._open_popups:
			top_popup = self._open_popups[-1]
			top_popup.dismiss()
			return True
		return False

	def _handle_hardware_back(self, window, key, *args):
		if key == 27:
			return self.handle_back_press()
		if self._open_popups or self.controller.is_busy or not self.controller.ctx:
			return False
		if key in (13, 271, 32):
			if self.controller.active_session and self.controller.active_session.waiting_for_input:
				self.send_reveal_next()
				return True
			if self.controller.active_session is None:
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
	# Startup
	# ------------------------------------------------------------------
	def _startup(self):
		try:
			_created, candidate = self.controller.initialize_startup()
			if candidate:
				self.load_graph_file(candidate)
			else:
				self.console.append_text(
					'No GraphML file loaded yet.\n'
					'Tap "Open" to select a .graphml file.\n'
				)
				self._update_button_states()
		except Exception:
			import traceback
			self.console.append_text(f'\nStartup Error:\n{traceback.format_exc()}\n')
			self._update_button_states()

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
		if self.controller.is_busy:
			return
		open_file_browser_popup(
			graphml_dir=self.controller.base_config.folder_path.strip(),
			current_graph_path=self.controller.current_graph_path,
			imported_dir=self.imported_dir,
			last_browse_dir=self._last_browse_dir,
			on_browse_dir_changed=lambda d: setattr(self, '_last_browse_dir', d),
			on_file_selected=self.open_specific_file,
			on_use_system_picker=self._use_system_file_picker,
			on_show_message=self._show_message,
			on_track_popup=self._open_tracked_popup,
			on_set_resume_refresh=lambda fn: setattr(self, '_on_resume_refresh', fn),
		)

	def open_specific_file(self, filepath: str):
		if not os.path.isfile(filepath):
			self._show_message('File Not Found', f'Could not find file:\n{filepath}')
			return
		self.load_graph_file(filepath)

	def reload_current_file(self):
		cur = self.controller.current_graph_path
		if cur and os.path.isfile(cur):
			self.load_graph_file(cur)
		else:
			self.open_file_dialog()

	def open_recent_dialog(self):
		open_recent_files_popup(
			on_file_selected=self.open_specific_file,
			on_track_popup=self._open_tracked_popup,
		)

	def open_generated_html(self):
		html_path = self.controller.last_html_path
		if not html_path or not os.path.isfile(html_path):
			self._show_message('No HTML Yet', 'Load or reload a GraphML file first.')
			return
		err = open_html_viewer(html_path)
		if err:
			self._show_message('Open HTML Error', err)

	def _open_folder_picker(self, title: str, initial_dir: str, on_selected):
		open_folder_picker_popup(
			title=title,
			initial_dir=initial_dir,
			on_selected=on_selected,
			on_track_popup=self._open_tracked_popup,
			on_set_resume_refresh=lambda fn: setattr(self, '_on_resume_refresh', fn),
		)

	# ------------------------------------------------------------------
	# Graph Loading & HTML Generation
	# ------------------------------------------------------------------
	def load_graph_file(self, filepath: str, override_config: Config = None, override_local: dict = None):
		self.console.clear_selection()
		norm_path = self.controller.load_graph_file(filepath, override_config, override_local)
		self.lbl_status.text = 'Loading...'
		self.lbl_file.text = f'Loading: {os.path.basename(norm_path)}'
		self._update_button_states()
		self.console.append_text(f"\nLoading: {os.path.basename(norm_path)}\n")

	def regenerate_html(self):
		if self.controller.regenerate_html():
			self.lbl_status.text = 'Generating HTML...'
			self._update_button_states()

	# ------------------------------------------------------------------
	# Configuration Popup
	# ------------------------------------------------------------------
	def open_config_dialog(self):
		open_config_popup(
			controller=self.controller,
			is_desktop=IS_DESKTOP,
			on_open_folder_picker=self._open_folder_picker,
			on_show_message=self._show_message,
			on_track_popup=self._open_tracked_popup,
			on_load_graph=self.load_graph_file,
		)

	# ------------------------------------------------------------------
	# Relationship Game Controls
	# ------------------------------------------------------------------
	def start_game(self):
		if self.controller.is_busy:
			return
		if not self.controller.ctx:
			self._show_message('No Graph Loaded', 'Tap "Open" to load a GraphML file first.')
			return
		if self.controller.start_game():
			self.lbl_status.text = 'Game running'
			self._update_button_states()

	def send_reveal_next(self):
		if self.controller.send_reveal_next():
			self.console.append_text('\n')
			self._update_button_states()

	# ------------------------------------------------------------------
	# Console, Progress Table, Graph Panel & Queue Polling
	# ------------------------------------------------------------------
	def clear_console(self):
		self.console.clear()

	def _on_answer_selected(self, highlight: AnswerHighlight):
		if highlight is not None and not self._graph_visible:
			self._toggle_graph()
		self.graph_widget.set_highlight(highlight)
		d = highlight.diagram if (highlight and highlight.diagram) else self.graph_widget.diagram
		self.lbl_graph_title.text = f'Graph: {d.title}' if d else 'Graph: —'

	def _toggle_progress(self):
		self._progress_visible = not self._progress_visible
		set_show_progress(self._progress_visible)
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
			Clock.schedule_once(lambda _dt: self.graph_widget._redraw(), 0)
		else:
			self.graph_widget.height = 0
			self.graph_widget.opacity = 0
			self.btn_toggle_graph.text = 'Show Graph'

	def _update_graph_panel(self, diagram_data: GraphDiagramData):
		self.console.clear_selection()
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
		total_answered = stats.get('total_answered', sum(r['answered'] for r in rows))
		total_items = stats.get('total_items', sum(r['total'] for r in rows))
		overall_pct = int(100 * total_answered / total_items) if total_items else 0

		self.lbl_current_tier.text = f'Current tier: {current_tier}'
		self.lbl_total_progress.text = f'{total_answered} / {total_items} ({overall_pct}%)'

		for idx, hdr in enumerate(('Category', 'Done', '%', 'Tier', 'Left')):
			kw = {'size_hint_x': None, 'width': dp(98), 'halign': 'left', 'text_size': (dp(94), None)} if idx == 0 else {}
			self.progress_grid.add_widget(Label(
				text=hdr,
				bold=True,
				size_hint_y=None,
				height=dp(22),
				font_size=dp(12),
				color=(0.75, 0.78, 0.85, 1),
				**kw,
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
			for idx, v in enumerate(vals):
				kw = {'size_hint_x': None, 'width': dp(98), 'halign': 'left', 'text_size': (dp(94), None)} if idx == 0 else {}
				self.progress_grid.add_widget(Label(
					text=v,
					size_hint_y=None,
					height=dp(20),
					font_size=dp(12),
					color=col,
					**kw,
				))

		# Header (22dp) + rows (20dp each) + spacing (2dp each) + padding (4dp) + 4dp margin
		needed_height = dp(22 + 4 + len(rows) * 22 + 4)
		self._progress_expanded_height = min(needed_height, dp(168))
		if self._progress_visible:
			self.progress_scroll.height = self._progress_expanded_height

	def _poll_output_queue(self, dt):
		for kind, payload in self.controller.poll_events():
			if kind == 'text':
				self.console.append_text(payload)

			elif kind == 'answer_line':
				text, highlight = payload
				self.console.add_answer_line(text, highlight)

			elif kind == 'loaded':
				ctx, _html_path, norm_path, _prepared, stats = payload
				conn_mode = ctx.config.connection_type
				self.lbl_file.text = f"{os.path.basename(norm_path)} ({len(ctx.nodes)}N / {len(ctx.edges)}E | {conn_mode})"
				self.lbl_status.text = 'Ready'
				self._update_progress_table(stats)
				self._update_graph_panel(None)
				self.console.append_text('Ready! Tap "Start Game" to begin.\n')
				self._update_button_states()

			elif kind == 'html_done':
				self.lbl_status.text = 'Ready'
				self._update_button_states()

			elif kind == 'load_error':
				self._update_progress_table(None)
				self._update_graph_panel(None)
				self.lbl_status.text = 'Load Error'
				self.console.append_text(f'\nERROR: {payload}\n')
				self._update_button_states()
				self._show_message('Load Error', payload)

			elif kind == 'waiting_input':
				self.lbl_status.text = 'Waiting for input' if payload else 'Processing...'
				self._update_button_states()

			elif kind == 'game_finished':
				self.lbl_status.text = 'Ready'
				self.console.append_text('\nTap "Start Game" to play again.\n')
				self._update_button_states()

			elif kind == 'game_error':
				self.lbl_status.text = 'Game Error'
				self.console.append_text(f'\nGame Error: {payload}\n')
				self._update_button_states()

			elif kind == 'stats':
				self._update_progress_table(payload)

			elif kind == 'graph':
				self._update_graph_panel(payload)

	def _update_button_states(self):
		c = self.controller
		has_ctx = c.ctx is not None
		has_html = bool(c.last_html_path and os.path.isfile(c.last_html_path))
		game_active = c.active_session is not None
		waiting = bool(game_active and c.active_session.waiting_for_input)

		self.btn_open.disabled = c.is_busy
		self.btn_recent.disabled = c.is_busy
		self.btn_reload.disabled = c.is_busy or not c.current_graph_path
		self.btn_html.disabled = not has_html
		self.btn_config.disabled = c.is_busy

		self.btn_start_game.disabled = c.is_busy or not has_ctx
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