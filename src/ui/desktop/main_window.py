import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from src.app_controller import AppController
from src.config import Config, build_effective_config
from src.graph_diagram import GraphDiagramData, AnswerHighlight, find_cycle_icon_path, format_graph_node_label, \
	compute_circular_layout, compute_edge_geometry, blend_hex_with_white, compute_diagram_cycle_centers
from src.ui.desktop.graph_canvas import COLOR_GLOW_FIRST, COLOR_OUTLINE_FIRST, GLOW_STEP_FIRST, GLOW_STEP_NOT_FIRST
from src.ui.desktop.config_dialog import ConfigDialog
from src.progress_storage import get_show_progress, load_app_state, clear_recent_files, get_local_data_dir, \
	set_show_progress


class GraphMLExplorerApp(tk.Tk):
	def __init__(self, input_file: str, output_folder: str):
		super().__init__()
		self.title("GraphML Feedback Loop Explorer")
		self.geometry("1220x760")
		self.minsize(880, 540)

		self.controller = AppController(input_file, output_folder)
		self.current_diagram: GraphDiagramData = None
		self.active_highlight: AnswerHighlight = None
		self._hovered_answer_tag: str = None
		self._answer_highlights: dict = {}
		self._answer_tag_seq: int = 0
		self._icon_photo_cache: dict = {}
		self._canvas_cycle_hits: list = []
		self._hovered_icon_edges = None
		self._hovered_icon_highlight: AnswerHighlight = None
		self._synced_console_tags: list = []
		self._progress_visible: bool = get_show_progress()

		self.controller.install_console_redirect()

		self._build_menu()
		self._build_layout()
		self._bind_shortcuts()

		self.protocol("WM_DELETE_WINDOW", self._on_closing)
		self.after(40, self._poll_output_queue)
		self.after(50, self._startup)

	def _build_menu(self):
		self.menubar = tk.Menu(self)

		file_menu = tk.Menu(self.menubar, tearoff=0)
		file_menu.add_command(label="Open GraphML...", accelerator="Ctrl+O", command=self.open_file_dialog)

		self.recent_menu = tk.Menu(file_menu, tearoff=0)
		file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)

		file_menu.add_separator()
		file_menu.add_command(label="Reload Current File", accelerator="F5", command=self.reload_current_file)
		file_menu.add_command(label="Regenerate HTML & GraphML", command=self.regenerate_html)
		file_menu.add_separator()
		file_menu.add_command(label="Exit", command=self._on_closing)
		self.menubar.add_cascade(label="File", menu=file_menu)

		tools_menu = tk.Menu(self.menubar, tearoff=0)
		tools_menu.add_command(label="Open Generated HTML", accelerator="Ctrl+H", command=self.open_generated_html)
		tools_menu.add_command(label="Open HTML Output Folder", accelerator="Ctrl+Shift+O", command=self.open_html_folder)
		tools_menu.add_separator()
		tools_menu.add_command(label="Configuration...", accelerator="Ctrl+,", command=self.open_config_dialog)
		tools_menu.add_command(label="Open AppData Folder", command=self.open_appdata_folder)
		self.menubar.add_cascade(label="Tools", menu=tools_menu)

		game_menu = tk.Menu(self.menubar, tearoff=0)
		game_menu.add_command(label="Start Game", accelerator="Enter / Space", command=self.start_game)
		game_menu.add_command(label="Reveal / Next", accelerator="Enter / Space", command=self.send_reveal_next)
		game_menu.add_command(label="Stop Game (0)", command=self.send_stop_game)
		self.menubar.add_cascade(label="Game", menu=game_menu)

		self.config(menu=self.menubar)
		self._refresh_recent_menu()

	def _build_layout(self):
		toolbar = ttk.Frame(self, padding=(8, 6))
		toolbar.pack(fill=tk.X)

		self.btn_open = ttk.Button(toolbar, text="📂 Open File...", command=self.open_file_dialog, takefocus=0)
		self.btn_open.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_reload = ttk.Button(toolbar, text="🔄 Reload", command=self.reload_current_file, takefocus=0)
		self.btn_reload.pack(side=tk.LEFT, padx=(0, 12))

		self.btn_open_html = ttk.Button(toolbar, text="🌐 Open HTML", command=self.open_generated_html, state=tk.DISABLED, takefocus=0)
		self.btn_open_html.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_open_folder = ttk.Button(toolbar, text="📁 Open HTML Folder", command=self.open_html_folder, takefocus=0)
		self.btn_open_folder.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_regen = ttk.Button(toolbar, text="🔄 Regenerate HTML", command=self.regenerate_html, takefocus=0)
		self.btn_regen.pack(side=tk.LEFT, padx=(0, 6))

		ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=(4, 10))

		self.game_btn_slot = ttk.Frame(toolbar)
		self.game_btn_slot.pack(side=tk.LEFT)

		self.btn_start_game = ttk.Button(
			self.game_btn_slot,
			text="▶ Start Game (Enter/Space)",
			command=self.start_game,
			takefocus=0,
		)
		self.btn_start_game.pack(side=tk.LEFT)

		self.btn_reveal = ttk.Button(
			self.game_btn_slot,
			text="⏭ Reveal / Next (Enter/Space)",
			command=self.send_reveal_next,
			takefocus=0,
		)

		self.btn_config = ttk.Button(toolbar, text="⚙ Config", command=self.open_config_dialog, takefocus=0)
		self.btn_config.pack(side=tk.RIGHT)

		self.btn_toggle_progress = ttk.Button(
			toolbar,
			text="Hide Progress" if self._progress_visible else "Show Progress",
			command=self._toggle_progress,
			takefocus=0,
		)
		self.btn_toggle_progress.pack(side=tk.RIGHT, padx=(0, 6))

		info_bar = ttk.Frame(self, padding=(10, 2, 10, 4))
		info_bar.pack(fill=tk.X)

		self.lbl_file = ttk.Label(info_bar, text="No file loaded", font=("Segoe UI", 9, "bold"))
		self.lbl_file.pack(side=tk.LEFT)

		self.lbl_status = ttk.Label(info_bar, text="Idle", foreground="#555555")
		self.lbl_status.pack(side=tk.RIGHT)

		main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
		main_pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

		left_pane = ttk.Frame(main_pane)
		main_pane.add(left_pane, weight=3)

		self.progress_frame = ttk.LabelFrame(left_pane, text="Category Progress", padding=8)
		if self._progress_visible:
			self.progress_frame.pack(fill=tk.X, pady=(0, 6))

		tier_bar = ttk.Frame(self.progress_frame)
		tier_bar.pack(fill=tk.X, pady=(0, 6))

		self.lbl_current_tier = ttk.Label(tier_bar, text="Current tier: —", font=("Segoe UI", 9, "bold"))
		self.lbl_current_tier.pack(side=tk.LEFT)

		self.lbl_total_progress = ttk.Label(tier_bar, text="", foreground="#555555", font=("Segoe UI", 9))
		self.lbl_total_progress.pack(side=tk.RIGHT)

		table_frame = ttk.Frame(self.progress_frame)
		table_frame.pack(fill=tk.X)

		columns = ("category", "done", "total", "pct", "tier", "left")
		self.progress_tree = ttk.Treeview(
			table_frame,
			columns=columns,
			show="headings",
			selectmode="none",
			height=1,
		)
		self.progress_tree.heading("category", text="Category", anchor="w")
		self.progress_tree.heading("done", text="Done", anchor="e")
		self.progress_tree.heading("total", text="Total", anchor="e")
		self.progress_tree.heading("pct", text="%", anchor="e")
		self.progress_tree.heading("tier", text="Tier", anchor="e")
		self.progress_tree.heading("left", text="Left", anchor="e")

		self.progress_tree.column("category", anchor="w", width=115, minwidth=85, stretch=False)
		self.progress_tree.column("done", anchor="e", width=70, minwidth=50, stretch=False)
		self.progress_tree.column("total", anchor="e", width=70, minwidth=50, stretch=False)
		self.progress_tree.column("pct", anchor="e", width=60, minwidth=45, stretch=False)
		self.progress_tree.column("tier", anchor="e", width=60, minwidth=45, stretch=False)
		self.progress_tree.column("left", anchor="e", width=70, minwidth=50, stretch=False)

		self.progress_tree.pack(anchor="w")
		self.progress_tree.tag_configure("complete", foreground="#1B7A34")

		self.console_frame = ttk.Frame(left_pane)
		self.console_frame.pack(fill=tk.BOTH, expand=True)

		self.console = tk.Text(
			self.console_frame,
			wrap=tk.WORD,
			bg="#1E1F22",
			fg="#E8EAED",
			selectbackground="#2F4F7F",
			font=("Consolas", 10),
			state=tk.DISABLED,
			cursor="arrow",
			takefocus=0,
			highlightthickness=0,
			relief=tk.FLAT,
			undo=False,
			padx=10,
			pady=8,
		)
		self.console.tag_configure("arrow_up", foreground="#6BCB77")
		self.console.tag_configure("arrow_down", foreground="#FF6B6B")
		self.console.bind("<Leave>", lambda _e: self._set_hovered_answer_tag(None))

		v_scroll = ttk.Scrollbar(self.console_frame, orient=tk.VERTICAL, command=self.console.yview)
		self.console.configure(yscrollcommand=v_scroll.set)
		self.console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

		graph_panel = ttk.LabelFrame(main_pane, text="Relationship Graph", padding=6)
		main_pane.add(graph_panel, weight=2)

		self.lbl_graph_title = ttk.Label(graph_panel, text="Reveal an answer to view graph", font=("Segoe UI", 9, "bold"))
		self.lbl_graph_title.pack(anchor="w", pady=(0, 4))

		self.graph_canvas = tk.Canvas(
			graph_panel,
			bg="#FFFFFF",
			highlightthickness=1,
			highlightbackground="#CCCCCC",
		)
		self.graph_canvas.pack(fill=tk.BOTH, expand=True)
		self.graph_canvas.bind("<Configure>", lambda _e: self._redraw_graph_canvas())
		self.graph_canvas.bind("<Motion>", self._on_graph_canvas_motion)
		self.graph_canvas.bind("<Leave>", lambda _e: self._clear_hovered_cycle_icon())

	def _bind_shortcuts(self):
		self.bind("<Control-o>", lambda e: self.open_file_dialog())
		self.bind("<Control-O>", lambda e: self.open_file_dialog())
		self.bind("<Control-h>", lambda e: self.open_generated_html())
		self.bind("<Control-H>", lambda e: self.open_generated_html())
		self.bind("<Control-Shift-O>", lambda e: self.open_html_folder())
		self.bind("<Control-comma>", lambda e: self.open_config_dialog())
		self.bind("<F5>", lambda e: self.reload_current_file())
		self.bind("<Return>", self._on_key_enter_or_space)
		self.bind("<KP_Enter>", self._on_key_enter_or_space)
		self.bind("<space>", self._on_key_enter_or_space)
		self.bind("1", self._on_key_start)
		self.bind("0", self._on_key_stop)

	# ------------------------------------------------------------------
	# Startup & Recent Files Menu
	# ------------------------------------------------------------------
	def _startup(self):
		config_created, candidate_path = self.controller.initialize_startup()
		if candidate_path:
			self.load_graph_file(candidate_path)
		else:
			self._append_console_text(
				"No GraphML file found to auto-load.\n"
				"Use 'Open File...' or configure your file in Settings.\n\n"
			)
			self._update_button_states()
			if config_created or not self.controller.base_config.file_name:
				self.open_config_dialog()

	def _refresh_recent_menu(self):
		self.recent_menu.delete(0, tk.END)
		state = load_app_state()
		recent = state.get("recent_files", [])

		if not recent:
			self.recent_menu.add_command(label="(No recent files)", state=tk.DISABLED)
			return

		for idx, path in enumerate(recent[:50], start=1):
			base = os.path.basename(path)
			folder = os.path.dirname(path)
			label = f"{idx}. {base}  —  {folder}"
			self.recent_menu.add_command(
				label=label,
				command=lambda p=path: self.open_specific_file(p),
			)

		self.recent_menu.add_separator()
		self.recent_menu.add_command(label="Clear Recent List", command=self._clear_recent_list)

	def _clear_recent_list(self):
		clear_recent_files()
		self._refresh_recent_menu()

	# ------------------------------------------------------------------
	# File Opening & Loading
	# ------------------------------------------------------------------
	def open_file_dialog(self):
		cur_path = self.controller.current_graph_path
		initial_dir = (
			os.path.dirname(cur_path)
			if cur_path and os.path.isdir(os.path.dirname(cur_path))
			else (
				self.controller.base_config.folder_path
				if os.path.isdir(self.controller.base_config.folder_path)
				else os.getcwd()
			)
		)
		filepath = filedialog.askopenfilename(
			parent=self,
			title="Open GraphML File",
			initialdir=initial_dir,
			filetypes=[("GraphML files", "*.graphml"), ("All files", "*.*")],
		)
		if filepath:
			self.open_specific_file(filepath)

	def open_specific_file(self, filepath: str):
		if not os.path.isfile(filepath):
			messagebox.showerror("File Not Found", f"Could not find file:\n{filepath}", parent=self)
			return
		self.load_graph_file(filepath)

	def reload_current_file(self):
		cur = self.controller.current_graph_path
		if cur and os.path.isfile(cur):
			self.load_graph_file(cur)
		else:
			self.open_file_dialog()

	def load_graph_file(self, filepath: str, override_config: Config = None, override_local: dict = None):
		norm_path = self.controller.load_graph_file(filepath, override_config, override_local)
		self.lbl_status.configure(text="Loading & generating HTML...")
		self.lbl_file.configure(text=f"Loading: {os.path.basename(norm_path)}")
		self._update_button_states()
		self._refresh_recent_menu()
		self._append_console_text(f"\nLoading: {norm_path}\n")

	def regenerate_html(self):
		if self.controller.is_busy:
			return
		if not self.controller.ctx or not self.controller.current_graph_path:
			messagebox.showinfo("No Graph Loaded", "Please open a GraphML file first.", parent=self)
			return
		if self.controller.regenerate_html():
			self.lbl_status.configure(text="Generating HTML & GraphML...")
			self._update_button_states()

	# ------------------------------------------------------------------
	# HTML & Folder Actions
	# ------------------------------------------------------------------
	def open_generated_html(self):
		html_path = self.controller.last_html_path
		if not html_path or not os.path.isfile(html_path):
			messagebox.showinfo("No HTML Yet", "No generated HTML file was found. Load or regenerate first.", parent=self)
			return
		try:
			webbrowser.open(Path(html_path).resolve().as_uri())
		except Exception as e:
			messagebox.showerror("Open HTML Error", f"Could not open HTML file:\n{e}", parent=self)

	def open_html_folder(self):
		os.makedirs(self.controller.output_folder, exist_ok=True)
		try:
			if sys.platform.startswith("win"):
				os.startfile(self.controller.output_folder)
			elif sys.platform == "darwin":
				subprocess.Popen(["open", self.controller.output_folder])
			else:
				subprocess.Popen(["xdg-open", self.controller.output_folder])
		except Exception as e:
			messagebox.showerror("Open Folder Error", f"Could not open folder:\n{e}", parent=self)

	def open_appdata_folder(self):
		folder = get_local_data_dir()
		try:
			if sys.platform.startswith("win"):
				os.startfile(folder)
			elif sys.platform == "darwin":
				subprocess.Popen(["open", folder])
			else:
				subprocess.Popen(["xdg-open", folder])
		except Exception as e:
			messagebox.showerror("Open Folder Error", f"Could not open folder:\n{e}", parent=self)

	# ------------------------------------------------------------------
	# Configuration UI
	# ------------------------------------------------------------------
	def open_config_dialog(self):
		def on_apply(new_base: Config, new_local: dict, mode: str = "session", sync_folder: str = None):
			try:
				action, path = self.controller.apply_config(
					new_base, new_local, mode=mode, sync_folder=sync_folder
				)
			except Exception as exc:
				messagebox.showerror("Save Error", f"Could not save configuration:\n{exc}", parent=self)
				return

			if action == "reload_current" and path:
				effective = build_effective_config(self.controller.base_config, self.controller.local_overrides, path)
				self.load_graph_file(path, override_config=effective, override_local=self.controller.local_overrides)
			elif action == "load_default" and path:
				self.load_graph_file(path)

		ConfigDialog(
			self,
			self.controller.base_config,
			self.controller.local_overrides,
			self.controller.input_file,
			on_apply,
			current_graph_path=self.controller.current_graph_path,
			on_open_file_callback=self.open_specific_file,
		)

	# ------------------------------------------------------------------
	# Relationship Game Runner & Controls
	# ------------------------------------------------------------------
	def start_game(self):
		if self.controller.is_busy:
			return
		if not self.controller.ctx:
			messagebox.showinfo("No Graph Loaded", "Please open a GraphML file first.", parent=self)
			return
		if self.controller.start_game():
			self.lbl_status.configure(text="Game running")
			self._update_button_states()
			self.focus_set()

	def send_reveal_next(self):
		if self.controller.send_reveal_next():
			self._append_console_text("\n")
			self._update_button_states()
			self.focus_set()

	def send_stop_game(self):
		res = self.controller.send_stop_game()
		if res == "sent_quit":
			self._append_console_text("0\n")
			self._update_button_states()
			self.focus_set()
		elif res == "cancelled":
			self._append_console_text("\nGame stopped.\n")
			self.lbl_status.configure(text="Ready")
			self._update_button_states()

	# ------------------------------------------------------------------
	# Circular Graph Panel & Console
	# ------------------------------------------------------------------
	def _update_graph_panel(self, diagram_data: GraphDiagramData):
		self.current_diagram = diagram_data
		self._clear_hovered_cycle_icon(redraw=False)
		if self._hovered_answer_tag is not None:
			self._set_hovered_answer_tag(None)
		else:
			self.active_highlight = None
			self._redraw_graph_canvas()

	# ------------------------------------------------------------------
	# Terminal-like Console Widget Handling
	# ------------------------------------------------------------------
	def clear_console(self):
		self._clear_hovered_cycle_icon(redraw=False)
		self._set_hovered_answer_tag(None)
		self._answer_highlights.clear()
		self.console.configure(state=tk.NORMAL)
		self.console.delete("1.0", tk.END)
		self.console.configure(state=tk.DISABLED)

	def _append_console_text(self, text: str):
		self.console.configure(state=tk.NORMAL)
		start_idx = self.console.index("end-1c")
		self.console.insert("end-1c", text)
		if "↗" in text or "↘" in text:
			for ch, tag in (("↗", "arrow_up"), ("↘", "arrow_down")):
				offset = 0
				while True:
					pos = text.find(ch, offset)
					if pos == -1:
						break
					self.console.tag_add(
						tag,
						f"{start_idx} + {pos} chars",
						f"{start_idx} + {pos + 1} chars",
					)
					offset = pos + 1
		self.console.configure(state=tk.DISABLED)
		self.console.see("end-1c")

	# ------------------------------------------------------------------
	# Queue Polling & UI State
	# ------------------------------------------------------------------
	def _poll_output_queue(self):
		for kind, payload in self.controller.poll_events():
			if kind == "text":
				self._append_console_text(payload)

			elif kind == "loaded":
				ctx, _html_path, norm_path, _prepared, stats = payload
				conn_mode = ctx.config.connection_type
				self.title(f"GraphML Feedback Loop Explorer — {os.path.basename(norm_path)}")
				self.lbl_file.configure(
					text=f"{os.path.basename(norm_path)}  |  Nodes: {len(ctx.nodes)}  |  Edges: {len(ctx.edges)}  |  Mode: {conn_mode}"
				)
				self.lbl_status.configure(text="Ready")
				self._update_progress_table(stats)
				self._update_graph_panel(None)
				self._append_console_text("Press Enter, Space, or click 'Start Game' to begin.\n")
				self._update_button_states()
				self.focus_set()

			elif kind == "html_done":
				self.lbl_status.configure(text="Ready")
				self._update_button_states()

			elif kind == "load_error":
				self._update_progress_table(None)
				self._update_graph_panel(None)
				self.lbl_status.configure(text="Load Error")
				self._append_console_text(f"\nERROR: {payload}\n")
				self._update_button_states()
				messagebox.showerror(
					"Configuration / Load Error",
					f"{payload}\n\nOpening Configuration so you can adjust settings.",
					parent=self,
				)
				self.open_config_dialog()

			elif kind == "waiting_input":
				self.lbl_status.configure(text="Game: Waiting for input" if payload else "Game: Processing...")
				self._update_button_states()

			elif kind == "game_finished":
				self.lbl_status.configure(text="Ready")
				self._append_console_text("\nEnter '1' + Enter or click 'Start Game' to play again.\n")
				self._update_button_states()

			elif kind == "game_error":
				self.lbl_status.configure(text="Game Error")
				self._append_console_text(f"\nGame Error: {payload}\n")
				self._update_button_states()

			elif kind == "stats":
				self._update_progress_table(payload)

			elif kind == "graph":
				self._update_graph_panel(payload)

			elif kind == "answer_line":
				text, highlight = payload
				self._append_answer_line(text, highlight)

		self.after(40, self._poll_output_queue)

	def _update_button_states(self):
		c = self.controller
		has_ctx = c.ctx is not None
		has_html = bool(c.last_html_path and os.path.isfile(c.last_html_path))
		game_active = c.active_session is not None
		waiting = bool(game_active and c.active_session.waiting_for_input)

		self.btn_open.configure(state=tk.DISABLED if c.is_busy else tk.NORMAL)
		self.btn_reload.configure(state=tk.NORMAL if (not c.is_busy and c.current_graph_path) else tk.DISABLED)
		self.btn_open_html.configure(state=tk.NORMAL if has_html else tk.DISABLED)
		self.btn_config.configure(state=tk.DISABLED if c.is_busy else tk.NORMAL)
		self.btn_regen.configure(state=tk.NORMAL if (not c.is_busy and has_ctx) else tk.DISABLED)

		self.btn_start_game.configure(state=tk.NORMAL if (not c.is_busy and has_ctx) else tk.DISABLED)
		self.btn_reveal.configure(state=tk.NORMAL if waiting else tk.DISABLED)

		if game_active:
			if self.btn_start_game.winfo_manager():
				self.btn_start_game.pack_forget()
			if not self.btn_reveal.winfo_manager():
				self.btn_reveal.pack(side=tk.LEFT)
		else:
			if self.btn_reveal.winfo_manager():
				self.btn_reveal.pack_forget()
			if not self.btn_start_game.winfo_manager():
				self.btn_start_game.pack(side=tk.LEFT)

	def _on_closing(self):
		self.controller.cleanup()
		self.destroy()

	def _update_progress_table(self, stats: dict):
		if not stats or not stats.get("rows"):
			for item_id in self.progress_tree.get_children():
				self.progress_tree.delete(item_id)
			self.progress_tree.configure(height=1)
			self.lbl_current_tier.configure(text="Current tier: —")
			self.lbl_total_progress.configure(text="")
			return

		rows = stats["rows"]
		self.progress_tree.configure(height=max(1, len(rows)))

		current_tier = stats.get("current_tier", 0)
		total_answered = stats.get("total_answered", sum(r["answered"] for r in rows))
		total_items = stats.get("total_items", sum(r["total"] for r in rows))
		overall_pct = int(100 * total_answered / total_items) if total_items else 0

		self.lbl_current_tier.configure(text=f"Current tier: {current_tier}")
		self.lbl_total_progress.configure(text=f"{total_answered} / {total_items} ({overall_pct}%)")

		existing_ids = self.progress_tree.get_children()
		existing_cats = [self.progress_tree.item(iid, "values")[0] for iid in existing_ids]
		new_cats = [r["category"] for r in rows]

		if existing_cats == new_cats:
			for iid, r in zip(existing_ids, rows):
				tags = ("complete",) if r["left"] == 0 else ()
				self.progress_tree.item(
					iid,
					values=(r["category"], r["answered"], r["total"], f"{r['pct']}%", r["tier"], r["left"]),
					tags=tags,
				)
		else:
			for iid in existing_ids:
				self.progress_tree.delete(iid)
			for r in rows:
				tags = ("complete",) if r["left"] == 0 else ()
				self.progress_tree.insert(
					"",
					tk.END,
					values=(r["category"], r["answered"], r["total"], f"{r['pct']}%", r["tier"], r["left"]),
					tags=tags,
				)

	def _on_key_enter_or_space(self, event=None):
		if self.controller.active_session and self.controller.active_session.waiting_for_input:
			self.send_reveal_next()
			return "break"
		if not self.controller.is_busy and self.controller.ctx and self.controller.active_session is None:
			self.start_game()
			return "break"
		return None

	def _on_key_start(self, event=None):
		if not self.controller.is_busy and self.controller.ctx and self.controller.active_session is None:
			self.start_game()
			return "break"
		return None

	def _on_key_stop(self, event=None):
		if self.controller.active_session is not None:
			self.send_stop_game()
			return "break"
		return None

	# ------------------------------------------------------------------
	# Circular Graph Panel Rendering
	# ------------------------------------------------------------------

	def _load_tk_cycle_icon(self, polarity: int, target_px: int):
		icon_path = find_cycle_icon_path(polarity)
		if not icon_path:
			return None
		cache_key = (icon_path, target_px)
		if cache_key in self._icon_photo_cache:
			return self._icon_photo_cache[cache_key]
		photo = None
		try:
			from PIL import Image, ImageTk
			img = Image.open(icon_path).convert("RGBA")
			img = img.resize((target_px, target_px), Image.Resampling.LANCZOS)
			photo = ImageTk.PhotoImage(img)
		except Exception:
			try:
				raw = tk.PhotoImage(file=icon_path)
				w_img = max(raw.width(), raw.height(), 1)
				if w_img > target_px * 1.25:
					factor = max(1, round(w_img / target_px))
					photo = raw.subsample(factor, factor)
				elif w_img < target_px * 0.75:
					factor = max(1, round(target_px / w_img))
					photo = raw.zoom(factor, factor)
				else:
					photo = raw
			except Exception:
				photo = None
		self._icon_photo_cache[cache_key] = photo
		return photo

	def _redraw_graph_canvas(self):
		canvas = getattr(self, "graph_canvas", None)
		if canvas is None:
			return
		canvas.delete("all")

		self._canvas_cycle_hits = []
		default_hl = self.current_diagram.default_highlight if self.current_diagram is not None else None
		active_hl = (
			self.active_highlight
			if self.active_highlight is not None
			else (self._hovered_icon_highlight if self._hovered_icon_highlight is not None else default_hl)
		)
		diagram = active_hl.diagram if (active_hl is not None and active_hl.diagram is not None) else self.current_diagram
		if diagram is None:
			self.lbl_graph_title.configure(text="Reveal an answer to view graph")
		else:
			self.lbl_graph_title.configure(text=diagram.title)

		w = canvas.winfo_width()
		h = canvas.winfo_height()
		if w < 40 or h < 40:
			return

		if diagram is None or not diagram.nodes:
			canvas.create_text(
				w / 2.0,
				h / 2.0,
				text="Reveal an answer to generate the circular graph.",
				fill="#777777",
				font=("Segoe UI", 10),
				width=max(120, w - 32),
				justify=tk.CENTER,
			)
			return

		node_sizes = {}
		wrapped_labels = {}
		node_fonts = {}
		for node in diagram.nodes:
			wrapped = format_graph_node_label(node.label)
			wrapped_labels[node.node_id] = wrapped
			line_count = wrapped.count("\n") + 1
			node_font = ("Segoe UI", 8) if line_count > 3 else ("Segoe UI", 10)
			node_fonts[node.node_id] = node_font
			tid = canvas.create_text(0, 0, text=wrapped, font=node_font, justify=tk.CENTER)
			bbox = canvas.bbox(tid)
			canvas.delete(tid)
			tw = (bbox[2] - bbox[0]) if bbox else 60
			th = (bbox[3] - bbox[1]) if bbox else 20
			node_sizes[node.node_id] = (max(60.0, tw + 20.0), max(32.0, th + 12.0))

		rects = compute_circular_layout(diagram, float(w), float(h), node_sizes, margin=16.0, flip_y=False)
		edges_geom = compute_edge_geometry(diagram, rects, parallel_offset=7.0, target_pad=1.0)

		hl_edges = active_hl.edges if active_hl is not None else set()
		hl_nodes = active_hl.node_ids if active_hl is not None else set()

		normal_edges = []
		highlighted_edges = []
		for item in edges_geom:
			edge = item[0]
			if (edge.source_id, edge.target_id) in hl_edges:
				highlighted_edges.append(item)
			else:
				normal_edges.append(item)

		# 1. Non-highlighted edges
		for edge, x1, y1, x2, y2, _ux, _uy in normal_edges:
			canvas.create_line(
				x1, y1, x2, y2,
				fill=edge.color,
				width=1.8,
				arrow=tk.BOTH if edge.bidirectional else tk.LAST,
				arrowshape=(10, 12, 4.5),
			)

		# 2. Highlighted edge glow + crisp highlighted arrow
		for edge, x1, y1, x2, y2, ux, uy in highlighted_edges:
			gx1 = x1 + ux * 10.0 if edge.bidirectional else x1
			gy1 = y1 + uy * 10.0 if edge.bidirectional else y1
			gx2 = x2 - ux * 10.0
			gy2 = y2 - uy * 10.0
			for gw, alpha in ((12.0, 0.24), (7.0, 0.48)):
				canvas.create_line(
					gx1, gy1, gx2, gy2,
					fill=blend_hex_with_white(edge.color, alpha),
					width=gw,
					capstyle=tk.ROUND,
				)
			canvas.create_line(
				x1, y1, x2, y2,
				fill=edge.color,
				width=3.0,
				arrow=tk.BOTH if edge.bidirectional else tk.LAST,
				arrowshape=(12, 15, 5.5),
			)

		# 3. Highlighted node glow behind node boxes
		first_hl_nodes = set()
		if active_hl is not None and not active_hl.is_cycle:
			if active_hl.first_node_ids:
				first_hl_nodes.update(active_hl.first_node_ids)
			if active_hl.first_node_id:
				first_hl_nodes.add(active_hl.first_node_id)

		for node in diagram.nodes:
			if node.node_id not in hl_nodes:
				continue
			cx, cy, nw, nh = rects[node.node_id]
			is_earliest_generation = node.node_id in first_hl_nodes
			if is_earliest_generation:
				glow_base = COLOR_GLOW_FIRST
			elif node.role in ("common_source", "common_effect"):
				glow_base = node.outline_color
			else:
				glow_base = node.fill_color if node.fill_color != "#FFFFFF" else "#999999"
			glow_steps = GLOW_STEP_FIRST if is_earliest_generation else GLOW_STEP_NOT_FIRST
			for pad, alpha in glow_steps:
				canvas.create_rectangle(
					cx - (nw + pad) / 2.0,
					cy - (nh + pad) / 2.0,
					cx + (nw + pad) / 2.0,
					cy + (nh + pad) / 2.0,
					fill=blend_hex_with_white(glow_base, alpha),
					outline="",
				)

		# 4. Node boxes & labels
		for node in diagram.nodes:
			cx, cy, nw, nh = rects[node.node_id]
			is_hl = node.node_id in hl_nodes
			is_earliest_generation = node.node_id in first_hl_nodes
			if node.role == "target":
				outline_col = node.outline_color
				outline_w = 4.0
			elif node.role in ("common_source", "common_effect"):
				outline_col = node.outline_color
				outline_w = 2.8 if is_hl else 2.4
			else:
				outline_col = COLOR_OUTLINE_FIRST if is_earliest_generation else node.outline_color
				outline_w = 2.8 if is_earliest_generation else (2.2 if is_hl else 1.4)

			canvas.create_rectangle(
				cx - nw / 2.0,
				cy - nh / 2.0,
				cx + nw / 2.0,
				cy + nh / 2.0,
				fill=node.fill_color,
				outline=outline_col,
				width=outline_w,
			)
			canvas.create_text(
				cx,
				cy,
				text=wrapped_labels[node.node_id],
				fill=node.text_color,
				font=node_fonts[node.node_id],
				justify=tk.CENTER,
			)

		# 5. Feedback loop icons (always drawn for every cycle; highlighted when hovered)
		cycles_to_draw = list(getattr(diagram, "cycles", []) or [])
		if active_hl is not None and active_hl.is_cycle and active_hl.cycle_polarity in (1, -1):
			if not any(c.edges == active_hl.edges for c in cycles_to_draw):
				from src.graph_diagram import DiagramCycle
				cycles_to_draw.append(DiagramCycle(
					node_ids=list(active_hl.cycle_node_ids or active_hl.node_ids),
					edges=set(active_hl.edges),
					polarity=active_hl.cycle_polarity,
				))

		if cycles_to_draw:
			icon_sz = max(34, min(56, int(min(w, h) * 0.16)))
			centers = compute_diagram_cycle_centers(cycles_to_draw, rects, min_sep=icon_sz * 1.15)

			def _draw_cycle_icon(mid_x: float, mid_y: float, polarity: int, is_hl_cyc: bool):
				badge_col = "#1DB954" if polarity > 0 else "#E53935"
				draw_sz = int(round(icon_sz * (1.22 if is_hl_cyc else 1.0)))
				if is_hl_cyc:
					r_glow = draw_sz * 0.46
					for pad, alpha in ((18.0, 0.22), (11.0, 0.42), (5.0, 0.72)):
						canvas.create_oval(
							mid_x - r_glow - pad / 2.0,
							mid_y - r_glow - pad / 2.0,
							mid_x + r_glow + pad / 2.0,
							mid_y + r_glow + pad / 2.0,
							fill=blend_hex_with_white(badge_col, alpha),
							outline="",
						)
				photo = self._load_tk_cycle_icon(polarity, draw_sz)
				if photo is not None:
					canvas.create_image(mid_x, mid_y, image=photo)
					if is_hl_cyc:
						r_ring = draw_sz * 0.50
						canvas.create_oval(
							mid_x - r_ring, mid_y - r_ring,
							mid_x + r_ring, mid_y + r_ring,
							outline=badge_col,
							width=3.0,
						)
				else:
					r_bg = draw_sz * 0.44
					canvas.create_oval(
						mid_x - r_bg, mid_y - r_bg,
						mid_x + r_bg, mid_y + r_bg,
						fill="#FFFFFF",
						outline=badge_col,
						width=4.0 if is_hl_cyc else 2.6,
					)
					arm = r_bg * 0.56
					thick = max(3.5, r_bg * (0.28 if is_hl_cyc else 0.22))
					canvas.create_line(
						mid_x - arm, mid_y, mid_x + arm, mid_y,
						fill=badge_col, width=thick, capstyle=tk.ROUND,
					)
					if polarity > 0:
						canvas.create_line(
							mid_x, mid_y - arm, mid_x, mid_y + arm,
							fill=badge_col, width=thick, capstyle=tk.ROUND,
						)

			normal_items = []
			hl_items = []
			for idx, cyc in enumerate(cycles_to_draw):
				if idx not in centers or cyc.polarity not in (1, -1):
					continue
				is_hl_cyc = bool(
					active_hl is not None
					and active_hl.is_cycle
					and active_hl.edges == cyc.edges
				)
				if is_hl_cyc:
					hl_items.append((idx, cyc))
				else:
					normal_items.append((idx, cyc))

			for idx, cyc in normal_items:
				mx, my = centers[idx]
				_draw_cycle_icon(mx, my, cyc.polarity, False)
				self._canvas_cycle_hits.append((mx, my, max(icon_sz * 0.55, 18.0), cyc, diagram))
			for idx, cyc in hl_items:
				mx, my = centers[idx]
				_draw_cycle_icon(mx, my, cyc.polarity, True)
				self._canvas_cycle_hits.append((mx, my, max(icon_sz * 0.55, 18.0), cyc, diagram))

	def _set_hovered_answer_tag(self, tag_name: str):
		if self._hovered_answer_tag == tag_name:
			return
		prev = self._hovered_answer_tag
		if prev:
			try:
				self.console.tag_configure(prev, background="")
			except tk.TclError:
				pass
		self._hovered_answer_tag = tag_name
		if tag_name is not None:
			try:
				self.console.tag_configure(tag_name, background="#2B2E36")
			except tk.TclError:
				pass
			self.console.configure(cursor="hand2")
			self.active_highlight = self._answer_highlights.get(tag_name)
		else:
			self.console.configure(cursor="arrow")
			self.active_highlight = None
		self._redraw_graph_canvas()

	def _append_answer_line(self, text: str, highlight: AnswerHighlight):
		self.console.configure(state=tk.NORMAL)
		start_idx = self.console.index("end-1c")
		full_text = f"{text}\n"
		self.console.insert("end-1c", full_text)
		end_idx = self.console.index("end-2c")

		if "↗" in full_text or "↘" in full_text:
			for ch, tag in (("↗", "arrow_up"), ("↘", "arrow_down")):
				offset = 0
				while True:
					pos = full_text.find(ch, offset)
					if pos == -1:
						break
					self.console.tag_add(
						tag,
						f"{start_idx} + {pos} chars",
						f"{start_idx} + {pos + 1} chars",
					)
					offset = pos + 1

		if highlight is not None:
			self._answer_tag_seq += 1
			tag_name = f"ans_hl_{self._answer_tag_seq}"
			self._answer_highlights[tag_name] = highlight
			self.console.tag_add(tag_name, start_idx, end_idx)
			self.console.tag_bind(tag_name, "<Enter>", lambda _e, t=tag_name: self._set_hovered_answer_tag(t))
			self.console.tag_bind(
				tag_name,
				"<Leave>",
				lambda _e, t=tag_name: self._set_hovered_answer_tag(None) if self._hovered_answer_tag == t else None,
			)

		self.console.configure(state=tk.DISABLED)
		self.console.see("end-1c")

	def _clear_hovered_cycle_icon(self, redraw: bool = True):
		for tag_name in self._synced_console_tags:
			if tag_name != self._hovered_answer_tag:
				try:
					self.console.tag_configure(tag_name, background="")
				except tk.TclError:
					pass
		self._synced_console_tags.clear()

		changed = (self._hovered_icon_edges is not None) or (self._hovered_icon_highlight is not None)
		self._hovered_icon_edges = None
		self._hovered_icon_highlight = None
		if hasattr(self, "graph_canvas"):
			self.graph_canvas.configure(cursor="")
		if changed and redraw:
			self._redraw_graph_canvas()

	def _on_graph_canvas_motion(self, event):
		best = None
		best_d2 = float("inf")
		for mx, my, hit_r, cyc, diag in self._canvas_cycle_hits:
			d2 = (event.x - mx) ** 2 + (event.y - my) ** 2
			if d2 <= hit_r * hit_r and d2 < best_d2:
				best_d2 = d2
				best = (cyc, diag)

		if best is None:
			self._clear_hovered_cycle_icon()
			return

		cyc, diag = best
		edge_key = frozenset(cyc.edges)
		if self._hovered_icon_edges == edge_key:
			return

		self._clear_hovered_cycle_icon(redraw=False)
		self._hovered_icon_edges = edge_key
		self._hovered_icon_highlight = AnswerHighlight(
			node_ids=set(cyc.node_ids),
			edges=set(cyc.edges),
			is_cycle=True,
			cycle_polarity=cyc.polarity,
			cycle_node_ids=list(cyc.node_ids),
			diagram=diag,
		)

		for tag_name, hl in self._answer_highlights.items():
			if hl.is_cycle and frozenset(hl.edges) == edge_key:
				if hl.diagram is None or hl.diagram is diag:
					try:
						self.console.tag_configure(tag_name, background="#2B2E36")
						self._synced_console_tags.append(tag_name)
					except tk.TclError:
						pass

		self.graph_canvas.configure(cursor="hand2")
		self._redraw_graph_canvas()

	def _toggle_progress(self):
		self._progress_visible = not self._progress_visible
		set_show_progress(self._progress_visible)
		if self._progress_visible:
			self.progress_frame.pack(fill=tk.X, pady=(0, 6), before=self.console_frame)
			self.btn_toggle_progress.configure(text="Hide Progress")
		else:
			self.progress_frame.pack_forget()
			self.btn_toggle_progress.configure(text="Show Progress")
