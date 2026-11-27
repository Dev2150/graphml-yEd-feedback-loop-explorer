from typing import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from src.app_controller import AppController
from src.diagram import GraphDiagramData
from src.explorer import ExplorerResult, SINGLE_NODE_MODES


class AndroidExplorerBar(BoxLayout):
	"""Kivy Graph Explorer controls + node picker popup for Dual, Descendants, Ascendants, and Neighborhood modes."""

	def __init__(
		self,
		controller: AppController,
		on_track_popup: Callable[[Popup], None],
		on_result: Callable[[ExplorerResult], None],
		on_empty: Callable[[str], None],
		on_jump_handler_change: Callable[[bool], None],
		**kwargs,
	):
		kwargs.setdefault('orientation', 'vertical')
		kwargs.setdefault('size_hint_y', None)
		kwargs.setdefault('height', dp(76))
		kwargs.setdefault('spacing', dp(4))
		super().__init__(**kwargs)

		self.controller = controller
		self._on_track_popup = on_track_popup
		self._on_result = on_result
		self._on_empty = on_empty
		self._on_jump_handler_change = on_jump_handler_change

		self._active: bool = False
		self._case: str = 'neighborhood'
		self._last_single_case: str = 'neighborhood'
		self._node_a: str = ''
		self._node_b: str = ''
		self._updating_ui: bool = False

		self._build_ui()

	def _build_ui(self):
		exp_row1 = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
		self.btn_exp_a = Button(
			text='A: Pick...',
			font_size=dp(12),
			shorten=True,
			shorten_from='right',
			on_release=lambda *_: self._open_node_picker('a'),
		)
		self.btn_exp_a.bind(size=lambda inst, sz: setattr(inst, 'text_size', (max(0, sz[0] - dp(10)), None)))
		self.btn_exp_clear_a = Button(
			text='×',
			size_hint_x=None,
			width=dp(32),
			font_size=dp(14),
			on_release=lambda *_: self._clear_slot('a'),
		)
		self.btn_exp_swap = Button(
			text='⇄',
			size_hint_x=None,
			width=dp(36),
			font_size=dp(14),
			on_release=lambda *_: self._swap_nodes(),
		)
		self.btn_exp_b = Button(
			text='B: Pick...',
			font_size=dp(12),
			shorten=True,
			shorten_from='right',
			on_release=lambda *_: self._open_node_picker('b'),
		)
		self.btn_exp_b.bind(size=lambda inst, sz: setattr(inst, 'text_size', (max(0, sz[0] - dp(10)), None)))
		self.btn_exp_clear_b = Button(
			text='×',
			size_hint_x=None,
			width=dp(32),
			font_size=dp(14),
			on_release=lambda *_: self._clear_slot('b'),
		)
		for w in (self.btn_exp_a, self.btn_exp_clear_a, self.btn_exp_swap, self.btn_exp_b, self.btn_exp_clear_b):
			exp_row1.add_widget(w)

		exp_row2 = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(4))
		self._exp_case_btns = {}
		for case_val, case_lbl in (
			('dual', 'Dual'),
			('descendants', 'Desc'),
			('ascendants', 'Asc'),
			('neighborhood', 'Neigh'),
		):
			btn = Button(
				text=case_lbl,
				font_size=dp(12),
				on_release=lambda _b, c=case_val: self._select_case(c),
			)
			exp_row2.add_widget(btn)
			self._exp_case_btns[case_val] = btn

		self.sp_exp_depth = Spinner(
			text='3',
			values=('1', '2', '3', '4', '5', '6', 'All'),
			size_hint_x=None,
			width=dp(62),
			font_size=dp(12),
		)
		self.sp_exp_depth.bind(text=self._on_depth_changed)
		exp_row2.add_widget(self.sp_exp_depth)

		self.add_widget(exp_row1)
		self.add_widget(exp_row2)

	def has_selection(self) -> bool:
		return bool(self._node_a or self._node_b)

	def on_graph_loaded(self, ctx, active: bool):
		self._updating_ui = True
		try:
			if ctx is not None:
				default_depth = max(1, ctx.config.max_indirectness + 1)
				self.sp_exp_depth.text = str(default_depth) if default_depth <= 6 else 'All'
		finally:
			self._updating_ui = False
		self.sync_controls(ctx, active=active)

	def sync_controls(self, ctx, active: bool):
		self._active = active
		nodes = ctx.nodes if ctx else {}
		if self._node_a and self._node_a not in nodes:
			self._node_a = ''
		if self._node_b and self._node_b not in nodes:
			self._node_b = ''

		self.btn_exp_a.text = f"A: {nodes[self._node_a]}" if self._node_a else 'A: Pick...'
		self.btn_exp_b.text = f"B: {nodes[self._node_b]}" if self._node_b else 'B: Pick...'

		for case_val, btn in self._exp_case_btns.items():
			btn.background_color = (0.24, 0.48, 0.78, 1) if case_val == self._case else (0.34, 0.36, 0.40, 1)

		self.sp_exp_depth.disabled = self._case not in ('descendants', 'ascendants')
		self._on_jump_handler_change(bool(active and self._case in SINGLE_NODE_MODES))

	def _open_node_picker(self, slot: str):
		if not self.controller.ctx:
			return
		nodes = self.controller.ctx.nodes
		items = sorted(nodes.items(), key=lambda kv: (str(kv[1]).lower(), str(kv[0])))

		content = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))
		ti_search = TextInput(hint_text='Filter nodes...', multiline=False, size_hint_y=None, height=dp(38))
		content.add_widget(ti_search)

		sv = ScrollView(do_scroll_x=False)
		lst = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4))
		lst.bind(minimum_height=lst.setter('height'))
		sv.add_widget(lst)
		content.add_widget(sv)

		popup = Popup(title=f'Select Node {"A" if slot == "a" else "B"}', content=content, size_hint=(0.94, 0.86))

		def _choose(nid: str):
			popup.dismiss()
			if slot == 'a':
				self._node_a = nid
			else:
				self._node_b = nid
			if self._node_a and self._node_b and self._node_a != self._node_b:
				self._case = 'dual'
			elif (self._node_a or self._node_b) and self._case == 'dual':
				self._case = self._last_single_case
			self.sync_controls(self.controller.ctx, active=self._active)
			if self.has_selection():
				self.run_current()
			else:
				self._on_empty('')

		def _render(*_):
			lst.clear_widgets()
			q = ti_search.text.strip().lower()
			for nid, label in items:
				if q and q not in str(label).lower():
					continue
				btn = Button(
					text=str(label),
					size_hint_y=None,
					height=dp(40),
					halign='left',
					valign='middle',
					font_size=dp(13),
					on_release=lambda _b, node_id=nid: _choose(node_id),
				)
				btn.bind(size=lambda inst, sz: setattr(inst, 'text_size', (max(0, sz[0] - dp(12)), sz[1])))
				lst.add_widget(btn)

		ti_search.bind(text=_render)
		_render()

		btn_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
		btn_row.add_widget(Button(text='Clear', on_release=lambda *_: _choose('')))
		btn_row.add_widget(Button(text='Cancel', on_release=lambda *_: popup.dismiss()))
		content.add_widget(btn_row)
		self._on_track_popup(popup)

	def _clear_slot(self, slot: str):
		if slot == 'a':
			self._node_a = ''
		else:
			self._node_b = ''
		if self.has_selection() and self._case == 'dual':
			self._case = self._last_single_case
		self.sync_controls(self.controller.ctx, active=self._active)
		if self.has_selection():
			self.run_current()
		else:
			self._on_empty('')

	def _swap_nodes(self):
		self._node_a, self._node_b = self._node_b, self._node_a
		self.sync_controls(self.controller.ctx, active=self._active)
		if self.has_selection():
			self.run_current()

	def _select_case(self, case_val: str):
		if case_val in SINGLE_NODE_MODES:
			self._last_single_case = case_val
			if self._node_a and self._node_b:
				self._node_b = ''
		self._case = case_val
		self.sync_controls(self.controller.ctx, active=self._active)
		if case_val == 'dual' and not (self._node_a and self._node_b):
			self._on_empty('Select both Node A and Node B for Dual mode.\n')
			return
		if self.has_selection():
			self.run_current()

	def _on_depth_changed(self, _spinner, _text: str):
		if self._updating_ui:
			return
		if self._active and self._case in ('descendants', 'ascendants') and self.has_selection():
			self.run_current()

	def jump_to_node(self, node_id: str, diagram: GraphDiagramData):
		if not self._active or self._case not in SINGLE_NODE_MODES or not self.controller.ctx:
			return
		target_id = node_id
		if diagram is not None and node_id in getattr(diagram, 'merged_nodes', {}):
			target_id = diagram.merged_nodes[node_id][0]
		if target_id not in self.controller.ctx.nodes:
			return
		self._node_a = target_id
		self._node_b = ''
		self.sync_controls(self.controller.ctx, active=self._active)
		self.run_current()

	def run_current(self):
		if not self._active or not self.controller.ctx:
			return
		raw_depth = self.sp_exp_depth.text.strip()
		max_depth = 0 if raw_depth.lower() == 'all' else int(raw_depth)
		try:
			res = self.controller.explore(
				mode=self._case,
				node_a_id=self._node_a or None,
				node_b_id=self._node_b or None,
				max_depth=max_depth,
			)
		except Exception as exc:
			self._on_empty(f'{exc}\n')
			return

		self._on_result(res)