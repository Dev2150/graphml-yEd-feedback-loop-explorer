import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from src.app_controller import AppController
from src.config import Config, build_effective_config
from src.explorer import SINGLE_NODE_MODES
from src.storage import (
	clear_recent_files,
	get_local_data_dir,
	get_show_progress,
	load_app_state,
	set_show_progress,
)
from src.ui.desktop.config_dialog import ConfigDialog
from src.ui.desktop.console_widget import InteractiveConsole
from src.ui.desktop.graph_canvas import TkCircularGraphCanvas
from src.ui.desktop.progress_panel import ProgressPanel


class GraphMLExplorerApp(tk.Tk):
	def __init__(self, input_file: str, output_folder: str):
		super().__init__()
		self.title("GraphML Feedback Loop Explorer")
		self.geometry("1220x760")
		self.minsize(880, 540)

		self.controller = AppController(input_file, output_folder)
		self._progress_visible: bool = get_show_progress()

		self._explorer_mode: bool = False
		self._explorer_case: str = "neighborhood"
		self._last_single_explorer_case: str = "neighborhood"
		self._explorer_nodes: list = []
		self._display_to_node_id: dict = {}
		self._node_id_to_display: dict = {}
		self._updating_explorer_ui: bool = False

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
		tools_menu.add_command(
			label="Open Current GraphML (yEd)",
			accelerator="Ctrl+G",
			command=self.open_current_graphml,
		)
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
		game_menu.add_separator()
		game_menu.add_command(label="Toggle Explorer Mode", command=self.toggle_explorer_mode)
		self.menubar.add_cascade(label="Game", menu=game_menu)

		self.config(menu=self.menubar)
		self._refresh_recent_menu()

	def _build_layout(self):
		toolbar = ttk.Frame(self, padding=(8, 6))
		toolbar.pack(fill=tk.X)

		self.btn_open = ttk.Button(toolbar, text="📂 Open File...", command=self.open_file_dialog, takefocus=0)
		self.btn_open.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_open_graphml = ttk.Button(
			toolbar,
			text="📄 Open GraphML",
			command=self.open_current_graphml,
			state=tk.DISABLED,
			takefocus=0,
		)
		self.btn_open_graphml.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_reload = ttk.Button(toolbar, text="🔄 Reload", command=self.reload_current_file, takefocus=0)
		self.btn_reload.pack(side=tk.LEFT, padx=(0, 12))

		self.btn_open_html = ttk.Button(
			toolbar,
			text="🌐 Open HTML",
			command=self.open_generated_html,
			state=tk.DISABLED,
			takefocus=0,
		)
		self.btn_open_html.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_open_folder = ttk.Button(toolbar, text="📁 Open HTML Folder", command=self.open_html_folder, takefocus=0)
		self.btn_open_folder.pack(side=tk.LEFT, padx=(0, 6))

		self.btn_regen = ttk.Button(toolbar, text="🔄 Regenerate HTML", command=self.regenerate_html, takefocus=0)
		self.btn_regen.pack(side=tk.LEFT, padx=(0, 6))

		ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=(4, 10))

		self.btn_mode_switch = ttk.Button(
			toolbar,
			text="🧭 Explorer Mode",
			command=self.toggle_explorer_mode,
			state=tk.DISABLED,
			takefocus=0,
		)
		self.btn_mode_switch.pack(side=tk.LEFT, padx=(0, 8))

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

		# --- Explorer Bar (hidden until Explorer Mode is toggled on) ---
		self.explorer_bar = ttk.LabelFrame(self, text="Graph Explorer", padding=(8, 4))

		row_nodes = ttk.Frame(self.explorer_bar)
		row_nodes.pack(fill=tk.X, pady=(0, 4))

		ttk.Label(row_nodes, text="Node A:").pack(side=tk.LEFT, padx=(0, 4))
		self.var_explorer_a = tk.StringVar()
		self.cmb_explorer_a = ttk.Combobox(row_nodes, textvariable=self.var_explorer_a, width=26)
		self.cmb_explorer_a.pack(side=tk.LEFT, fill=tk.X, expand=True)
		ttk.Button(row_nodes, text="✕", width=3, command=lambda: self._clear_explorer_slot("a"), takefocus=0).pack(
			side=tk.LEFT, padx=(2, 6)
		)

		ttk.Button(row_nodes, text="⇄", width=3, command=self._swap_explorer_nodes, takefocus=0).pack(
			side=tk.LEFT, padx=(0, 6)
		)

		ttk.Label(row_nodes, text="Node B:").pack(side=tk.LEFT, padx=(0, 4))
		self.var_explorer_b = tk.StringVar()
		self.cmb_explorer_b = ttk.Combobox(row_nodes, textvariable=self.var_explorer_b, width=26)
		self.cmb_explorer_b.pack(side=tk.LEFT, fill=tk.X, expand=True)
		ttk.Button(row_nodes, text="✕", width=3, command=lambda: self._clear_explorer_slot("b"), takefocus=0).pack(
			side=tk.LEFT, padx=(2, 0)
		)

		row_cases = ttk.Frame(self.explorer_bar)
		row_cases.pack(fill=tk.X)

		ttk.Label(row_cases, text="Case:").pack(side=tk.LEFT, padx=(0, 6))
		self.var_explorer_case = tk.StringVar(value=self._explorer_case)
		self._explorer_case_buttons = {}
		for case_val, case_lbl in (
			("dual", "Dual (A ↔ B)"),
			("descendants", "Descendants (A →)"),
			("ascendants", "Ascendants (→ A)"),
			("neighborhood", "Neighborhood"),
		):
			rb = ttk.Radiobutton(
				row_cases,
				text=case_lbl,
				value=case_val,
				variable=self.var_explorer_case,
				command=self._on_explorer_case_clicked,
				takefocus=0,
			)
			rb.pack(side=tk.LEFT, padx=(0, 10))
			self._explorer_case_buttons[case_val] = rb

		ttk.Label(row_cases, text="Depth:").pack(side=tk.LEFT, padx=(8, 4))
		self.var_explorer_depth = tk.StringVar(value="3")
		self.cmb_explorer_depth = ttk.Combobox(
			row_cases,
			textvariable=self.var_explorer_depth,
			values=["1", "2", "3", "4", "5", "6", "All"],
			state="readonly",
			width=6,
		)
		self.cmb_explorer_depth.pack(side=tk.LEFT, padx=(0, 8))
		self.cmb_explorer_depth.bind("<<ComboboxSelected>>", lambda _e: self._run_explorer())

		self.btn_explore_run = ttk.Button(row_cases, text="Explore", command=self._run_explorer, takefocus=0)
		self.btn_explore_run.pack(side=tk.LEFT)

		self.lbl_explorer_hint = ttk.Label(
			row_cases,
			text="Right-click a node to jump",
			foreground="#555555",
			font=("Segoe UI", 8, "italic"),
		)
		self.lbl_explorer_hint.pack(side=tk.RIGHT)

		self._bind_explorer_combobox(self.cmb_explorer_a, self.var_explorer_a, "a")
		self._bind_explorer_combobox(self.cmb_explorer_b, self.var_explorer_b, "b")

		# --- Main Split Pane ---
		self.main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
		self.main_pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

		left_pane = ttk.Frame(self.main_pane)
		self.main_pane.add(left_pane, weight=3)

		self.progress_panel = ProgressPanel(left_pane)
		if self._progress_visible:
			self.progress_panel.pack(fill=tk.X, pady=(0, 6))

		self.console = InteractiveConsole(
			left_pane,
			on_answer_hover=lambda hl: self.graph_canvas.set_highlight(hl),
		)
		self.console.pack(fill=tk.BOTH, expand=True)

		graph_panel = ttk.LabelFrame(self.main_pane, text="Relationship Graph", padding=6)
		self.main_pane.add(graph_panel, weight=2)

		self.lbl_graph_title = ttk.Label(
			graph_panel,
			text="Reveal an answer to view graph",
			font=("Segoe UI", 9, "bold"),
		)
		self.lbl_graph_title.pack(anchor="w", pady=(0, 4))

		self.graph_canvas = TkCircularGraphCanvas(
			graph_panel,
			on_title_change=lambda title: self.lbl_graph_title.configure(text=title),
			on_cycle_hover=self.console.highlight_cycle_edges,
			on_cycle_hover_clear=self.console.clear_cycle_highlights,
			on_answer_select=self.console.highlight_answer,
		)
		self.graph_canvas.pack(fill=tk.BOTH, expand=True)

	def _bind_shortcuts(self):
		self.bind("<Control-o>", lambda e: self.open_file_dialog())
		self.bind("<Control-O>", lambda e: self.open_file_dialog())
		self.bind("<Control-h>", lambda e: self.open_generated_html())
		self.bind("<Control-H>", lambda e: self.open_generated_html())
		self.bind("<Control-g>", lambda e: self.open_current_graphml())
		self.bind("<Control-G>", lambda e: self.open_current_graphml())
		self.bind("<Control-Shift-O>", lambda e: self.open_html_folder())
		self.bind("<Control-comma>", lambda e: self.open_config_dialog())
		self.bind("<F5>", lambda e: self.reload_current_file())
		self.bind("<Return>", self._on_key_enter_or_space)
		self.bind("<KP_Enter>", self._on_key_enter_or_space)
		self.bind("<space>", self._on_key_enter_or_space)
		self.bind("1", self._on_key_start)
		self.bind("0", self._on_key_stop)

	# ------------------------------------------------------------------
	# Explorer Mode Controls & Node Selection
	# ------------------------------------------------------------------
	def _bind_explorer_combobox(self, combo: ttk.Combobox, var: tk.StringVar, slot: str):
		def _restore_all(_event=None):
			all_vals = [disp for _, disp in self._explorer_nodes]
			if list(combo["values"]) != all_vals:
				combo["values"] = all_vals

		def _on_key(event):
			if event.keysym in ("Up", "Down", "Left", "Right", "Return", "KP_Enter", "Tab", "Escape"):
				return
			q = var.get().strip().lower()
			all_vals = [disp for _, disp in self._explorer_nodes]
			combo["values"] = [d for d in all_vals if q in d.lower()] if q else all_vals

		def _on_select(_event=None):
			if self._updating_explorer_ui:
				return
			self._on_explorer_node_changed(slot)

		combo.bind("<FocusIn>", _restore_all)
		combo.bind("<Button-1>", _restore_all)
		combo.bind("<KeyRelease>", _on_key)
		combo.bind("<<ComboboxSelected>>", _on_select)
		combo.bind("<Return>", _on_select)
		combo.bind("<KP_Enter>", _on_select)

	def _refresh_explorer_node_choices(self):
		prev_a = self._display_to_node_id.get(self.var_explorer_a.get().strip())
		prev_b = self._display_to_node_id.get(self.var_explorer_b.get().strip())

		self._explorer_nodes = []
		self._display_to_node_id = {}
		self._node_id_to_display = {}

		if self.controller.ctx:
			nodes = self.controller.ctx.nodes
			counts: dict[str, int] = {}
			for label in nodes.values():
				key = str(label).lower()
				counts[key] = counts.get(key, 0) + 1

			sorted_items = sorted(nodes.items(), key=lambda kv: (str(kv[1]).lower(), str(kv[0])))
			for nid, label in sorted_items:
				disp = str(label) if counts.get(str(label).lower(), 0) <= 1 else f"{label} [{nid}]"
				self._explorer_nodes.append((nid, disp))
				self._display_to_node_id[disp] = nid
				self._node_id_to_display[nid] = disp

			default_depth = max(1, self.controller.ctx.config.max_indirectness + 1)
			self.var_explorer_depth.set(str(default_depth) if default_depth <= 6 else "All")

		all_vals = [disp for _, disp in self._explorer_nodes]
		self.cmb_explorer_a["values"] = all_vals
		self.cmb_explorer_b["values"] = all_vals

		self._updating_explorer_ui = True
		try:
			self.var_explorer_a.set(self._node_id_to_display.get(prev_a, ""))
			self.var_explorer_b.set(self._node_id_to_display.get(prev_b, ""))
		finally:
			self._updating_explorer_ui = False

	def _get_selected_explorer_ids(self):
		a_txt = self.var_explorer_a.get().strip()
		b_txt = self.var_explorer_b.get().strip()
		nid_a = self._display_to_node_id.get(a_txt)
		nid_b = self._display_to_node_id.get(b_txt)
		if nid_a is None and a_txt:
			low = a_txt.lower()
			nid_a = next((nid for nid, disp in self._explorer_nodes if disp.lower() == low), None)
		if nid_b is None and b_txt:
			low = b_txt.lower()
			nid_b = next((nid for nid, disp in self._explorer_nodes if disp.lower() == low), None)
		return nid_a, nid_b

	def _parse_explorer_depth(self):
		raw = self.var_explorer_depth.get().strip()
		if raw.lower() == "all":
			return 0
		try:
			return max(1, int(raw))
		except ValueError:
			return 3

	def toggle_explorer_mode(self):
		if self.controller.is_busy or not self.controller.ctx:
			return
		self._set_explorer_mode(not self._explorer_mode)

	def _set_explorer_mode(self, enabled: bool):
		if self._explorer_mode == enabled:
			return
		self._explorer_mode = enabled

		if enabled:
			self.controller.cancel_active_game()
			self.btn_mode_switch.configure(text="🎮 Game Mode")
			self.progress_panel.pack_forget()
			self.explorer_bar.pack(fill=tk.X, padx=8, pady=(2, 6), before=self.main_pane)
			self.console.clear()
			self.graph_canvas.set_diagram(None)
			self._refresh_explorer_node_choices()
			self._sync_explorer_right_click()
			self._update_button_states()

			nid_a, nid_b = self._get_selected_explorer_ids()
			if nid_a or nid_b:
				self._run_explorer()
			else:
				self.console.append_text(
					"Explorer Mode:\n"
					"  • Pick Node A and Node B for Dual mode (A ↔ B, as if answering A → X → B).\n"
					"  • Pick only one node for Descendants, Ascendants, or Neighborhood.\n"
					"  • Right-click any node in single-node modes to jump to it.\n"
				)
		else:
			self.btn_mode_switch.configure(text="🧭 Explorer Mode")
			self.explorer_bar.pack_forget()
			self.graph_canvas.set_on_node_right_click(None)
			if self._progress_visible:
				self.progress_panel.pack(fill=tk.X, pady=(0, 6), before=self.console)
			self.console.clear()
			self.graph_canvas.set_diagram(None)
			self.lbl_status.configure(text="Ready" if self.controller.ctx else "Idle")
			self._update_button_states()
			if self.controller.ctx:
				self.console.append_text("Press Enter, Space, or click 'Start Game' to begin.\n")
			self.focus_set()

	def _sync_explorer_right_click(self):
		if self._explorer_mode and self._explorer_case in SINGLE_NODE_MODES:
			self.graph_canvas.set_on_node_right_click(self._on_explorer_node_right_click)
			self.lbl_explorer_hint.configure(text="Right-click a node to jump")
		else:
			self.graph_canvas.set_on_node_right_click(None)
			self.lbl_explorer_hint.configure(text="")

		is_dir = self._explorer_case in ("descendants", "ascendants")
		self.cmb_explorer_depth.configure(state="readonly" if is_dir else tk.DISABLED)

	def _on_explorer_node_changed(self, _slot: str):
		nid_a, nid_b = self._get_selected_explorer_ids()
		if nid_a and nid_b and nid_a != nid_b:
			self._explorer_case = "dual"
		elif (nid_a or nid_b) and self._explorer_case == "dual":
			self._explorer_case = self._last_single_explorer_case
		self.var_explorer_case.set(self._explorer_case)
		self._sync_explorer_right_click()
		if nid_a or nid_b:
			self._run_explorer()
		else:
			self.console.clear()
			self.graph_canvas.set_diagram(None)

	def _on_explorer_case_clicked(self):
		chosen = self.var_explorer_case.get()
		if chosen in SINGLE_NODE_MODES:
			self._last_single_explorer_case = chosen
			nid_a, nid_b = self._get_selected_explorer_ids()
			if nid_a and nid_b:
				self._updating_explorer_ui = True
				try:
					self.var_explorer_b.set("")
				finally:
					self._updating_explorer_ui = False
		self._explorer_case = chosen
		self._sync_explorer_right_click()
		nid_a, nid_b = self._get_selected_explorer_ids()
		if chosen == "dual" and not (nid_a and nid_b):
			self.console.clear()
			self.console.append_text("Select both Node A and Node B for Dual exploration.\n")
			self.graph_canvas.set_diagram(None)
			return
		if nid_a or nid_b:
			self._run_explorer()

	def _clear_explorer_slot(self, slot: str):
		self._updating_explorer_ui = True
		try:
			if slot == "a":
				self.var_explorer_a.set("")
			else:
				self.var_explorer_b.set("")
		finally:
			self._updating_explorer_ui = False
		self._on_explorer_node_changed(slot)

	def _swap_explorer_nodes(self):
		a_val = self.var_explorer_a.get()
		b_val = self.var_explorer_b.get()
		self._updating_explorer_ui = True
		try:
			self.var_explorer_a.set(b_val)
			self.var_explorer_b.set(a_val)
		finally:
			self._updating_explorer_ui = False
		nid_a, nid_b = self._get_selected_explorer_ids()
		if nid_a or nid_b:
			self._run_explorer()

	def _on_explorer_node_right_click(self, node_id: str, diagram):
		if not self._explorer_mode or self._explorer_case not in SINGLE_NODE_MODES:
			return
		target_id = node_id
		if diagram is not None and node_id in getattr(diagram, "merged_nodes", {}):
			target_id = diagram.merged_nodes[node_id][0]
		if target_id not in self._node_id_to_display:
			return
		self._updating_explorer_ui = True
		try:
			self.var_explorer_a.set(self._node_id_to_display[target_id])
			self.var_explorer_b.set("")
		finally:
			self._updating_explorer_ui = False
		self._run_explorer()

	def _run_explorer(self):
		if not self._explorer_mode or not self.controller.ctx:
			return
		nid_a, nid_b = self._get_selected_explorer_ids()
		if nid_a and nid_b and nid_a != nid_b and self._explorer_case != "dual":
			self._explorer_case = "dual"
			self.var_explorer_case.set("dual")
		elif (nid_a or nid_b) and not (nid_a and nid_b) and self._explorer_case == "dual":
			self._explorer_case = self._last_single_explorer_case
			self.var_explorer_case.set(self._explorer_case)
		self._sync_explorer_right_click()

		try:
			res = self.controller.explore(
				mode=self._explorer_case,
				node_a_id=nid_a,
				node_b_id=nid_b,
				max_depth=self._parse_explorer_depth(),
			)
		except ValueError as exc:
			self.console.clear()
			self.console.append_text(f"{exc}\n")
			self.graph_canvas.set_diagram(None)
			return

		self.console.clear()
		self.console.append_text(f"{res.title}\n")
		for text, hl in res.answer_lines:
			self.console.append_answer_line(text, hl)
		self.graph_canvas.set_diagram(res.diagram)
		self.lbl_status.configure(text=f"Explorer: {res.mode.capitalize()}")

	# ------------------------------------------------------------------
	# Startup & Recent Files Menu
	# ------------------------------------------------------------------
	def _startup(self):
		config_created, candidate_path = self.controller.initialize_startup()
		if candidate_path:
			self.load_graph_file(candidate_path)
		else:
			self.console.append_text(
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
		self.console.append_text(f"\nLoading: {norm_path}\n")

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
		if self._explorer_mode:
			self._set_explorer_mode(False)
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
			self.console.append_text("\n")
			self._update_button_states()
			self.focus_set()

	def send_stop_game(self):
		res = self.controller.send_stop_game()
		if res == "sent_quit":
			self.console.append_text("0\n")
			self._update_button_states()
			self.focus_set()
		elif res == "cancelled":
			self.console.append_text("\nGame stopped.\n")
			self.lbl_status.configure(text="Ready")
			self._update_button_states()

	# ------------------------------------------------------------------
	# Queue Polling & UI State
	# ------------------------------------------------------------------
	def _poll_output_queue(self):
		for kind, payload in self.controller.poll_events():
			if kind == "text":
				if not self._explorer_mode:
					self.console.append_text(payload)

			elif kind == "loaded":
				ctx, _html_path, norm_path, _prepared, stats = payload
				conn_mode = ctx.config.connection_type
				self.title(f"GraphML Feedback Loop Explorer — {os.path.basename(norm_path)}")
				self.lbl_file.configure(
					text=f"{os.path.basename(norm_path)}  |  Nodes: {len(ctx.nodes)}  |  Edges: {len(ctx.edges)}  |  Mode: {conn_mode}"
				)
				self.progress_panel.update_stats(stats)
				self._refresh_explorer_node_choices()

				if self._explorer_mode:
					self._sync_explorer_right_click()
					nid_a, nid_b = self._get_selected_explorer_ids()
					if nid_a or nid_b:
						self._run_explorer()
					else:
						self.console.clear()
						self.graph_canvas.set_diagram(None)
						self.lbl_status.configure(text="Explorer Ready")
						self.console.append_text(
							"Explorer Mode:\n"
							"  • Pick Node A and Node B for Dual mode (A ↔ B, as if answering A → X → B).\n"
							"  • Pick only one node for Descendants, Ascendants, or Neighborhood.\n"
							"  • Right-click any node in single-node modes to jump to it.\n"
						)
				else:
					self.lbl_status.configure(text="Ready")
					self.graph_canvas.set_diagram(None)
					self.console.append_text("Press Enter, Space, or click 'Start Game' to begin.\n")
					self.focus_set()

				self._update_button_states()

			elif kind == "html_done":
				self.lbl_status.configure(text="Ready")
				self._update_button_states()

			elif kind == "load_error":
				self.progress_panel.update_stats(None)
				self.graph_canvas.set_diagram(None)
				self._refresh_explorer_node_choices()
				self.lbl_status.configure(text="Load Error")
				self.console.append_text(f"\nERROR: {payload}\n")
				self._update_button_states()
				messagebox.showerror(
					"Configuration / Load Error",
					f"{payload}\n\nOpening Configuration so you can adjust settings.",
					parent=self,
				)
				self.open_config_dialog()

			elif kind == "waiting_input":
				if not self._explorer_mode:
					self.lbl_status.configure(text="Game: Waiting for input" if payload else "Game: Processing...")
				self._update_button_states()

			elif kind == "game_finished":
				if not self._explorer_mode:
					self.lbl_status.configure(text="Ready")
					self.console.append_text("\nEnter '1' + Enter or click 'Start Game' to play again.\n")
				self._update_button_states()

			elif kind == "game_error":
				if not self._explorer_mode:
					self.lbl_status.configure(text="Game Error")
					self.console.append_text(f"\nGame Error: {payload}\n")
				self._update_button_states()

			elif kind == "stats":
				self.progress_panel.update_stats(payload)

			elif kind == "graph":
				if not self._explorer_mode:
					self.graph_canvas.set_diagram(payload)

			elif kind == "answer_line":
				if not self._explorer_mode:
					text, highlight = payload
					self.console.append_answer_line(text, highlight)

		self.after(40, self._poll_output_queue)

	def _update_button_states(self):
		c = self.controller
		has_ctx = c.ctx is not None
		has_html = bool(c.last_html_path and os.path.isfile(c.last_html_path))
		game_active = c.active_session is not None
		waiting = bool(game_active and c.active_session.waiting_for_input)
		has_graphml = bool(c.current_graph_path and os.path.isfile(c.current_graph_path))

		self.btn_open.configure(state=tk.DISABLED if c.is_busy else tk.NORMAL)
		self.btn_open_graphml.configure(state=tk.NORMAL if has_graphml else tk.DISABLED)
		self.btn_open_html.configure(state=tk.NORMAL if has_html else tk.DISABLED)
		self.btn_reload.configure(state=tk.NORMAL if (not c.is_busy and c.current_graph_path) else tk.DISABLED)
		self.btn_config.configure(state=tk.DISABLED if c.is_busy else tk.NORMAL)
		self.btn_regen.configure(state=tk.NORMAL if (not c.is_busy and has_ctx) else tk.DISABLED)
		self.btn_mode_switch.configure(state=tk.NORMAL if (not c.is_busy and has_ctx) else tk.DISABLED)
		self.btn_toggle_progress.configure(state=tk.DISABLED if self._explorer_mode else tk.NORMAL)

		self.btn_start_game.configure(state=tk.NORMAL if (not c.is_busy and has_ctx) else tk.DISABLED)
		self.btn_reveal.configure(state=tk.NORMAL if waiting else tk.DISABLED)

		if self._explorer_mode:
			if self.game_btn_slot.winfo_manager():
				self.game_btn_slot.pack_forget()
		else:
			if not self.game_btn_slot.winfo_manager():
				self.game_btn_slot.pack(side=tk.LEFT, after=self.btn_mode_switch)
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

	def _on_key_enter_or_space(self, event=None):
		if self._explorer_mode:
			return None
		if self.controller.active_session and self.controller.active_session.waiting_for_input:
			self.send_reveal_next()
			return "break"
		if not self.controller.is_busy and self.controller.ctx and self.controller.active_session is None:
			self.start_game()
			return "break"
		return None

	def _on_key_start(self, event=None):
		if self._explorer_mode:
			return None
		if not self.controller.is_busy and self.controller.ctx and self.controller.active_session is None:
			self.start_game()
			return "break"
		return None

	def _on_key_stop(self, event=None):
		if self._explorer_mode:
			return None
		if self.controller.active_session is not None:
			self.send_stop_game()
			return "break"
		return None

	def _toggle_progress(self):
		if self._explorer_mode:
			return
		self._progress_visible = not self._progress_visible
		set_show_progress(self._progress_visible)
		if self._progress_visible:
			self.progress_panel.pack(fill=tk.X, pady=(0, 6), before=self.console)
			self.btn_toggle_progress.configure(text="Hide Progress")
		else:
			self.progress_panel.pack_forget()
			self.btn_toggle_progress.configure(text="Show Progress")

	def open_current_graphml(self):
		graph_path = self.controller.current_graph_path
		if not graph_path or not os.path.isfile(graph_path):
			messagebox.showinfo("No GraphML Loaded", "Please open a GraphML file first.", parent=self)
			return
		try:
			if sys.platform.startswith("win"):
				os.startfile(graph_path)
			elif sys.platform == "darwin":
				subprocess.Popen(["open", graph_path])
			else:
				subprocess.Popen(["xdg-open", graph_path])
		except Exception as e:
			messagebox.showerror("Open GraphML Error", f"Could not open GraphML file:\n{e}", parent=self)