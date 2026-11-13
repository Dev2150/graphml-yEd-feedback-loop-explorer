import copy
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import networkx as nx

from src.config import (
	Config,
	COUNTER_CONNECTION_TYPES,
	create_input_file,
	read_config_file,
	save_config_file,
)
from src.games.relationship_game import GameCancelledError, run_relationship_guessing_game, \
	prepare_relationship_game_data, compute_relationship_stats
from src.html_exporter import generate_html_and_graphml
from src.io_graphml import read_from_graph_xml
from src.models import GraphContext
from src.progress_storage import (
	clear_recent_files,
	load_app_state,
	record_recent_file,
)

ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')


def run_gui(input_file: str, output_folder: str):
	app = GraphMLExplorerApp(input_file, output_folder)
	app.mainloop()

class ConsoleRedirector:
	def __init__(self, msg_queue: queue.Queue):
		self.msg_queue = msg_queue

	def write(self, text: str):
		if text:
			clean = ANSI_ESCAPE_RE.sub('', text)
			self.msg_queue.put(("text", clean))

	def flush(self):
		pass

	def isatty(self) -> bool:
		return False


class GameSession:
	def __init__(self):
		self.input_queue: queue.Queue = queue.Queue()
		self.cancel_event: threading.Event = threading.Event()
		self.thread: threading.Thread = None
		self.waiting_for_input: bool = False


