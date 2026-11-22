import tkinter as tk
from tkinter import ttk
from typing import Optional


class ProgressPanel(ttk.LabelFrame):
	"""Collapsible Category Progress Treeview frame."""

	def __init__(self, parent, **kwargs):
		kwargs.setdefault("text", "Category Progress")
		kwargs.setdefault("padding", 8)
		super().__init__(parent, **kwargs)

		tier_bar = ttk.Frame(self)
		tier_bar.pack(fill=tk.X, pady=(0, 6))

		self.lbl_current_tier = ttk.Label(tier_bar, text="Current tier: —", font=("Segoe UI", 9, "bold"))
		self.lbl_current_tier.pack(side=tk.LEFT)

		self.lbl_total_progress = ttk.Label(tier_bar, text="", foreground="#555555", font=("Segoe UI", 9))
		self.lbl_total_progress.pack(side=tk.RIGHT)

		table_frame = ttk.Frame(self)
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

	def update_stats(self, stats: Optional[dict]):
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