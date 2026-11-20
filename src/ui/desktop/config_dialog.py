import copy
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from src.app_controller import parse_graph_settings_dict
from src.config import Config, GRAPH_SETTING_KEYS
from src.progress_storage import get_sync_folder, get_local_data_dir


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
		add_check_pair("include_secondary_cycles", "Include Secondary Cycles", cfg.include_secondary_cycles, loc.get("include_secondary_cycles"))

		# ------------------------------------------------------------------
		# Tab 2: App Settings
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
		).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

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
		if "/" in fname or "\\" in fname or os.path.isabs(fname):
			target = fname if fname.endswith(".graphml") else fname + ".graphml"
		else:
			target = os.path.join(folder, fname + ("" if fname.endswith(".graphml") else ".graphml"))
		if not os.path.isfile(target):
			messagebox.showerror("File Not Found", f"Could not find file:\n{target}", parent=self)
			return
		self.destroy()
		self.on_open_file_callback(target)

	def _clear_all_local(self):
		for key, en_var in self.local_enabled_vars.items():
			en_var.set(False)
			self._update_local_row_state(key)

	@staticmethod
	def _collect_raw_graph_fields(vars_map: dict, excl_widget: tk.Text) -> dict:
		raw = {k: v.get() for k, v in vars_map.items()}
		raw["excluded_elements"] = excl_widget.get("1.0", tk.END)
		return raw

	def _build_configs(self):
		global_dict = parse_graph_settings_dict(
			self._collect_raw_graph_fields(self.global_vars, self.txt_global_excluded),
			"Global",
		)
		new_base = copy.deepcopy(self.base_config)
		new_base.folder_path = self.app_vars["folder_path"].get().strip()
		new_base.file_name = self.app_vars["file_name"].get().strip()
		for k, v in global_dict.items():
			setattr(new_base, k, v)

		new_local = {}
		if self.has_file:
			local_parsed = parse_graph_settings_dict(
				self._collect_raw_graph_fields(self.local_vars, self.txt_local_excluded),
				"Local",
			)
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
		current = self.app_vars["sync_folder"].get().strip()
		path = filedialog.askdirectory(
			parent=self,
			title="Select Default Sync Folder",
			initialdir=current if os.path.isdir(current) else os.getcwd(),
		)
		if path:
			self.app_vars["sync_folder"].set(path)

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
