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
	GRAPH_SETTING_KEYS,
	build_effective_config,
	create_input_file,
	read_config_file,
	save_config_file,
)
from src.games.relationship_game import (
	GameCancelledError,
	run_relationship_guessing_game,
	prepare_relationship_game_data,
	compute_relationship_stats,
)
from src.graph_diagram import (
	GraphDiagramData,
	compute_circular_layout,
	compute_edge_geometry, format_graph_node_label, AnswerHighlight, find_cycle_icon_path, compute_cycle_center,
	blend_hex_with_white,
)
from src.html_exporter import generate_html_and_graphml
from src.io_graphml import list_graph_elements_and_groups, read_from_graph_xml
from src.models import GraphContext
from src.progress_storage import (
	clear_recent_files,
	delete_graph_config,
	load_app_state,
	load_graph_config,
	record_recent_file,
	save_graph_config, set_sync_folder, get_sync_folder, get_local_data_dir,
)

ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')


def run_gui(input_file: str, output_folder: str):
	app = GraphMLExplorerApp(input_file, output_folder)
	try:
		app.mainloop()
	finally:
		sys.stdout = app._orig_stdout
		sys.stderr = app._orig_stderr


class ConsoleRedirector:
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
			self.msg_queue.put(("text", clean))

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


class ExclusionPickerDialog(tk.Toplevel):
	"""Searchable checklist to pick Groups and Elements from the current GraphML file."""

	def __init__(self, parent, graph_path: str, current_excluded: list, on_confirm):
		super().__init__(parent)
		self.title(f"Exclude Elements / Groups — {os.path.basename(graph_path)}")
		self.transient(parent)
		self.grab_set()
		self.geometry("1220x760")
		self.minsize(880, 540)

		self.on_confirm = on_confirm
		self.selected_lower = {x.strip().lower(): x.strip() for x in current_excluded if x.strip()}

		groups, elements = list_graph_elements_and_groups(graph_path)
		self.all_items = [("Group", g) for g in groups] + [("Node", e) for e in elements]
		self.vars = {}
		for kind, name in self.all_items:
			self.vars[(kind, name)] = tk.BooleanVar(value=(name.lower() in self.selected_lower))

		outer = ttk.Frame(self, padding=10)
		outer.pack(fill=tk.BOTH, expand=True)

		ttk.Label(
			outer,
			text="Check groups (excludes the group and everything inside) or individual nodes:",
			wraplength=420,
		).pack(anchor="w", pady=(0, 6))

		search_bar = ttk.Frame(outer)
		search_bar.pack(fill=tk.X, pady=(0, 6))
		ttk.Label(search_bar, text="Filter:").pack(side=tk.LEFT, padx=(0, 6))
		self.search_var = tk.StringVar()
		self.search_var.trace_add("write", lambda *_: self._render_items())
		ttk.Entry(search_bar, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

		list_container = ttk.Frame(outer)
		list_container.pack(fill=tk.BOTH, expand=True)

		self.canvas = tk.Canvas(list_container, highlightthickness=0)
		scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=self.canvas.yview)
		self.items_frame = ttk.Frame(self.canvas)
		self.items_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
		self.canvas_win = self.canvas.create_window((0, 0), window=self.items_frame, anchor="nw")
		self.canvas.configure(yscrollcommand=scrollbar.set)
		self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.canvas_win, width=e.width))

		self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

		btn_bar = ttk.Frame(outer, padding=(0, 8, 0, 0))
		btn_bar.pack(fill=tk.X)
		ttk.Button(btn_bar, text="Uncheck All", command=self._uncheck_all).pack(side=tk.LEFT)
		ttk.Button(btn_bar, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
		ttk.Button(btn_bar, text="OK", command=self._confirm).pack(side=tk.RIGHT)

		self._render_items()

	def _render_items(self):
		for child in self.items_frame.winfo_children():
			child.destroy()
		q = self.search_var.get().strip().lower()
		for kind, name in self.all_items:
			if q and q not in name.lower() and q not in kind.lower():
				continue
			label = f"[{kind}]  {name}"
			ttk.Checkbutton(self.items_frame, text=label, variable=self.vars[(kind, name)]).pack(anchor="w", pady=1)

	def _uncheck_all(self):
		for var in self.vars.values():
			var.set(False)

	def _confirm(self):
		seen = set()
		result = []
		for (kind, name), var in self.vars.items():
			if var.get() and name.lower() not in seen:
				seen.add(name.lower())
				result.append(name)
		known_names_lower = {name.lower() for _, name in self.all_items}
		for low, orig in self.selected_lower.items():
			if low not in known_names_lower and low not in seen:
				seen.add(low)
				result.append(orig)
		self.destroy()
		self.on_confirm(result)


class ConfigDialog(tk.Toplevel):
	"""Configuration UI dialog — separates App Settings, Global Defaults, and per-setting Local Overrides."""

	def __init__(
		self,
		parent,
		base_config: Config,
		local_overrides: dict,
		input_file: str,
		on_apply_callback,
		current_graph_path: str = "",
		on_open_file_callback=None,
	):
		super().__init__(parent)
		self.current_graph_path = current_graph_path
		self.has_file = bool(current_graph_path and os.path.isfile(current_graph_path))
		self.base_config = copy.deepcopy(base_config)
		self.local_overrides = copy.deepcopy(local_overrides or {})
		self.input_file = input_file
		self.on_apply_callback = on_apply_callback
		self.on_open_file_callback = on_open_file_callback

		title_suffix = os.path.basename(current_graph_path) if self.has_file else "Global & App Settings"
		self.title(f"Configuration — {title_suffix}")
		self.transient(parent)
		self.grab_set()
		self.resizable(True, True)
		self.geometry("920x1000")
		self.minsize(720, 480)

		self.app_vars = {}
		self.global_vars = {}
		self.local_enabled_vars = {}
		self.local_vars = {}
		self.local_widgets = {}

		self._build_ui()
		self.protocol("WM_DELETE_WINDOW", self.destroy)

	@staticmethod
	def _set_widget_enabled(widget, enabled: bool):
		if isinstance(widget, tk.Text):
			widget.configure(
				state=tk.NORMAL if enabled else tk.DISABLED,
				bg="#FFFFFF" if enabled else "#ECECEC",
				fg="#000000" if enabled else "#777777",
			)
		elif isinstance(widget, ttk.Combobox):
			widget.configure(state="normal" if enabled else "disabled")
		else:
			widget.configure(state=tk.NORMAL if enabled else tk.DISABLED)

	def _update_local_row_state(self, key: str):
		enabled = self.has_file and bool(self.local_enabled_vars[key].get())
		for w in self.local_widgets.get(key, []):
			self._set_widget_enabled(w, enabled)

	def _build_ui(self):
		if self.has_file:
			active_count = sum(1 for k in GRAPH_SETTING_KEYS if k in self.local_overrides)
			status_text = (
				f"Current GraphML: {os.path.basename(self.current_graph_path)}  |  "
				f"Active local overrides: {active_count} / {len(GRAPH_SETTING_KEYS)}"
			)
		else:
			status_text = "No GraphML file loaded — editing Global Defaults & App Settings (Local overrides disabled)"
		ttk.Label(self, text=status_text, padding=(12, 8, 12, 4), font=("Segoe UI", 9, "bold")).pack(fill=tk.X)

		notebook = ttk.Notebook(self)
		notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 6))

		# ------------------------------------------------------------------
		# Tab 1: Graph Settings (Global vs Local per setting)
		# ------------------------------------------------------------------
		graph_tab = ttk.Frame(notebook, padding=6)
		notebook.add(graph_tab, text="Graph Settings (Global / Local)")

		canvas = tk.Canvas(graph_tab, highlightthickness=0)
		scrollbar = ttk.Scrollbar(graph_tab, orient=tk.VERTICAL, command=canvas.yview)
		form_frame = ttk.Frame(canvas, padding=(4, 4, 12, 4))

		form_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
		canvas_window = canvas.create_window((0, 0), window=form_frame, anchor="nw")
		canvas.configure(yscrollcommand=scrollbar.set)
		canvas.bind("<Configure>", lambda e: canvas.itemconfigure(canvas_window, width=e.width))

		def _on_mousewheel(event):
			if event.widget in (getattr(self, "txt_global_excluded", None), getattr(self, "txt_local_excluded", None)):
				return
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

		form_frame.columnconfigure(0, weight=2, minsize=210)
		form_frame.columnconfigure(1, weight=2, minsize=200)
		form_frame.columnconfigure(2, weight=0, minsize=72)
		form_frame.columnconfigure(3, weight=2, minsize=200)

		row = 0
		ttk.Label(form_frame, text="Setting", font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
		ttk.Label(form_frame, text="Global (Default)", font=("Segoe UI", 9, "bold")).grid(row=row, column=1, sticky="w", padx=(0, 8), pady=(0, 4))
		ttk.Label(form_frame, text="Use Local", font=("Segoe UI", 9, "bold")).grid(row=row, column=2, sticky="n", padx=4, pady=(0, 4))
		ttk.Label(form_frame, text="Local (Current File)", font=("Segoe UI", 9, "bold")).grid(row=row, column=3, sticky="w", padx=(8, 0), pady=(0, 4))
		row += 1

		def add_section(title: str):
			nonlocal row
			ttk.Separator(form_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=4, sticky="ew", pady=(8, 4))
			row += 1
			ttk.Label(form_frame, text=title, font=("Segoe UI", 10, "bold")).grid(row=row, column=0, columnspan=4, sticky="w", pady=(0, 4))
			row += 1

		def _register_local_toggle(key: str):
			is_local = self.has_file and (key in self.local_overrides)
			en_var = tk.BooleanVar(value=is_local)
			self.local_enabled_vars[key] = en_var
			chk_en = ttk.Checkbutton(
				form_frame,
				variable=en_var,
				command=lambda k=key: self._update_local_row_state(k),
				state=tk.NORMAL if self.has_file else tk.DISABLED,
			)
			chk_en.grid(row=row, column=2, sticky="n", pady=3)
			return is_local

		def add_entry_pair(key: str, label: str, g_val, l_raw_val=None, fmt_fn=str):
			nonlocal row
			ttk.Label(form_frame, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))

			g_str = fmt_fn(g_val)
			g_var = tk.StringVar(value=g_str)
			self.global_vars[key] = g_var
			ttk.Entry(form_frame, textvariable=g_var).grid(row=row, column=1, sticky="ew", pady=3, padx=(0, 8))

			is_local = _register_local_toggle(key)
			l_str = fmt_fn(l_raw_val) if is_local else g_str
			l_var = tk.StringVar(value=l_str)
			self.local_vars[key] = l_var
			l_entry = ttk.Entry(form_frame, textvariable=l_var)
			l_entry.grid(row=row, column=3, sticky="ew", pady=3, padx=(8, 0))
			self.local_widgets[key] = [l_entry]
			self._update_local_row_state(key)
			row += 1

		def add_combo_pair(key: str, label: str, g_val: str, l_raw_val, options: list):
			nonlocal row
			ttk.Label(form_frame, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))

			g_var = tk.StringVar(value=str(g_val))
			self.global_vars[key] = g_var
			ttk.Combobox(form_frame, textvariable=g_var, values=options, state="normal").grid(
				row=row, column=1, sticky="ew", pady=3, padx=(0, 8)
			)

			is_local = _register_local_toggle(key)
			l_var = tk.StringVar(value=str(l_raw_val) if is_local else str(g_val))
			self.local_vars[key] = l_var
			l_combo = ttk.Combobox(form_frame, textvariable=l_var, values=options, state="normal")
			l_combo.grid(row=row, column=3, sticky="ew", pady=3, padx=(8, 0))
			self.local_widgets[key] = [l_combo]
			self._update_local_row_state(key)
			row += 1

		def add_check_pair(key: str, label: str, g_val: bool, l_raw_val):
			nonlocal row
			ttk.Label(form_frame, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))

			g_var = tk.BooleanVar(value=bool(g_val))
			self.global_vars[key] = g_var
			ttk.Checkbutton(form_frame, text="Enabled", variable=g_var).grid(row=row, column=1, sticky="w", pady=3, padx=(0, 8))

			is_local = _register_local_toggle(key)
			l_var = tk.BooleanVar(value=bool(l_raw_val) if is_local else bool(g_val))
			self.local_vars[key] = l_var
			l_chk = ttk.Checkbutton(form_frame, text="Enabled", variable=l_var)
			l_chk.grid(row=row, column=3, sticky="w", pady=3, padx=(8, 0))
			self.local_widgets[key] = [l_chk]
			self._update_local_row_state(key)
			row += 1

		cfg = self.base_config
		loc = self.local_overrides

		add_section("1. Connection Mode")
		add_combo_pair("connection_type", "Connection Type", cfg.connection_type, loc.get("connection_type"), ["correlation", "counter", "family"])
		add_check_pair("ignore_edge_colors", "Ignore Edge Colors (+1)", cfg.ignore_edge_colors, loc.get("ignore_edge_colors"))
		add_entry_pair("color_threshold", "Color Threshold", cfg.color_threshold, loc.get("color_threshold"))

		add_section("2. HTML & GraphML Output")
		add_check_pair("show_connections_list", "Show Connections List", cfg.show_connections_list, loc.get("show_connections_list"))
		add_entry_pair("connections_skipped", "Connections Skipped", cfg.connections_skipped, loc.get("connections_skipped"))
		add_check_pair("show_only_edges", "Show Only Edges", cfg.show_only_edges, loc.get("show_only_edges"))
		add_check_pair("show_edge_labels", "Show Edge Labels", cfg.show_edge_labels, loc.get("show_edge_labels"))
		add_check_pair("enable_non_cycle_printing", "Non-Cycle Path Printing", cfg.enable_non_cycle_printing, loc.get("enable_non_cycle_printing"))
		add_check_pair("sort_by_len", "Sort Cycles by Length", cfg.sort_by_len, loc.get("sort_by_len"))
		add_check_pair("sort_connections_alphabetically", "Sort Connections Alpha", cfg.sort_connections_alphabetically, loc.get("sort_connections_alphabetically"))
		add_entry_pair("max_cycle_length_html", "Max Cycle Length (HTML)", cfg.max_cycle_length_html, loc.get("max_cycle_length_html"))
		add_entry_pair("max_indirectness", "Max Indirectness (HTML)", cfg.max_indirectness, loc.get("max_indirectness"))

		add_section("3. Node & Group Filters")
		add_entry_pair("source_node", "Source Node (blank = all)", cfg.source_node, loc.get("source_node"))
		add_entry_pair("target_node", "Target Node (blank = all)", cfg.target_node, loc.get("target_node"))
		add_entry_pair(
			"block_starting_node",
			"Block Starting Nodes (csv)",
			cfg.block_starting_node,
			loc.get("block_starting_node"),
			fmt_fn=lambda xs: ", ".join(xs) if isinstance(xs, list) else str(xs or ""),
		)

		# Excluded Elements (Global + Local with Pick buttons)
		ttk.Label(form_frame, text="Excluded Elements / Groups\n(one per line)").grid(row=row, column=0, sticky="nw", pady=4, padx=(0, 8))

		g_excl_box = ttk.Frame(form_frame)
		g_excl_box.grid(row=row, column=1, sticky="ew", pady=4, padx=(0, 8))
		g_excl_box.columnconfigure(0, weight=1)
		self.txt_global_excluded = tk.Text(g_excl_box, height=5, width=22, wrap=tk.NONE)
		self.txt_global_excluded.insert("1.0", "\n".join(cfg.excluded_elements))
		self.txt_global_excluded.grid(row=0, column=0, sticky="ew")
		if self.has_file:
			ttk.Button(g_excl_box, text="Pick...", command=lambda: self._open_exclusion_picker(self.txt_global_excluded)).grid(
				row=0, column=1, sticky="n", padx=(4, 0)
			)

		is_local_excl = _register_local_toggle("excluded_elements")
		l_excl_list = loc.get("excluded_elements") if (is_local_excl and isinstance(loc.get("excluded_elements"), list)) else cfg.excluded_elements

		l_excl_box = ttk.Frame(form_frame)
		l_excl_box.grid(row=row, column=3, sticky="ew", pady=4, padx=(8, 0))
		l_excl_box.columnconfigure(0, weight=1)
		self.txt_local_excluded = tk.Text(l_excl_box, height=5, width=22, wrap=tk.NONE)
		self.txt_local_excluded.insert("1.0", "\n".join(l_excl_list))
		self.txt_local_excluded.grid(row=0, column=0, sticky="ew")
		l_widgets = [self.txt_local_excluded]
		if self.has_file:
			btn_l_pick = ttk.Button(l_excl_box, text="Pick...", command=lambda: self._open_exclusion_picker(self.txt_local_excluded))
			btn_l_pick.grid(row=0, column=1, sticky="n", padx=(4, 0))
			l_widgets.append(btn_l_pick)
		self.local_widgets["excluded_elements"] = l_widgets
		self._update_local_row_state("excluded_elements")
		row += 1

		add_section("4. Relationship Guessing Game")
		add_entry_pair("chance_irrelevant", "Chance Irrelevant (0.0-1.0)", cfg.chance_irrelevant, loc.get("chance_irrelevant"))
		add_entry_pair("max_cycle_length_game", "Max Cycle Length (Game)", cfg.max_cycle_length_game, loc.get("max_cycle_length_game"))
		add_entry_pair("max_indirectness_game", "Max Indirectness (Game)", cfg.max_indirectness_game, loc.get("max_indirectness_game"))
		add_check_pair("leaf_only", "Leaf Nodes Only", cfg.leaf_only, loc.get("leaf_only"))

		# ------------------------------------------------------------------
		# Tab 2: App Settings (Startup / Default File, separate from Graph Settings)
		# ------------------------------------------------------------------
		app_tab = ttk.Frame(notebook, padding=14)
		notebook.add(app_tab, text="App Settings")
		app_tab.columnconfigure(1, weight=1)

		ttk.Label(
			app_tab,
			text="App Settings (saved in input.txt; independent of per-file Graph Settings):",
			font=("Segoe UI", 10, "bold"),
		).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

		ttk.Label(app_tab, text="Default GraphML Folder:").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
		self.app_vars["folder_path"] = tk.StringVar(value=cfg.folder_path)
		ttk.Entry(app_tab, textvariable=self.app_vars["folder_path"]).grid(row=1, column=1, sticky="ew", pady=4)
		ttk.Button(app_tab, text="Browse...", command=self._browse_graphml).grid(row=1, column=2, padx=(6, 0), pady=4)

		ttk.Label(app_tab, text="Default File Name / Path:").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
		self.app_vars["file_name"] = tk.StringVar(value=cfg.file_name)
		ttk.Entry(app_tab, textvariable=self.app_vars["file_name"]).grid(row=2, column=1, sticky="ew", pady=4)
		ttk.Button(app_tab, text="Browse...", command=self._browse_graphml).grid(row=2, column=2, padx=(6, 0), pady=4)

		ttk.Label(app_tab, text="Default Sync Folder (Syncthing):").grid(row=3, column=0, sticky="w", pady=4, padx=(0, 8))
		self.app_vars["sync_folder"] = tk.StringVar(value=get_sync_folder())
		ttk.Entry(app_tab, textvariable=self.app_vars["sync_folder"]).grid(row=3, column=1, sticky="ew", pady=4)
		ttk.Button(app_tab, text="Browse...", command=self._browse_sync_folder).grid(row=3, column=2, padx=(6, 0), pady=4)

		btn_app_row = ttk.Frame(app_tab)
		btn_app_row.grid(row=4, column=1, sticky="w", pady=(10, 4))

		if self.on_open_file_callback is not None:
			ttk.Button(btn_app_row, text="Open Default File Now", command=self._open_configured_file).pack(
				side=tk.LEFT, padx=(0, 8)
			)

		ttk.Button(btn_app_row, text="Open AppData Folder", command=self._open_appdata_folder).pack(side=tk.LEFT)

		ttk.Label(
			app_tab,
			text="Used as the startup fallback file when no recent file is available in app_state.json.",
			foreground="#555555",
			wraplength=560,
		).grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))

		# ------------------------------------------------------------------
		# Bottom Button Bar
		# ------------------------------------------------------------------
		btn_bar = ttk.Frame(self, padding=(10, 4, 10, 10))
		btn_bar.pack(fill=tk.X)

		if self.has_file:
			ttk.Button(btn_bar, text="Clear All Local", command=self._clear_all_local).pack(side=tk.LEFT)

		ttk.Button(btn_bar, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
		ttk.Button(btn_bar, text="Save & Apply", command=lambda: self._apply(mode="save")).pack(side=tk.RIGHT, padx=(6, 0))
		ttk.Button(btn_bar, text="Apply (Session Only)", command=lambda: self._apply(mode="session")).pack(side=tk.RIGHT)

	def _open_exclusion_picker(self, target_text_widget: tk.Text):
		raw = target_text_widget.get("1.0", tk.END)
		current = [line.strip() for line in raw.splitlines() if line.strip()]

		def on_picked(new_list):
			target_text_widget.delete("1.0", tk.END)
			target_text_widget.insert("1.0", "\n".join(new_list))

		try:
			ExclusionPickerDialog(self, self.current_graph_path, current, on_picked)
		except Exception as exc:
			messagebox.showerror("Error", f"Could not inspect GraphML elements:\n{exc}", parent=self)

	def _browse_graphml(self):
		initial_dir = self.app_vars["folder_path"].get().strip() or os.getcwd()
		path = filedialog.askopenfilename(
			parent=self,
			title="Select Default GraphML File",
			initialdir=initial_dir if os.path.isdir(initial_dir) else os.getcwd(),
			filetypes=[("GraphML files", "*.graphml"), ("All files", "*.*")],
		)
		if path:
			self.app_vars["folder_path"].set(os.path.dirname(path) + os.sep)
			self.app_vars["file_name"].set(os.path.basename(path))

	def _open_configured_file(self):
		folder = self.app_vars["folder_path"].get().strip()
		fname = self.app_vars["file_name"].get().strip()
		if not fname:
			messagebox.showinfo("No File Specified", "Enter a Default File Name / Path first.", parent=self)
			return
		if '/' in fname or '\\' in fname or os.path.isabs(fname):
			target = fname if fname.endswith('.graphml') else fname + '.graphml'
		else:
			target = os.path.join(folder, fname + ('' if fname.endswith('.graphml') else '.graphml'))
		if not os.path.isfile(target):
			messagebox.showerror("File Not Found", f"Could not find file:\n{target}", parent=self)
			return
		self.destroy()
		self.on_open_file_callback(target)

	def _clear_all_local(self):
		for key, en_var in self.local_enabled_vars.items():
			en_var.set(False)
			self._update_local_row_state(key)

	def _parse_graph_fields(self, vars_map: dict, excl_widget: tk.Text, scope_label: str) -> dict:
		out = {}
		out["connection_type"] = vars_map["connection_type"].get().strip().lower() or "correlation"
		out["ignore_edge_colors"] = bool(vars_map["ignore_edge_colors"].get())
		try:
			out["color_threshold"] = int(vars_map["color_threshold"].get().strip())
			out["connections_skipped"] = int(vars_map["connections_skipped"].get().strip())
			out["max_cycle_length_html"] = int(vars_map["max_cycle_length_html"].get().strip())
			out["max_indirectness"] = int(vars_map["max_indirectness"].get().strip())
			out["max_cycle_length_game"] = int(vars_map["max_cycle_length_game"].get().strip())
			out["max_indirectness_game"] = int(vars_map["max_indirectness_game"].get().strip())
			chance = float(vars_map["chance_irrelevant"].get().strip())
		except ValueError as exc:
			raise ValueError(f"[{scope_label}] Check numeric fields: {exc}") from exc

		if chance > 1.0:
			chance /= 100.0
		out["chance_irrelevant"] = chance
		out["show_connections_list"] = bool(vars_map["show_connections_list"].get())
		out["show_only_edges"] = bool(vars_map["show_only_edges"].get())
		out["show_edge_labels"] = bool(vars_map["show_edge_labels"].get())
		out["enable_non_cycle_printing"] = bool(vars_map["enable_non_cycle_printing"].get())
		out["sort_by_len"] = bool(vars_map["sort_by_len"].get())
		out["sort_connections_alphabetically"] = bool(vars_map["sort_connections_alphabetically"].get())
		out["source_node"] = vars_map["source_node"].get().strip().lower()
		out["target_node"] = vars_map["target_node"].get().strip().lower()
		block_raw = vars_map["block_starting_node"].get().strip()
		out["block_starting_node"] = [x.strip().lower() for x in block_raw.split(",") if x.strip()]
		out["excluded_elements"] = [line.strip() for line in excl_widget.get("1.0", tk.END).splitlines() if line.strip()]
		out["leaf_only"] = bool(vars_map["leaf_only"].get())
		return out

	def _build_configs(self):
		global_dict = self._parse_graph_fields(self.global_vars, self.txt_global_excluded, "Global")
		new_base = copy.deepcopy(self.base_config)
		new_base.folder_path = self.app_vars["folder_path"].get().strip()
		new_base.file_name = self.app_vars["file_name"].get().strip()
		for k, v in global_dict.items():
			setattr(new_base, k, v)

		new_local = {}
		if self.has_file:
			local_parsed = self._parse_graph_fields(self.local_vars, self.txt_local_excluded, "Local")
			for k in GRAPH_SETTING_KEYS:
				if self.local_enabled_vars[k].get():
					new_local[k] = local_parsed[k]
		return new_base, new_local

	def _apply(self, mode: str):
		try:
			new_base, new_local = self._build_configs()
		except ValueError as e:
			messagebox.showerror("Invalid Configuration", str(e), parent=self)
			return

		sync_folder = self.app_vars["sync_folder"].get().strip() if "sync_folder" in self.app_vars else None
		self.destroy()
		self.on_apply_callback(new_base, new_local, mode=mode, sync_folder=sync_folder)

	def _browse_sync_folder(self):
		current = self.app_vars["folder_path"].get().strip()
		path = filedialog.askdirectory(
			parent=self,
			title="Select Default GraphML Folder",
			initialdir=current if os.path.isdir(current) else os.getcwd(),
		)
		if path:
			self.app_vars["folder_path"].set(path + os.sep)

	def _open_appdata_folder(self):
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


class GraphMLExplorerApp(tk.Tk):
	def __init__(self, input_file: str, output_folder: str):
		super().__init__()
		self.title("GraphML Feedback Loop Explorer")
		self.geometry("1220x760")
		self.minsize(880, 540)

		self.input_file = os.path.abspath(input_file)
		self.output_folder = os.path.abspath(output_folder)

		self.base_config: Config = Config()
		self.config_obj: Config = Config()
		self.ctx: GraphContext = None
		self.current_graph_path: str = ""
		self.last_html_path: str = ""
		self.is_busy: bool = False
		self.active_session: GameSession = None
		self.prepared_game_data = None
		self.current_diagram: GraphDiagramData = None
		self.active_highlight: AnswerHighlight = None
		self._hovered_answer_tag: str = None
		self._answer_highlights: dict = {}
		self._answer_tag_seq: int = 0
		self._icon_photo_cache: dict = {}


		self.output_queue: queue.Queue = queue.Queue()
		self._orig_stdout = sys.stdout
		self._orig_stderr = sys.stderr
		sys.stdout = ConsoleRedirector(self.output_queue, self._orig_stdout)
		sys.stderr = ConsoleRedirector(self.output_queue, self._orig_stderr)

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
		tools_menu.add_command(label="Open HTML Output Folder", accelerator="Ctrl+Shift+O",
							   command=self.open_html_folder)
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

		self.btn_config = ttk.Button(toolbar, text="⚙ Config", command=self.open_config_dialog, takefocus=0)
		self.btn_config.pack(side=tk.RIGHT)

		info_bar = ttk.Frame(self, padding=(10, 2, 10, 4))
		info_bar.pack(fill=tk.X)

		self.lbl_file = ttk.Label(info_bar, text="No file loaded", font=("Segoe UI", 9, "bold"))
		self.lbl_file.pack(side=tk.LEFT)

		self.lbl_status = ttk.Label(info_bar, text="Idle", foreground="#555555")
		self.lbl_status.pack(side=tk.RIGHT)

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

		main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
		main_pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

		console_frame = ttk.Frame(main_pane)
		main_pane.add(console_frame, weight=3)

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
		self.console.bind("<Leave>", lambda _e: self._set_hovered_answer_tag(None))

		v_scroll = ttk.Scrollbar(console_frame, orient=tk.VERTICAL, command=self.console.yview)
		self.console.configure(yscrollcommand=v_scroll.set)
		self.console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

		graph_panel = ttk.LabelFrame(main_pane, text="Relationship Graph", padding=6)
		main_pane.add(graph_panel, weight=2)

		self.lbl_graph_title = ttk.Label(graph_panel, text="Reveal an answer to view graph",
										 font=("Segoe UI", 9, "bold"))
		self.lbl_graph_title.pack(anchor="w", pady=(0, 4))

		self.graph_canvas = tk.Canvas(
			graph_panel,
			bg="#FFFFFF",
			highlightthickness=1,
			highlightbackground="#CCCCCC",
		)
		self.graph_canvas.pack(fill=tk.BOTH, expand=True)
		self.graph_canvas.bind("<Configure>", lambda _e: self._redraw_graph_canvas())

		bottom_bar = ttk.Frame(self, padding=(8, 0, 8, 8))
		bottom_bar.pack(fill=tk.X)

		self.btn_start_game = ttk.Button(bottom_bar, text="▶ Start Game (Enter/Space)", command=self.start_game,
										 takefocus=0)
		self.btn_start_game.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_reveal = ttk.Button(bottom_bar, text="⏭ Reveal / Next (Enter/Space)", command=self.send_reveal_next,
									 takefocus=0)
		self.btn_reveal.pack(side=tk.LEFT, padx=(0, 6))

		ttk.Button(bottom_bar, text="🧹 Clear Console", command=self.clear_console, takefocus=0).pack(side=tk.RIGHT)

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
	# Startup & File Resolution
	# ------------------------------------------------------------------
	def _startup(self):
		config_created = False
		if not os.path.exists(self.input_file):
			create_input_file(self.input_file)
			config_created = True

		self.base_config = read_config_file(self.input_file)
		self.config_obj = copy.deepcopy(self.base_config)
		app_state = load_app_state()
		last_file = app_state.get("last_file", "")

		candidate_path = ""
		if last_file and os.path.isfile(last_file):
			candidate_path = last_file
		else:
			cfg_path = self._resolve_graph_path_from_config(self.base_config)
			if cfg_path and os.path.isfile(cfg_path):
				candidate_path = os.path.abspath(cfg_path)

		if candidate_path:
			self.load_graph_file(candidate_path)
		else:
			self._append_console_text(
				"No GraphML file found to auto-load.\n"
				"Use 'Open File...' or configure your file in Settings.\n\n"
			)
			self._update_button_states()
			if config_created or not self.base_config.file_name:
				self.open_config_dialog()

	def _resolve_graph_path_from_config(self, cfg: Config) -> str:
		if not cfg.file_name:
			return ""
		if '/' in cfg.file_name or '\\' in cfg.file_name or os.path.isabs(cfg.file_name):
			return cfg.file_name if cfg.file_name.endswith('.graphml') else cfg.file_name + '.graphml'
		return os.path.join(cfg.folder_path, cfg.file_name + ('' if cfg.file_name.endswith('.graphml') else '.graphml'))

	def _resolve_effective_config(self, filepath: str):
		norm_path = os.path.abspath(filepath)
		saved_dict = load_graph_config(norm_path) or {}
		local_overrides = {k: v for k, v in saved_dict.items() if k in GRAPH_SETTING_KEYS}
		return build_effective_config(self.base_config, local_overrides, norm_path), local_overrides

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
			else (
				self.base_config.folder_path
				if os.path.isdir(self.base_config.folder_path)
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
		self.lbl_status.configure(text="Loading & generating HTML...")
		self.lbl_file.configure(text=f"Loading: {os.path.basename(norm_path)}")
		self._update_button_states()

		record_recent_file(norm_path)
		self._refresh_recent_menu()

		cfg_snapshot = copy.deepcopy(self.config_obj)
		self._append_console_text(f"\nLoading: {norm_path}\n")

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
		def on_apply(new_base: Config, new_local: dict, mode: str = "session", sync_folder: str = None):
			self.base_config = new_base
			self.local_overrides = new_local

			if mode == "save":
				try:
					if sync_folder is not None:
						set_sync_folder(sync_folder)
					save_config_file(self.input_file, new_base)
					if self.current_graph_path:
						save_graph_config(self.current_graph_path, new_local)
				except Exception as exc:
					messagebox.showerror("Save Error", f"Could not save configuration:\n{exc}", parent=self)
					return

			if self.current_graph_path and os.path.isfile(self.current_graph_path):
				effective = build_effective_config(self.base_config, self.local_overrides, self.current_graph_path)
				self.load_graph_file(
					self.current_graph_path,
					override_config=effective,
					override_local=self.local_overrides,
				)
			else:
				self.config_obj = copy.deepcopy(self.base_config)
				target_path = self._resolve_graph_path_from_config(self.base_config)
				if target_path and os.path.isfile(target_path):
					self.load_graph_file(target_path)

		ConfigDialog(
			self,
			self.base_config,
			self.local_overrides,
			self.input_file,
			on_apply,
			current_graph_path=self.current_graph_path,
			on_open_file_callback=self.open_specific_file,
		)

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
		self.focus_set()

		ctx_ref = self.ctx
		prepared_ref = self.prepared_game_data

		def on_stats(stats_dict: dict):
			self.output_queue.put(("stats", (session, stats_dict)))

		def on_graph(diagram_data: GraphDiagramData):
			self.output_queue.put(("graph", (session, diagram_data)))

		def on_answer_output(text: str, highlight: AnswerHighlight):
			self.output_queue.put(("answer_line", (session, text, highlight)))

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
					on_graph_update=on_graph,
					on_answer_output=on_answer_output
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
	# Circular Graph Panel Rendering
	# ------------------------------------------------------------------
	def _update_graph_panel(self, diagram_data: GraphDiagramData):
		self.current_diagram = diagram_data
		self._redraw_graph_canvas()

	def _redraw_graph_canvas(self):
		canvas = getattr(self, "graph_canvas", None)
		if canvas is None:
			return
		canvas.delete("all")
		w = canvas.winfo_width()
		h = canvas.winfo_height()
		if w < 40 or h < 40:
			return

		diagram = self.current_diagram
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

		font_spec = ("Segoe UI", 10)
		max_text_w = max(80, min(140, int(w * 0.28)))
		node_sizes = {}
		for node in diagram.nodes:
			tid = canvas.create_text(0, 0, text=node.label, font=font_spec, width=max_text_w, justify=tk.CENTER)
			bbox = canvas.bbox(tid)
			canvas.delete(tid)
			tw = (bbox[2] - bbox[0]) if bbox else 60
			th = (bbox[3] - bbox[1]) if bbox else 20
			node_sizes[node.node_id] = (max(60.0, tw + 20.0), max(32.0, th + 12.0))

		rects = compute_circular_layout(diagram, float(w), float(h), node_sizes, margin=16.0, flip_y=False)
		edges_geom = compute_edge_geometry(diagram, rects, parallel_offset=7.0, target_pad=1.0)

		for edge, x1, y1, x2, y2, _ux, _uy in edges_geom:
			canvas.create_line(
				x1,
				y1,
				x2,
				y2,
				fill=edge.color,
				width=1.8,
				arrow=tk.LAST,
				arrowshape=(10, 12, 4.5),
			)

		for node in diagram.nodes:
			cx, cy, nw, nh = rects[node.node_id]
			canvas.create_rectangle(
				cx - nw / 2.0,
				cy - nh / 2.0,
				cx + nw / 2.0,
				cy + nh / 2.0,
				fill=node.fill_color,
				outline="#000000",
				width=1.4,
			)
			canvas.create_text(
				cx,
				cy,
				text=node.label,
				fill=node.text_color,
				font=font_spec,
				width=max_text_w,
				justify=tk.CENTER,
			)

	# ------------------------------------------------------------------
	# Terminal-like Console Widget Handling
	# ------------------------------------------------------------------
	def clear_console(self):
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
		if event.state & 0x4:
			return None
		if event.keysym in (
			"Left", "Right", "Up", "Down", "Prior", "Next", "Home", "End",
			"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
			"Escape", "Tab", "F5"
		):
			return None

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
					self._update_graph_panel(None)
					self._append_console_text("Press Enter, Space, or click 'Start Game' to begin.\n")
					self._update_button_states()
					self.focus_set()

				elif kind == "html_done":
					self.last_html_path = payload or self.last_html_path
					self.is_busy = False
					self.lbl_status.configure(text="Ready")
					self._update_button_states()

				elif kind == "load_error":
					self.is_busy = False
					self.prepared_game_data = None
					self._update_progress_table(None)
					self._update_graph_panel(None)
					self.lbl_status.configure(text="Load Error")
					self._append_console_text(f"\nERROR: {payload}\n")
					self._update_button_states()
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

				elif kind == "graph":
					session, diagram_data = payload
					if session is self.active_session:
						self._update_graph_panel(diagram_data)

				elif kind == "answer_line":
					session, text, highlight = payload
					if session is self.active_session:
						self._append_answer_line(text, highlight)

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
			state=tk.NORMAL if (not self.is_busy and has_ctx) else tk.DISABLED,
		)
		self.btn_reveal.configure(state=tk.NORMAL if waiting else tk.DISABLED)

		if game_active:
			if self.btn_start_game.winfo_manager():
				self.btn_start_game.pack_forget()
			if not self.btn_reveal.winfo_manager():
				self.btn_reveal.pack(side=tk.LEFT, padx=(0, 6))
		else:
			if self.btn_reveal.winfo_manager():
				self.btn_reveal.pack_forget()
			if not self.btn_start_game.winfo_manager():
				self.btn_start_game.pack(side=tk.LEFT, padx=(0, 6))

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

	def _on_key_enter_or_space(self, event=None):
		if self.active_session and self.active_session.waiting_for_input:
			self.send_reveal_next()
			return "break"
		if not self.is_busy and self.ctx and self.active_session is None:
			self.start_game()
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

		active_hl = self.active_highlight
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
			line_count = wrapped.count('\n') + 1
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
				arrow=tk.LAST,
				arrowshape=(10, 12, 4.5),
			)

		# 2. Highlighted edge glow + crisp highlighted arrow
		for edge, x1, y1, x2, y2, ux, uy in highlighted_edges:
			gx2 = x2 - ux * 10.0
			gy2 = y2 - uy * 10.0
			for gw, alpha in ((12.0, 0.24), (7.0, 0.48)):
				canvas.create_line(
					x1, y1, gx2, gy2,
					fill=blend_hex_with_white(edge.color, alpha),
					width=gw,
					capstyle=tk.ROUND,
				)
			canvas.create_line(
				x1, y1, x2, y2,
				fill=edge.color,
				width=3.0,
				arrow=tk.LAST,
				arrowshape=(12, 15, 5.5),
			)

		# 3. Highlighted node glow behind node boxes
		for node in diagram.nodes:
			if node.node_id not in hl_nodes:
				continue
			cx, cy, nw, nh = rects[node.node_id]
			for pad, alpha in ((16.0, 0.28), (10.0, 0.50), (5.0, 0.78)):
				canvas.create_rectangle(
					cx - (nw + pad) / 2.0,
					cy - (nh + pad) / 2.0,
					cx + (nw + pad) / 2.0,
					cy + (nh + pad) / 2.0,
					fill=blend_hex_with_white(node.fill_color, alpha),
					outline="",
				)

		# 4. Node boxes & labels
		for node in diagram.nodes:
			cx, cy, nw, nh = rects[node.node_id]
			is_hl = node.node_id in hl_nodes
			canvas.create_rectangle(
				cx - nw / 2.0,
				cy - nh / 2.0,
				cx + nw / 2.0,
				cy + nh / 2.0,
				fill=node.fill_color,
				outline="#000000",
				width=2.2 if is_hl else 1.4,
			)
			canvas.create_text(
				cx,
				cy,
				text=wrapped_labels[node.node_id],
				fill=node.text_color,
				font=node_fonts[node.node_id],
				justify=tk.CENTER,
			)

		# 5. Cycle plus/minus icon in the middle of the path
		if active_hl is not None and active_hl.is_cycle and active_hl.cycle_polarity in (1, -1):
			center = compute_cycle_center(active_hl, rects)
			if center is not None:
				mid_x, mid_y = center
				icon_sz = max(36, min(64, int(min(w, h) * 0.18)))
				photo = self._load_tk_cycle_icon(active_hl.cycle_polarity, icon_sz)
				if photo is not None:
					canvas.create_image(mid_x, mid_y, image=photo)
				else:
					r_bg = icon_sz * 0.46
					badge_col = "#1DB954" if active_hl.cycle_polarity > 0 else "#E53935"
					canvas.create_oval(
						mid_x - r_bg, mid_y - r_bg,
						mid_x + r_bg, mid_y + r_bg,
						fill="#FFFFFF",
						outline=badge_col,
						width=3.0,
					)
					arm = r_bg * 0.56
					thick = max(4.0, r_bg * 0.24)
					canvas.create_line(
						mid_x - arm, mid_y, mid_x + arm, mid_y,
						fill=badge_col, width=thick, capstyle=tk.ROUND,
					)
					if active_hl.cycle_polarity > 0:
						canvas.create_line(
							mid_x, mid_y - arm, mid_x, mid_y + arm,
							fill=badge_col, width=thick, capstyle=tk.ROUND,
						)

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
			self.console.tag_bind(tag_name, "<Leave>", lambda _e, t=tag_name: self._set_hovered_answer_tag(
				None) if self._hovered_answer_tag == t else None)

		self.console.configure(state=tk.DISABLED)
		self.console.see("end-1c")