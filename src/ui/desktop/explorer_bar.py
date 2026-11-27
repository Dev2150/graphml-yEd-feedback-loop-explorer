import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from src.app_controller import AppController
from src.explorer import ExplorerResult, SINGLE_NODE_MODES


class ExplorerBar(ttk.LabelFrame):
	"""Desktop Graph Explorer controls for Dual, Descendants, Ascendants, and Neighborhood modes."""

	def __init__(
		self,
		parent,
		controller: AppController,
		on_result: Callable[[ExplorerResult], None],
		on_empty: Callable[[str], None],
		on_jump_handler_change: Callable[[bool], None],
		**kwargs,
	):
		kwargs.setdefault("text", "Graph Explorer")
		kwargs.setdefault("padding", (8, 4))
		super().__init__(parent, **kwargs)

		self.controller = controller
		self._on_result = on_result
		self._on_empty = on_empty
		self._on_jump_handler_change = on_jump_handler_change

		self._active: bool = False
		self._case: str = "neighborhood"
		self._last_single_case: str = "neighborhood"
		self._explorer_nodes: list = []
		self._display_to_node_id: dict = {}
		self._node_id_to_display: dict = {}
		self._updating_ui: bool = False
		self._last_explored_state = None

		self._build_ui()

	def _build_ui(self):
		row_nodes = ttk.Frame(self)
		row_nodes.pack(fill=tk.X, pady=(0, 4))

		ttk.Label(row_nodes, text="Node A:").pack(side=tk.LEFT, padx=(0, 4))
		self.var_explorer_a = tk.StringVar()
		self.cmb_explorer_a = ttk.Combobox(row_nodes, textvariable=self.var_explorer_a, width=26)
		self.cmb_explorer_a.pack(side=tk.LEFT, fill=tk.X, expand=True)
		ttk.Button(row_nodes, text="✕", width=3, command=lambda: self._clear_slot("a"), takefocus=0).pack(
			side=tk.LEFT, padx=(2, 6)
		)

		ttk.Button(row_nodes, text="⇄", width=3, command=self._swap_nodes, takefocus=0).pack(
			side=tk.LEFT, padx=(0, 6)
		)

		ttk.Label(row_nodes, text="Node B:").pack(side=tk.LEFT, padx=(0, 4))
		self.var_explorer_b = tk.StringVar()
		self.cmb_explorer_b = ttk.Combobox(row_nodes, textvariable=self.var_explorer_b, width=26)
		self.cmb_explorer_b.pack(side=tk.LEFT, fill=tk.X, expand=True)
		ttk.Button(row_nodes, text="✕", width=3, command=lambda: self._clear_slot("b"), takefocus=0).pack(
			side=tk.LEFT, padx=(2, 0)
		)

		row_cases = ttk.Frame(self)
		row_cases.pack(fill=tk.X)

		ttk.Label(row_cases, text="Case:").pack(side=tk.LEFT, padx=(0, 6))
		self.var_explorer_case = tk.StringVar(value=self._case)
		self._case_buttons = {}
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
				command=self._on_case_clicked,
				takefocus=0,
			)
			rb.pack(side=tk.LEFT, padx=(0, 10))
			self._case_buttons[case_val] = rb

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
		self.cmb_explorer_depth.bind("<<ComboboxSelected>>", lambda _e: self.run_current(force=True))

		self.lbl_explorer_hint = ttk.Label(
			row_cases,
			text="Right-click a node to jump",
			foreground="#555555",
			font=("Segoe UI", 8, "italic"),
		)
		self.lbl_explorer_hint.pack(side=tk.RIGHT)

		self._bind_combobox(self.cmb_explorer_a, self.var_explorer_a, "a")
		self._bind_combobox(self.cmb_explorer_b, self.var_explorer_b, "b")

	def _resolve_node_text(self, txt: str) -> Optional[str]:
		clean = txt.strip()
		if not clean:
			return None
		nid = self._display_to_node_id.get(clean)
		if nid is None:
			low = clean.lower()
			nid = next((node_id for node_id, disp in self._explorer_nodes if disp.lower() == low), None)
		return nid

	def _bind_combobox(self, combo: ttk.Combobox, var: tk.StringVar, slot: str):
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
			if self._updating_ui or not self._active:
				return
			self._on_node_changed(slot)

		def _on_var_write(*_args):
			if self._updating_ui or not self._active:
				return
			txt = var.get().strip()
			if txt == "" or self._resolve_node_text(txt) is not None:
				self._on_node_changed(slot)

		combo.bind("<FocusIn>", _restore_all)
		combo.bind("<Button-1>", _restore_all)
		combo.bind("<KeyRelease>", _on_key)
		combo.bind("<<ComboboxSelected>>", _on_select)
		combo.bind("<Return>", _on_select)
		combo.bind("<KP_Enter>", _on_select)
		var.trace_add("write", _on_var_write)

	def refresh_node_choices(self, ctx):
		prev_a = self._resolve_node_text(self.var_explorer_a.get())
		prev_b = self._resolve_node_text(self.var_explorer_b.get())

		self._explorer_nodes = []
		self._display_to_node_id = {}
		self._node_id_to_display = {}
		self._last_explored_state = None

		if ctx is not None:
			nodes = ctx.nodes
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

			default_depth = max(1, ctx.config.max_indirectness + 1)
			self.var_explorer_depth.set(str(default_depth) if default_depth <= 6 else "All")

		all_vals = [disp for _, disp in self._explorer_nodes]
		self.cmb_explorer_a["values"] = all_vals
		self.cmb_explorer_b["values"] = all_vals

		self._updating_ui = True
		try:
			self.var_explorer_a.set(self._node_id_to_display.get(prev_a, ""))
			self.var_explorer_b.set(self._node_id_to_display.get(prev_b, ""))
		finally:
			self._updating_ui = False

	def get_selected_ids(self):
		return (
			self._resolve_node_text(self.var_explorer_a.get()),
			self._resolve_node_text(self.var_explorer_b.get()),
		)

	def has_selection(self) -> bool:
		nid_a, nid_b = self.get_selected_ids()
		return bool(nid_a or nid_b)

	def _parse_depth(self) -> int:
		raw = self.var_explorer_depth.get().strip()
		if raw.lower() == "all":
			return 0
		try:
			return max(1, int(raw))
		except ValueError:
			return 3

	def sync_controls(self, active: bool):
		self._active = active
		jump_enabled = bool(active and self._case in SINGLE_NODE_MODES)
		self._on_jump_handler_change(jump_enabled)
		self.lbl_explorer_hint.configure(text="Right-click a node to jump" if jump_enabled else "")

		is_dir = self._case in ("descendants", "ascendants")
		self.cmb_explorer_depth.configure(state="readonly" if is_dir else tk.DISABLED)

	def _on_node_changed(self, _slot: str):
		nid_a, nid_b = self.get_selected_ids()
		if nid_a and nid_b and nid_a != nid_b:
			self._case = "dual"
		elif (nid_a or nid_b) and self._case == "dual":
			self._case = self._last_single_case
		self.var_explorer_case.set(self._case)
		self.sync_controls(self._active)
		if nid_a or nid_b:
			self.run_current()
		else:
			self._last_explored_state = None
			self._on_empty("")

	def _on_case_clicked(self):
		chosen = self.var_explorer_case.get()
		if chosen in SINGLE_NODE_MODES:
			self._last_single_case = chosen
			nid_a, nid_b = self.get_selected_ids()
			if nid_a and nid_b:
				self._updating_ui = True
				try:
					self.var_explorer_b.set("")
				finally:
					self._updating_ui = False
		self._case = chosen
		self.sync_controls(self._active)
		nid_a, nid_b = self.get_selected_ids()
		if chosen == "dual" and not (nid_a and nid_b):
			self._last_explored_state = None
			self._on_empty("Select both Node A and Node B for Dual exploration.\n")
			return
		if nid_a or nid_b:
			self.run_current(force=True)

	def _clear_slot(self, slot: str):
		self._updating_ui = True
		try:
			if slot == "a":
				self.var_explorer_a.set("")
			else:
				self.var_explorer_b.set("")
		finally:
			self._updating_ui = False
		self._on_node_changed(slot)

	def _swap_nodes(self):
		a_val = self.var_explorer_a.get()
		b_val = self.var_explorer_b.get()
		self._updating_ui = True
		try:
			self.var_explorer_a.set(b_val)
			self.var_explorer_b.set(a_val)
		finally:
			self._updating_ui = False
		if self.has_selection():
			self.run_current(force=True)

	def jump_to_node(self, node_id: str, diagram):
		if not self._active or self._case not in SINGLE_NODE_MODES:
			return
		target_id = node_id
		if diagram is not None and node_id in getattr(diagram, "merged_nodes", {}):
			target_id = diagram.merged_nodes[node_id][0]
		if target_id not in self._node_id_to_display:
			return
		self._updating_ui = True
		try:
			self.var_explorer_a.set(self._node_id_to_display[target_id])
			self.var_explorer_b.set("")
		finally:
			self._updating_ui = False
		self.run_current(force=True)

	def run_current(self, force: bool = False):
		if not self._active or not self.controller.ctx:
			return
		nid_a, nid_b = self.get_selected_ids()
		if nid_a and nid_b and nid_a != nid_b and self._case != "dual":
			self._case = "dual"
			self.var_explorer_case.set("dual")
		elif (nid_a or nid_b) and not (nid_a and nid_b) and self._case == "dual":
			self._case = self._last_single_case
			self.var_explorer_case.set(self._case)
		self.sync_controls(self._active)

		depth_val = self._parse_depth()
		state_key = (
			self._case,
			nid_a,
			nid_b,
			depth_val if self._case in ("descendants", "ascendants") else None,
		)
		if not force and state_key == self._last_explored_state:
			return
		self._last_explored_state = state_key

		try:
			res = self.controller.explore(
				mode=self._case,
				node_a_id=nid_a,
				node_b_id=nid_b,
				max_depth=depth_val,
			)
		except Exception as exc:
			self._on_empty(f"{exc}\n")
			return

		self._on_result(res)