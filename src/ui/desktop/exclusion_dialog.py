import os
import tkinter as tk
from tkinter import ttk

from src.io_graphml import list_graph_elements_and_groups


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
