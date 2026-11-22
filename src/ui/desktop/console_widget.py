import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from src.diagram import AnswerHighlight, GraphDiagramData


class InteractiveConsole(ttk.Frame):
	"""Read-only scrollable console with colored arrows and hover-highlighted answer rows."""

	def __init__(
		self,
		parent,
		on_answer_hover: Optional[Callable[[Optional[AnswerHighlight]], None]] = None,
	):
		super().__init__(parent)
		self._on_answer_hover = on_answer_hover

		self._hovered_answer_tag: Optional[str] = None
		self._answer_highlights: dict[str, AnswerHighlight] = {}
		self._answer_tag_seq: int = 0
		self._synced_console_tags: list[str] = []

		self.text = tk.Text(
			self,
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
		self.text.tag_configure("arrow_up", foreground="#6BCB77")
		self.text.tag_configure("arrow_down", foreground="#FF6B6B")
		self.text.bind("<Leave>", lambda _e: self._set_hovered_answer_tag(None))

		v_scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.text.yview)
		self.text.configure(yscrollcommand=v_scroll.set)
		self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

	def clear(self):
		self.clear_cycle_highlights()
		self._set_hovered_answer_tag(None)
		self._answer_highlights.clear()
		self.text.configure(state=tk.NORMAL)
		self.text.delete("1.0", tk.END)
		self.text.configure(state=tk.DISABLED)

	def append_text(self, text: str):
		self.text.configure(state=tk.NORMAL)
		start_idx = self.text.index("end-1c")
		self.text.insert("end-1c", text)
		self._tag_arrows(start_idx, text)
		self.text.configure(state=tk.DISABLED)
		self.text.see("end-1c")

	def append_answer_line(self, text: str, highlight: Optional[AnswerHighlight]):
		self.text.configure(state=tk.NORMAL)
		start_idx = self.text.index("end-1c")
		full_text = f"{text}\n"
		self.text.insert("end-1c", full_text)
		end_idx = self.text.index("end-2c")

		self._tag_arrows(start_idx, full_text)

		if highlight is not None:
			self._answer_tag_seq += 1
			tag_name = f"ans_hl_{self._answer_tag_seq}"
			self._answer_highlights[tag_name] = highlight
			self.text.tag_add(tag_name, start_idx, end_idx)
			self.text.tag_bind(tag_name, "<Enter>", lambda _e, t=tag_name: self._set_hovered_answer_tag(t))
			self.text.tag_bind(
				tag_name,
				"<Leave>",
				lambda _e, t=tag_name: self._set_hovered_answer_tag(None) if self._hovered_answer_tag == t else None,
			)

		self.text.configure(state=tk.DISABLED)
		self.text.see("end-1c")

	def highlight_cycle_edges(self, edge_key: frozenset, diagram: GraphDiagramData):
		self.clear_cycle_highlights()
		for tag_name, hl in self._answer_highlights.items():
			if hl.is_cycle and frozenset(hl.edges) == edge_key:
				if hl.diagram is None or hl.diagram is diagram:
					try:
						self.text.tag_configure(tag_name, background="#2B2E36")
						self._synced_console_tags.append(tag_name)
					except tk.TclError:
						pass

	def clear_cycle_highlights(self):
		for tag_name in self._synced_console_tags:
			if tag_name != self._hovered_answer_tag:
				try:
					self.text.tag_configure(tag_name, background="")
				except tk.TclError:
					pass
		self._synced_console_tags.clear()

	def _tag_arrows(self, start_idx: str, text: str):
		if "↗" not in text and "↘" not in text:
			return
		for ch, tag in (("↗", "arrow_up"), ("↘", "arrow_down")):
			offset = 0
			while True:
				pos = text.find(ch, offset)
				if pos == -1:
					break
				self.text.tag_add(
					tag,
					f"{start_idx} + {pos} chars",
					f"{start_idx} + {pos + 1} chars",
				)
				offset = pos + 1

	def _set_hovered_answer_tag(self, tag_name: Optional[str]):
		if self._hovered_answer_tag == tag_name:
			return
		prev = self._hovered_answer_tag
		if prev:
			try:
				self.text.tag_configure(prev, background="")
			except tk.TclError:
				pass

		self._hovered_answer_tag = tag_name
		if tag_name is not None:
			try:
				self.text.tag_configure(tag_name, background="#2B2E36")
			except tk.TclError:
				pass
			self.text.configure(cursor="hand2")
			hl = self._answer_highlights.get(tag_name)
		else:
			self.text.configure(cursor="arrow")
			hl = None

		if self._on_answer_hover is not None:
			self._on_answer_hover(hl)