class ConfigDialog(tk.Toplevel):
	"""Configuration UI dialog — shown only when clicked or when configuration is needed."""

	def __init__(self, parent, config: Config, input_file: str, on_apply_callback):
		super().__init__(parent)
		self.title("Configuration")
		self.transient(parent)
		self.grab_set()
		self.resizable(True, True)
		self.geometry("600x850")
		self.minsize(480, 420)

		self.parent_app = parent
		self.orig_config = config
		self.input_file = input_file
		self.on_apply_callback = on_apply_callback

		self._build_ui(config)
		self.protocol("WM_DELETE_WINDOW", self.destroy)

	def _build_ui(self, cfg: Config):
		container = ttk.Frame(self, padding=10)
		container.pack(fill=tk.BOTH, expand=True)

		# Scrollable form area
		canvas = tk.Canvas(container, highlightthickness=0)
		scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
		form_frame = ttk.Frame(canvas, padding=(4, 4, 12, 4))

		form_frame.bind(
			"<Configure>",
			lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
		)
		canvas_window = canvas.create_window((0, 0), window=form_frame, anchor="nw")
		canvas.configure(yscrollcommand=scrollbar.set)
		canvas.bind(
			"<Configure>",
			lambda e: canvas.itemconfigure(canvas_window, width=e.width)
		)

		def _on_mousewheel(event):
			if event.delta:
				canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
			elif event.num == 4:
				canvas.yview_scroll(-3, "units")
			elif event.num == 5:
				canvas.yview_scroll(3, "units")

		self.bind("<MouseWheel>", _on_mousewheel)
		self.bind("<Button-4>", _on_mousewheel)
		self.bind("<Button-5>", _on_mousewheel)

		canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

		self.vars = {}
		row = 0

		def add_section(title: str):
			nonlocal row
			if row > 0:
				ttk.Separator(form_frame, orient=tk.HORIZONTAL).grid(
					row=row, column=0, columnspan=3, sticky="ew", pady=(10, 4)
				)
				row += 1
			lbl = ttk.Label(form_frame, text=title, font=("Segoe UI", 10, "bold"))
			lbl.grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 6))
			row += 1

		def add_entry(key: str, label: str, value: str, browse_file: bool = False):
			nonlocal row
			ttk.Label(form_frame, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
			var = tk.StringVar(value=str(value))
			self.vars[key] = var
			entry = ttk.Entry(form_frame, textvariable=var)
			entry.grid(row=row, column=1, sticky="ew", pady=3)
			if browse_file:
				ttk.Button(form_frame, text="Browse...", command=self._browse_graphml).grid(
					row=row, column=2, padx=(6, 0), pady=3
				)
			row += 1

		def add_combo(key: str, label: str, value: str, options: list):
			nonlocal row
			ttk.Label(form_frame, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
			var = tk.StringVar(value=str(value))
			self.vars[key] = var
			combo = ttk.Combobox(form_frame, textvariable=var, values=options, state="normal")
			combo.grid(row=row, column=1, sticky="ew", pady=3)
			row += 1

		def add_check(key: str, label: str, value: bool):
			nonlocal row
			var = tk.BooleanVar(value=bool(value))
			self.vars[key] = var
			chk = ttk.Checkbutton(form_frame, text=label, variable=var)
			chk.grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
			row += 1

		form_frame.columnconfigure(1, weight=1)

		add_section("1. Graph File & Connection Mode")
		add_entry("folder_path", "Folder Path:", cfg.folder_path)
		add_entry("file_name", "File Name / Path:", cfg.file_name, browse_file=True)
		add_combo("connection_type", "Connection Type:", cfg.connection_type, ["correlation", "counter", "family"])
		add_check("ignore_edge_colors", "Ignore Edge Colors (all edges = +1)", cfg.ignore_edge_colors)
		add_entry("color_threshold", "Color Threshold:", cfg.color_threshold)

		add_section("2. HTML & GraphML Output")
		add_check("show_connections_list", "Show Connections List (instead of full paths)", cfg.show_connections_list)
		add_entry("connections_skipped", "Connections Skipped (intermediate nodes):", cfg.connections_skipped)
		add_check("show_only_edges", "Show Only Edges", cfg.show_only_edges)
		add_check("show_edge_labels", "Show Edge Labels", cfg.show_edge_labels)
		add_check("enable_non_cycle_printing", "Enable Non-Cycle Path Printing", cfg.enable_non_cycle_printing)
		add_check("sort_by_len", "Sort Cycles by Length -> Alphabetical", cfg.sort_by_len)
		add_check("sort_connections_alphabetically", "Sort Connections Alphabetically", cfg.sort_connections_alphabetically)
		add_entry("max_cycle_length_html", "Max Cycle Length (HTML):", cfg.max_cycle_length_html)
		add_entry("max_indirectness", "Max Indirectness (HTML):", cfg.max_indirectness)

		add_section("3. Node Filters")
		add_entry("source_node", "Source Node (blank = all):", cfg.source_node)
		add_entry("target_node", "Target Node (blank = all):", cfg.target_node)
		add_entry("block_starting_node", "Block Starting Nodes (comma-sep):", ", ".join(cfg.block_starting_node))

		add_section("4. Relationship Guessing Game")
		add_entry("chance_irrelevant", "Chance Irrelevant (0.0 - 1.0):", cfg.chance_irrelevant)
		add_entry("max_cycle_length_game", "Max Cycle Length (Game):", cfg.max_cycle_length_game)
		add_entry("max_indirectness_game", "Max Indirectness (Game):", cfg.max_indirectness_game)
		add_check("leaf_only", "Leaf Nodes Only", cfg.leaf_only)

		# Action buttons
		btn_bar = ttk.Frame(self, padding=(10, 6, 10, 10))
		btn_bar.pack(fill=tk.X)

		ttk.Button(btn_bar, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
		ttk.Button(
			btn_bar, text="Save to input.txt & Apply", command=lambda: self._apply(save_to_disk=True)
		).pack(side=tk.RIGHT, padx=(6, 0))
		ttk.Button(
			btn_bar, text="Apply & Reload", command=lambda: self._apply(save_to_disk=False)
		).pack(side=tk.RIGHT)

	def _browse_graphml(self):
		initial_dir = self.vars["folder_path"].get().strip() or os.getcwd()
		path = filedialog.askopenfilename(
			parent=self,
			title="Select GraphML File",
			initialdir=initial_dir if os.path.isdir(initial_dir) else os.getcwd(),
			filetypes=[("GraphML files", "*.graphml"), ("All files", "*.*")]
		)
		if path:
			self.vars["folder_path"].set(os.path.dirname(path) + os.sep)
			self.vars["file_name"].set(os.path.basename(path))

	def _build_config_from_vars(self) -> Config:
		new_cfg = copy.deepcopy(self.orig_config)
		new_cfg.folder_path = self.vars["folder_path"].get().strip()
		new_cfg.file_name = self.vars["file_name"].get().strip()
		new_cfg.connection_type = self.vars["connection_type"].get().strip().lower() or "correlation"
		new_cfg.ignore_edge_colors = bool(self.vars["ignore_edge_colors"].get()) or (
			new_cfg.connection_type in COUNTER_CONNECTION_TYPES
		)
		new_cfg.color_threshold = int(self.vars["color_threshold"].get().strip())

		new_cfg.show_connections_list = bool(self.vars["show_connections_list"].get())
		new_cfg.connections_skipped = int(self.vars["connections_skipped"].get().strip())
		new_cfg.show_only_edges = bool(self.vars["show_only_edges"].get())
		new_cfg.show_edge_labels = bool(self.vars["show_edge_labels"].get())
		new_cfg.enable_non_cycle_printing = bool(self.vars["enable_non_cycle_printing"].get())
		new_cfg.sort_by_len = bool(self.vars["sort_by_len"].get())
		new_cfg.sort_connections_alphabetically = bool(self.vars["sort_connections_alphabetically"].get())
		new_cfg.max_cycle_length_html = int(self.vars["max_cycle_length_html"].get().strip())
		new_cfg.max_indirectness = int(self.vars["max_indirectness"].get().strip())

		new_cfg.source_node = self.vars["source_node"].get().strip().lower()
		new_cfg.target_node = self.vars["target_node"].get().strip().lower()
		block_raw = self.vars["block_starting_node"].get().strip()
		new_cfg.block_starting_node = [x.strip().lower() for x in block_raw.split(",") if x.strip()]

		chance = float(self.vars["chance_irrelevant"].get().strip())
		if chance > 1.0:
			chance /= 100.0
		new_cfg.chance_irrelevant = chance
		new_cfg.max_cycle_length_game = int(self.vars["max_cycle_length_game"].get().strip())
		new_cfg.max_indirectness_game = int(self.vars["max_indirectness_game"].get().strip())
		new_cfg.leaf_only = bool(self.vars["leaf_only"].get())
		return new_cfg

	def _apply(self, save_to_disk: bool):
		try:
			new_cfg = self._build_config_from_vars()
		except ValueError as e:
			messagebox.showerror("Invalid Configuration", f"Please check numeric fields:\n{e}", parent=self)
			return

		if save_to_disk:
			try:
				save_config_file(self.input_file, new_cfg)
			except Exception as e:
				messagebox.showerror("Save Error", f"Could not save configuration:\n{e}", parent=self)
				return

		self.destroy()
		self.on_apply_callback(new_cfg)


class GraphMLExplorerApp(tk.Tk):
	def __init__(self, input_file: str, output_folder: str):
		super().__init__()
		self.title("GraphML Feedback Loop Explorer")
		self.geometry("1080x740")
		self.minsize(780, 520)

		self.input_file = os.path.abspath(input_file)
		self.output_folder = os.path.abspath(output_folder)

		self.config_obj: Config = Config()
		self.ctx: GraphContext = None
		self.current_graph_path: str = ""
		self.last_html_path: str = ""
		self.is_busy: bool = False
		self.active_session: GameSession = None
		self.prepared_game_data = None

		self.output_queue: queue.Queue = queue.Queue()
		self._orig_stdout = sys.stdout
		self._orig_stderr = sys.stderr
		sys.stdout = ConsoleRedirector(self.output_queue)
		sys.stderr = ConsoleRedirector(self.output_queue)

		self._build_menu()
		self._build_layout()
		self._bind_shortcuts()

		self.protocol("WM_DELETE_WINDOW", self._on_closing)
		self.after(40, self._poll_output_queue)
		self.after(50, self._startup)

	def _build_menu(self):
		self.menubar = tk.Menu(self)

		# File menu
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

		# Tools menu
		tools_menu = tk.Menu(self.menubar, tearoff=0)
		tools_menu.add_command(label="Open Generated HTML", accelerator="Ctrl+H", command=self.open_generated_html)
		tools_menu.add_command(label="Open HTML Output Folder", accelerator="Ctrl+Shift+O", command=self.open_html_folder)
		tools_menu.add_separator()
		tools_menu.add_command(label="Configuration...", accelerator="Ctrl+,", command=self.open_config_dialog)
		self.menubar.add_cascade(label="Tools", menu=tools_menu)

		# Game menu
		game_menu = tk.Menu(self.menubar, tearoff=0)
		game_menu.add_command(label="Start / Restart Game", command=self.start_game)
		game_menu.add_command(label="Reveal / Next", accelerator="Enter", command=self.send_reveal_next)
		game_menu.add_command(label="Stop Game (0)", command=self.send_stop_game)
		self.menubar.add_cascade(label="Game", menu=game_menu)

		self.config(menu=self.menubar)
		self._refresh_recent_menu()

	def _build_layout(self):
		# Top toolbar
		toolbar = ttk.Frame(self, padding=(8, 6))
		toolbar.pack(fill=tk.X)

		self.btn_open = ttk.Button(toolbar, text="📂 Open File...", command=self.open_file_dialog)
		self.btn_open.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_reload = ttk.Button(toolbar, text="🔄 Reload", command=self.reload_current_file)
		self.btn_reload.pack(side=tk.LEFT, padx=(0, 12))

		self.btn_open_html = ttk.Button(toolbar, text="🌐 Open HTML", command=self.open_generated_html, state=tk.DISABLED)
		self.btn_open_html.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_open_folder = ttk.Button(toolbar, text="📁 Open HTML Folder", command=self.open_html_folder)
		self.btn_open_folder.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_regen = ttk.Button(toolbar, text="🔄 Regenerate HTML", command=self.regenerate_html)
		self.btn_regen.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_config = ttk.Button(toolbar, text="⚙ Config", command=self.open_config_dialog)
		self.btn_config.pack(side=tk.RIGHT)

		# Info / Status strip
		info_bar = ttk.Frame(self, padding=(10, 2, 10, 4))
		info_bar.pack(fill=tk.X)

		self.lbl_file = ttk.Label(info_bar, text="No file loaded", font=("Segoe UI", 9, "bold"))
		self.lbl_file.pack(side=tk.LEFT)

		self.lbl_status = ttk.Label(info_bar, text="Idle", foreground="#555555")
		self.lbl_status.pack(side=tk.RIGHT)

		# Persistent Category Progress panel (above the console output)
		progress_frame = ttk.LabelFrame(self, text="Category Progress", padding=8)
		progress_frame.pack(fill=tk.X, padx=8, pady=(0, 6))

		tier_bar = ttk.Frame(progress_frame)
		tier_bar.pack(fill=tk.X, pady=(0, 6))

		self.lbl_current_tier = ttk.Label(
			tier_bar, text="Current tier: —", font=("Segoe UI", 9, "bold")
		)
		self.lbl_current_tier.pack(side=tk.LEFT)

		self.lbl_total_progress = ttk.Label(
			tier_bar, text="", foreground="#555555", font=("Segoe UI", 9)
		)
		self.lbl_total_progress.pack(side=tk.RIGHT)

		table_frame = ttk.Frame(progress_frame)
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

		self.progress_tree.column("category", anchor="w", width=180, minwidth=100, stretch=True)
		self.progress_tree.column("done", anchor="e", width=80, minwidth=50, stretch=False)
		self.progress_tree.column("total", anchor="e", width=80, minwidth=50, stretch=False)
		self.progress_tree.column("pct", anchor="e", width=70, minwidth=45, stretch=False)
		self.progress_tree.column("tier", anchor="e", width=70, minwidth=45, stretch=False)
		self.progress_tree.column("left", anchor="e", width=80, minwidth=50, stretch=False)

		self.progress_tree.pack(fill=tk.X)
		self.progress_tree.tag_configure("complete", foreground="#1B7A34")

		# Read-only Console Output Label area
		console_frame = ttk.Frame(self)
		console_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

		self.console = tk.Text(
			console_frame,
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

		v_scroll = ttk.Scrollbar(console_frame, orient=tk.VERTICAL, command=self.console.yview)
		self.console.configure(yscrollcommand=v_scroll.set)

		self.console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

		# Bottom game control bar
		bottom_bar = ttk.Frame(self, padding=(8, 0, 8, 8))
		bottom_bar.pack(fill=tk.X)

		self.btn_start_game = ttk.Button(bottom_bar, text="▶ Start Game (1)", command=self.start_game)
		self.btn_start_game.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_reveal = ttk.Button(bottom_bar, text="⏭ Reveal / Next (Enter)", command=self.send_reveal_next)
		self.btn_reveal.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_stop_game = ttk.Button(bottom_bar, text="⏹ Stop Game (0)", command=self.send_stop_game)
		self.btn_stop_game.pack(side=tk.LEFT, padx=(0, 6))

		ttk.Button(bottom_bar, text="🧹 Clear Console", command=self.clear_console).pack(side=tk.RIGHT)

	def _bind_shortcuts(self):
		self.bind("<Control-o>", lambda e: self.open_file_dialog())
		self.bind("<Control-O>", lambda e: self.open_file_dialog())
		self.bind("<Control-h>", lambda e: self.open_generated_html())
		self.bind("<Control-H>", lambda e: self.open_generated_html())
		self.bind("<Control-Shift-O>", lambda e: self.open_html_folder())
		self.bind("<Control-comma>", lambda e: self.open_config_dialog())
		self.bind("<F5>", lambda e: self.reload_current_file())
		self.bind("<Return>", self._on_key_enter)
		self.bind("<KP_Enter>", self._on_key_enter)
		self.bind("1", self._on_key_start)
		self.bind("0", self._on_key_stop)

	# ------------------------------------------------------------------
	# Startup & File Resolution
	# ------------------------------------------------------------------
	def _startup(self):
		config_created = False
		if not os.path.exists(self.input_file):
			create_input_file(self.input_file)
			config_created = True

		self.config_obj = read_config_file(self.input_file)
		app_state = load_app_state()
		last_file = app_state.get("last_file", "")

		# Determine file to load: 1) last opened file, 2) input.txt configured file
		candidate_path = ""
		used_last_file = False

		if last_file and os.path.isfile(last_file):
			candidate_path = last_file
			used_last_file = True
		else:
			cfg_path = self._resolve_graph_path_from_config(self.config_obj)
			if cfg_path and os.path.isfile(cfg_path):
				candidate_path = os.path.abspath(cfg_path)

		if candidate_path:
			if used_last_file:
				# Preserve input.txt inline overrides if last_file matches input.txt's target
				cfg_path = self._resolve_graph_path_from_config(self.config_obj)
				same_as_cfg = (
					cfg_path
					and os.path.normcase(os.path.abspath(cfg_path)) == os.path.normcase(os.path.abspath(candidate_path))
				)
				if not same_as_cfg:
					self.config_obj.folder_path = os.path.dirname(candidate_path) + os.sep
					self.config_obj.file_name = os.path.basename(candidate_path)
			self.load_graph_file(candidate_path)
		else:
			self._append_console_text(
				"No GraphML file found to auto-load.\n"
				"Use 'Open File...' or configure your file in Settings.\n\n"
			)
			self._update_button_states()
			if config_created or not self.config_obj.file_name:
				self.open_config_dialog()

	def _resolve_graph_path_from_config(self, cfg: Config) -> str:
		if not cfg.file_name:
			return ""
		if '/' in cfg.file_name or '\\' in cfg.file_name or os.path.isabs(cfg.file_name):
			return cfg.file_name if cfg.file_name.endswith('.graphml') else cfg.file_name + '.graphml'
		return os.path.join(cfg.folder_path, cfg.file_name + ('' if cfg.file_name.endswith('.graphml') else '.graphml'))

	# ------------------------------------------------------------------
	# Recent Files Menu
	# ------------------------------------------------------------------
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
				command=lambda p=path: self.open_specific_file(p)
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
		initial_dir = (
			os.path.dirname(self.current_graph_path)
			if self.current_graph_path and os.path.isdir(os.path.dirname(self.current_graph_path))
			else (self.config_obj.folder_path if os.path.isdir(self.config_obj.folder_path) else os.getcwd())
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
		self.config_obj.folder_path = os.path.dirname(os.path.abspath(filepath)) + os.sep
		self.config_obj.file_name = os.path.basename(filepath)
		self.load_graph_file(filepath)

	def reload_current_file(self):
		if self.current_graph_path and os.path.isfile(self.current_graph_path):
			self.load_graph_file(self.current_graph_path)
		else:
			self.open_file_dialog()

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
		self.lbl_status.configure(text="Loading & generating HTML...")
		self.lbl_file.configure(text=f"Loading: {os.path.basename(norm_path)}")
		self._update_button_states()

		record_recent_file(norm_path)
		self._refresh_recent_menu()

		cfg_snapshot = copy.deepcopy(self.config_obj)
		self._append_console_text(f"\n{'=' * 60}\nLoading: {norm_path}\n{'=' * 60}\n")

		def worker():
			try:
				nodes, edges, edge_values, node_values, edge_labels, node_colors = read_from_graph_xml(
					norm_path, cfg_snapshot.color_threshold
				)

				if cfg_snapshot.ignore_edge_colors or cfg_snapshot.connection_type in COUNTER_CONNECTION_TYPES:
					edge_values = {k: 1 for k in edge_values}
					node_values = {k: 0 for k in node_values}
					print("Note: edge colors ignored — all edge values set to +1.")

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
				self.output_queue.put(("loaded", (ctx, html_path, norm_path, prepared, stats)))
			except Exception as exc:
				self.output_queue.put(("load_error", str(exc)))

		threading.Thread(target=worker, daemon=True).start()

	def regenerate_html(self):
		if self.is_busy:
			return
		if not self.ctx or not self.current_graph_path:
			messagebox.showinfo("No Graph Loaded", "Please open a GraphML file first.", parent=self)
			return

		self._cancel_active_game()
		self.is_busy = True
		self.lbl_status.configure(text="Generating HTML & GraphML...")
		self._update_button_states()

		ctx_ref = self.ctx
		ctx_ref.nodes_printed.clear()
		graph_path = self.current_graph_path

		def worker():
			try:
				html_path = generate_html_and_graphml(ctx_ref, self.output_folder, graph_path)
				self.output_queue.put(("html_done", html_path))
			except Exception as exc:
				self.output_queue.put(("load_error", str(exc)))

		threading.Thread(target=worker, daemon=True).start()

	# ------------------------------------------------------------------
	# HTML & Folder Actions
	# ------------------------------------------------------------------
	def open_generated_html(self):
		if not self.last_html_path or not os.path.isfile(self.last_html_path):
			messagebox.showinfo("No HTML Yet", "No generated HTML file was found. Load or regenerate first.", parent=self)
			return
		try:
			webbrowser.open(Path(self.last_html_path).resolve().as_uri())
		except Exception as e:
			messagebox.showerror("Open HTML Error", f"Could not open HTML file:\n{e}", parent=self)

	def open_html_folder(self):
		os.makedirs(self.output_folder, exist_ok=True)
		try:
			if sys.platform.startswith("win"):
				os.startfile(self.output_folder)
			elif sys.platform == "darwin":
				subprocess.Popen(["open", self.output_folder])
			else:
				subprocess.Popen(["xdg-open", self.output_folder])
		except Exception as e:
			messagebox.showerror("Open Folder Error", f"Could not open folder:\n{e}", parent=self)

	# ------------------------------------------------------------------
	# Configuration UI (only shown when requested or necessary)
	# ------------------------------------------------------------------
	def open_config_dialog(self):
		def on_apply(new_cfg: Config):
			self.config_obj = new_cfg
			target_path = self._resolve_graph_path_from_config(new_cfg)
			if target_path and os.path.isfile(target_path):
				self.load_graph_file(target_path)
			elif self.current_graph_path and os.path.isfile(self.current_graph_path):
				self.load_graph_file(self.current_graph_path)
			else:
				self._append_console_text(f"Configured file not found: {target_path}\n")

		ConfigDialog(self, self.config_obj, self.input_file, on_apply)

	# ------------------------------------------------------------------
	# Relationship Game Runner & Controls
	# ------------------------------------------------------------------
	def start_game(self):
		if self.is_busy:
			return
		if not self.ctx:
			messagebox.showinfo("No Graph Loaded", "Please open a GraphML file first.", parent=self)
			return

		self._cancel_active_game()
		session = GameSession()
		self.active_session = session
		self.lbl_status.configure(text="Game running")
		self._update_button_states()

		ctx_ref = self.ctx
		prepared_ref = self.prepared_game_data

		def on_stats(stats_dict: dict):
			self.output_queue.put(("stats", (session, stats_dict)))

		def gui_input() -> str:
			if session.cancel_event.is_set():
				raise GameCancelledError()
			self.output_queue.put(("waiting_input", (session, True)))
			while True:
				if session.cancel_event.is_set():
					raise GameCancelledError()
				try:
					val = session.input_queue.get(timeout=0.1)
					if val is None or session.cancel_event.is_set():
						raise GameCancelledError()
					self.output_queue.put(("waiting_input", (session, False)))
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
				self.output_queue.put(("game_finished", session))
			except GameCancelledError:
				pass
			except Exception as exc:
				self.output_queue.put(("game_error", (session, str(exc))))

		session.thread = threading.Thread(target=game_worker, daemon=True)
		session.thread.start()

	def send_reveal_next(self):
		if self.active_session and self.active_session.waiting_for_input:
			self._append_console_text("\n")
			self.active_session.waiting_for_input = False
			self.active_session.input_queue.put("")
			self._update_button_states()
			self.focus_set()

	def send_stop_game(self):
		if self.active_session and self.active_session.waiting_for_input:
			self._append_console_text("0\n")
			self.active_session.waiting_for_input = False
			self.active_session.input_queue.put("0")
			self._update_button_states()
			self.focus_set()
		elif self.active_session:
			self._cancel_active_game()
			self._append_console_text("\nGame stopped.\n")
			self.lbl_status.configure(text="Ready")
			self._update_button_states()

	# ------------------------------------------------------------------
	# Terminal-like Console Widget Handling
	# ------------------------------------------------------------------
	def clear_console(self):
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

	def _on_console_backspace(self, event=None):
		try:
			if self.console.tag_ranges("sel"):
				if self.console.compare("sel.first", "<", "input_start"):
					return "break"
				return None
		except tk.TclError:
			pass
		if self.console.compare("insert", "<=", "input_start"):
			return "break"
		return None

	def _on_console_delete(self, event=None):
		try:
			if self.console.tag_ranges("sel"):
				if self.console.compare("sel.first", "<", "input_start"):
					return "break"
				return None
		except tk.TclError:
			pass
		if self.console.compare("insert", "<", "input_start"):
			return "break"
		return None

	def _on_console_home(self, event=None):
		if self.console.compare("insert", ">=", "input_start") and self.console.compare(
			"insert linestart", "==", "input_start linestart"
		):
			self.console.mark_set("insert", "input_start")
			return "break"
		return None

	def _on_console_cut(self, event=None):
		try:
			if self.console.tag_ranges("sel") and self.console.compare("sel.first", "<", "input_start"):
				return "break"
		except tk.TclError:
			pass
		if self.console.compare("insert", "<", "input_start"):
			return "break"
		return None

	def _on_console_paste(self, event=None):
		if self.console.compare("insert", "<", "input_start"):
			self.console.mark_set("insert", "end-1c")
		try:
			pasted = self.clipboard_get()
			single_line = pasted.replace("\r\n", " ").replace("\n", " ")
			self.console.insert("insert", single_line)
		except tk.TclError:
			pass
		return "break"

	def _on_console_key(self, event):
		# Allow shortcuts & navigation keys freely
		if event.state & 0x4:  # Control pressed (e.g., Ctrl+C, Ctrl+A)
			return None
		if event.keysym in (
			"Left", "Right", "Up", "Down", "Prior", "Next", "Home", "End",
			"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
			"Escape", "Tab", "F5"
		):
			return None

		# If typing printable character while cursor is in history, jump to active prompt
		if event.char and ord(event.char) >= 32:
			try:
				if self.console.tag_ranges("sel") and self.console.compare("sel.first", "<", "input_start"):
					self.console.tag_remove("sel", "1.0", "end")
					self.console.mark_set("insert", "end-1c")
			except tk.TclError:
				pass
			if self.console.compare("insert", "<", "input_start"):
				self.console.mark_set("insert", "end-1c")
				self.console.see("end-1c")
		return None

	# ------------------------------------------------------------------
	# Queue Polling & UI State
	# ------------------------------------------------------------------
	def _poll_output_queue(self):
		try:
			while True:
				kind, payload = self.output_queue.get_nowait()

				if kind == "text":
					self._append_console_text(payload)

				elif kind == "loaded":
					ctx, html_path, norm_path, prepared, stats = payload
					self.ctx = ctx
					self.prepared_game_data = prepared
					self.last_html_path = html_path or ""
					self.is_busy = False
					conn_mode = ctx.config.connection_type
					self.title(f"GraphML Feedback Loop Explorer — {os.path.basename(norm_path)}")
					self.lbl_file.configure(
						text=f"{os.path.basename(norm_path)}  |  Nodes: {len(ctx.nodes)}  |  Edges: {len(ctx.edges)}  |  Mode: {conn_mode}"
					)
					self.lbl_status.configure(text="Ready")
					self._update_progress_table(stats)
					self._append_console_text("Ready! Press '1' or click 'Start Game' to begin.\n")
					self._update_button_states()
					self.console.focus_set()

				elif kind == "html_done":
					self.last_html_path = payload or self.last_html_path
					self.is_busy = False
					self.lbl_status.configure(text="Ready")
					self._update_button_states()

				elif kind == "load_error":
					self.is_busy = False
					self.prepared_game_data = None
					self._update_progress_table(None)
					self.lbl_status.configure(text="Load Error")
					self._append_console_text(f"\nERROR: {payload}\n")
					self._update_button_states()
					# Open Configuration UI automatically since user intervention is needed
					messagebox.showerror(
						"Configuration / Load Error",
						f"{payload}\n\nOpening Configuration so you can adjust settings.",
						parent=self
					)
					self.open_config_dialog()

				elif kind == "waiting_input":
					session, is_waiting = payload
					if session is self.active_session:
						session.waiting_for_input = is_waiting
						self.lbl_status.configure(
							text="Game: Waiting for input" if is_waiting else "Game: Processing..."
						)
						self._update_button_states()

				elif kind == "game_finished":
					session = payload
					if session is self.active_session:
						self.active_session = None
						self.lbl_status.configure(text="Ready")
						self._append_console_text("\nEnter '1' + Enter or click 'Start Game' to play again.\n")
						self._update_button_states()

				elif kind == "game_error":
					session, err_msg = payload
					if session is self.active_session:
						self.active_session = None
						self.lbl_status.configure(text="Game Error")
						self._append_console_text(f"\nGame Error: {err_msg}\n")
						self._update_button_states()
				elif kind == "stats":
					session, stats_dict = payload
					if session is self.active_session:
						self._update_progress_table(stats_dict)

		except queue.Empty:
			pass
		self.after(40, self._poll_output_queue)

	def _update_button_states(self):
		has_ctx = self.ctx is not None
		has_html = bool(self.last_html_path and os.path.isfile(self.last_html_path))
		game_active = self.active_session is not None
		waiting = bool(game_active and self.active_session.waiting_for_input)

		self.btn_open.configure(state=tk.DISABLED if self.is_busy else tk.NORMAL)
		self.btn_reload.configure(state=tk.NORMAL if (not self.is_busy and self.current_graph_path) else tk.DISABLED)
		self.btn_open_html.configure(state=tk.NORMAL if has_html else tk.DISABLED)
		self.btn_config.configure(state=tk.DISABLED if self.is_busy else tk.NORMAL)
		self.btn_regen.configure(state=tk.NORMAL if (not self.is_busy and has_ctx) else tk.DISABLED)

		self.btn_start_game.configure(
			text="🔄 Restart Game" if game_active else "▶ Start Game (1)",
			state=tk.NORMAL if (not self.is_busy and has_ctx) else tk.DISABLED,
		)
		self.btn_reveal.configure(state=tk.NORMAL if waiting else tk.DISABLED)
		self.btn_stop_game.configure(state=tk.NORMAL if game_active else tk.DISABLED)

	def _on_closing(self):
		self._cancel_active_game()
		sys.stdout = self._orig_stdout
		sys.stderr = self._orig_stderr
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
		total_answered = sum(r["answered"] for r in rows)
		total_items = sum(r["total"] for r in rows)
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

	def _on_key_enter(self, event=None):
		if self.active_session and self.active_session.waiting_for_input:
			self.send_reveal_next()
			return "break"
		return None

	def _on_key_start(self, event=None):
		if not self.is_busy and self.ctx and self.active_session is None:
			self.start_game()
			return "break"
		return None

	def _on_key_stop(self, event=None):
		if self.active_session is not None:
			self.send_stop_game()
			return "break"
		return None