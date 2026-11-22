from typing import Callable, Optional

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from src.diagram import AnswerHighlight

MAX_CONSOLE_LINES = 250


def format_console_markup(text: str) -> str:
	safe = text.replace('&', '&amp;').replace('[', '&bl;').replace(']', '&br;')
	# Replace emojis missing from DejaVuSans with colored ASCII badges
	safe = (
		safe.replace('🟦', '[color=#4DA6FF][B][/color]')
		.replace('🟥', '[color=#FF5C5C][R][/color]')
		.replace('💥', '[color=#FFB347]![/color]')
		.replace('⚖️', '[color=#66D9EF]=[/color]')
		.replace('⚖', '[color=#66D9EF]=[/color]')
		.replace('❤️', '[color=#FF6B6B]<3[/color]')
		.replace('↗', '[color=#6BCB77]↗[/color]')
		.replace('↘', '[color=#FF6B6B]↘[/color]')
	)
	return safe


class ConsoleAnswerLabel(Label):
	"""Seamless borderless console row that triggers on tap without blocking ScrollView drags."""

	def __init__(self, highlight: AnswerHighlight, on_tap, **kwargs):
		super().__init__(**kwargs)
		self.highlight = highlight
		self.on_tap = on_tap
		self.is_selected = False
		self._touch_down_pos = None
		self.bind(pos=self._redraw_bg, size=self._redraw_bg)

	def set_selected(self, selected: bool):
		if self.is_selected != selected:
			self.is_selected = selected
			self._redraw_bg()

	def _redraw_bg(self, *_):
		self.canvas.before.clear()
		if self.is_selected:
			with self.canvas.before:
				Color(0.18, 0.22, 0.29, 1)
				Rectangle(pos=self.pos, size=self.size)

	def on_touch_down(self, touch):
		if self.collide_point(*touch.pos) and getattr(touch, 'button', None) in (None, 'left'):
			self._touch_down_pos = touch.pos
		return super().on_touch_down(touch)

	def on_touch_up(self, touch):
		start = self._touch_down_pos
		self._touch_down_pos = None
		if start is not None and self.collide_point(*touch.pos):
			dx = touch.pos[0] - start[0]
			dy = touch.pos[1] - start[1]
			if (dx * dx + dy * dy) <= dp(12) ** 2 and self.on_tap:
				self.on_tap(self)
		return super().on_touch_up(touch)


class AndroidConsole(ScrollView):
	"""Scrollable Kivy console with line capping, markup formatting, and tappable answer rows."""

	def __init__(
		self,
		font_name: str = 'Roboto',
		on_answer_selected: Optional[Callable[[Optional[AnswerHighlight]], None]] = None,
		**kwargs,
	):
		kwargs.setdefault('do_scroll_x', False)
		kwargs.setdefault('bar_width', dp(6))
		super().__init__(**kwargs)

		self.font_name = font_name
		self._on_answer_selected = on_answer_selected
		self._pending_line_buf: str = ''
		self._selected_answer_lbl: Optional[ConsoleAnswerLabel] = None

		self.console_box = BoxLayout(
			orientation='vertical',
			size_hint_y=None,
			spacing=dp(2),
			padding=(dp(4), dp(4)),
		)
		self.console_box.bind(minimum_height=self.console_box.setter('height'))
		self.add_widget(self.console_box)

	def clear_selection(self):
		if self._selected_answer_lbl is not None:
			self._selected_answer_lbl.set_selected(False)
			self._selected_answer_lbl = None

	def clear(self):
		self._pending_line_buf = ''
		self.clear_selection()
		self.console_box.clear_widgets()

	def append_text(self, text: str):
		self._pending_line_buf += text
		if '\n' in self._pending_line_buf:
			lines = self._pending_line_buf.split('\n')
			self._pending_line_buf = lines.pop()
			for line in lines:
				self._add_console_line(line)
		elif len(self._pending_line_buf) > 0:
			self.flush_partial_line()

	def flush_partial_line(self):
		if not self._pending_line_buf:
			return
		line = self._pending_line_buf
		self._pending_line_buf = ''
		self._add_console_line(line)

	def add_answer_line(self, text: str, highlight: Optional[AnswerHighlight]):
		self.flush_partial_line()
		if highlight is None:
			self._add_console_line(text)
			return
		lbl = ConsoleAnswerLabel(
			highlight=highlight,
			on_tap=self._on_answer_tapped,
			text=format_console_markup(text if text else ' '),
			markup=True,
			font_name=self.font_name,
			font_size=dp(13),
			color=(0.91, 0.92, 0.93, 1),
			size_hint_y=None,
			halign='left',
			valign='top',
		)
		self._append_widget(lbl)

	def _add_console_line(self, line: str):
		lbl = Label(
			text=format_console_markup(line if line else ' '),
			markup=True,
			font_name=self.font_name,
			font_size=dp(13),
			color=(0.91, 0.92, 0.93, 1),
			size_hint_y=None,
			halign='left',
			valign='top',
		)
		self._append_widget(lbl)

	def _append_widget(self, lbl: Label):
		lbl.bind(width=lambda inst, w: setattr(inst, 'text_size', (w, None)))
		lbl.bind(texture_size=lambda inst, ts: setattr(inst, 'height', max(dp(18), ts[1] + dp(2))))
		self.console_box.add_widget(lbl)

		while len(self.console_box.children) > MAX_CONSOLE_LINES:
			oldest = self.console_box.children[-1]
			if oldest is self._selected_answer_lbl:
				self._selected_answer_lbl = None
			self.console_box.remove_widget(oldest)

		Clock.schedule_once(lambda _dt: setattr(self, 'scroll_y', 0), 0.02)

	def _on_answer_tapped(self, lbl: ConsoleAnswerLabel):
		if self._selected_answer_lbl is lbl:
			lbl.set_selected(False)
			self._selected_answer_lbl = None
			if self._on_answer_selected is not None:
				self._on_answer_selected(None)
			return

		if self._selected_answer_lbl is not None:
			self._selected_answer_lbl.set_selected(False)
		self._selected_answer_lbl = lbl
		lbl.set_selected(True)
		if self._on_answer_selected is not None:
			self._on_answer_selected(lbl.highlight)