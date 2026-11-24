from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import Label as CoreLabel
from kivy.graphics import (
	Color,
	Ellipse,
	InstructionGroup,
	Line,
	Rectangle,
	StencilPop,
	StencilPush,
	StencilUnUse,
	StencilUse,
	Triangle,
)
from kivy.metrics import dp
from kivy.uix.widget import Widget

from src.diagram import (
	COLOR_ANT_NEG,
	COLOR_ANT_NEUTRAL,
	COLOR_ANT_POS,
	AnswerHighlight,
	DiagramCycle,
	GraphDiagramData,
	compute_ant_trail_segments,
	compute_circular_layout,
	compute_diagram_cycle_centers,
	compute_edge_geometry,
	find_cycle_icon_path,
	format_graph_node_label,
)
from src.ui.desktop.graph_canvas import SIZE_MULTIPLIER_SECONDARY, SIZE_MULTIPLIER_PRIMARY


def _hex_to_rgba(hex_color: str):
	h = (hex_color or '').lstrip('#')
	if len(h) != 6:
		return (0.0, 0.0, 0.0, 1.0)
	try:
		return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0, 1.0)
	except ValueError:
		return (0.0, 0.0, 0.0, 1.0)


class CircularGraphWidget(Widget):
	def __init__(self, font_name: str = 'Roboto', **kwargs):
		super().__init__(**kwargs)
		self.font_name = font_name
		self.diagram: GraphDiagramData = None
		self.highlight: AnswerHighlight = None
		self._icon_texture_cache = {}
		self._cycle_hits = []
		self._on_cycle_hover = None
		self._on_cycle_hover_clear = None
		self._hovered_icon_edges = None
		self._hovered_icon_highlight = None
		self._ant_phase = 0.0
		self._ant_event = None
		self._ant_group = None
		self._ant_edges_geom = []
		self.bind(pos=self._redraw, size=self._redraw)

	def set_diagram(self, diagram: GraphDiagramData):
		self.diagram = diagram
		self.highlight = None
		self._redraw()

	def set_highlight(self, highlight: AnswerHighlight):
		self.highlight = highlight
		self._redraw()

	def clear_hovered_cycle_icon(self, redraw: bool = True):
		if self._on_cycle_hover_clear is not None:
			self._on_cycle_hover_clear()
		changed = (self._hovered_icon_edges is not None) or (self._hovered_icon_highlight is not None)
		self._hovered_icon_edges = None
		self._hovered_icon_highlight = None
		if changed and redraw:
			self._redraw()

	def _on_mouse_pos(self, _window, pos):
		if not self.get_root_window() or self.opacity == 0 or self.width < 20 or self.height < 20:
			return
		lx, ly = self.to_widget(*pos)
		if not self.collide_point(lx, ly):
			self.clear_hovered_cycle_icon()
			return

		best = None
		best_d2 = float('inf')
		for mx, my, hit_r, cyc, diag in self._cycle_hits:
			d2 = (lx - mx) ** 2 + (ly - my) ** 2
			if d2 <= hit_r * hit_r and d2 < best_d2:
				best_d2 = d2
				best = (cyc, diag)

		if best is None:
			self.clear_hovered_cycle_icon()
			return

		cyc, diag = best
		edge_key = frozenset(cyc.edges)
		if self._hovered_icon_edges == edge_key:
			return

		self.clear_hovered_cycle_icon(redraw=False)
		self._hovered_icon_edges = edge_key
		self._hovered_icon_highlight = AnswerHighlight(
			node_ids=set(cyc.node_ids),
			edges=set(cyc.edges),
			is_cycle=True,
			cycle_polarity=cyc.polarity,
			cycle_node_ids=list(cyc.node_ids),
			diagram=diag,
		)
		if self._on_cycle_hover is not None:
			self._on_cycle_hover(edge_key, diag)
		self._redraw()

	def _load_cycle_icon_texture(self, polarity: int):
		icon_path = find_cycle_icon_path(polarity)
		if not icon_path:
			return None
		if icon_path not in self._icon_texture_cache:
			try:
				self._icon_texture_cache[icon_path] = CoreImage(icon_path).texture
			except Exception:
				self._icon_texture_cache[icon_path] = None
		return self._icon_texture_cache[icon_path]

	def _build_node_texture(self, text: str, text_rgba):
		formatted = format_graph_node_label(text) or ' '
		line_count = formatted.count('\n') + 1
		if line_count > 5:
			font_sz = dp(7.5)
		elif line_count > 3:
			font_sz = dp(8.5)
		elif line_count > 1:
			font_sz = dp(10)
		else:
			font_sz = dp(11)

		lbl = CoreLabel(
			text=formatted,
			font_size=font_sz,
			font_name=self.font_name,
			color=text_rgba,
			halign='center',
		)
		lbl.refresh()
		return lbl.texture

	def _redraw(self, *_):
		self.canvas.clear()
		self._ant_edges_geom = []
		self._ant_group = None

		if self.width < 20 or self.height < 20:
			self._stop_ant_animation()
			return

		active_hl = self.highlight
		if active_hl is None and self.diagram is not None:
			active_hl = self.diagram.default_highlight
		active_diagram = (
			active_hl.diagram
			if (active_hl is not None and active_hl.diagram is not None)
			else self.diagram
		)

		ox, oy = self.x, self.y
		with self.canvas:
			StencilPush()
			Rectangle(pos=self.pos, size=self.size)
			StencilUse()
			try:
				Color(1, 1, 1, 1)
				Rectangle(pos=self.pos, size=self.size)

				if active_diagram is None or not active_diagram.nodes:
					self._stop_ant_animation()
					lbl = CoreLabel(
						text='Reveal an answer to view graph',
						font_size=dp(12),
						font_name=self.font_name,
						color=(0.45, 0.45, 0.45, 1),
					)
					lbl.refresh()
					tex = lbl.texture
					if tex is not None:
						Color(1, 1, 1, 1)
						Rectangle(
							texture=tex,
							pos=(ox + (self.width - tex.width) / 2.0, oy + (self.height - tex.height) / 2.0),
							size=tex.size,
						)
					return

				textures = {}
				node_sizes = {}

				for node in active_diagram.nodes:
					tex = self._build_node_texture(node.label, _hex_to_rgba(node.text_color))
					textures[node.node_id] = tex
					tw = tex.width if tex is not None else dp(24)
					th = tex.height if tex is not None else dp(14)
					node_sizes[node.node_id] = (
						max(dp(40), tw + dp(10)),
						max(dp(22), th + dp(6)),
					)

				rects = compute_circular_layout(
					active_diagram,
					self.width,
					self.height,
					node_sizes,
					margin=dp(8),
					flip_y=True,
				)
				edges_geom = compute_edge_geometry(
					active_diagram,
					rects,
					parallel_offset=dp(6),
					target_pad=dp(1),
				)

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
				arrow_len = dp(8)
				arrow_hw = dp(3.5)
				for edge, x1, y1, x2, y2, ux, uy in normal_edges:
					Color(*_hex_to_rgba(edge.color))
					start_x = x1 + ux * arrow_len if edge.bidirectional else x1
					start_y = y1 + uy * arrow_len if edge.bidirectional else y1
					base_x = x2 - ux * arrow_len
					base_y = y2 - uy * arrow_len
					lx = base_x - uy * arrow_hw
					ly = base_y + ux * arrow_hw
					rx = base_x + uy * arrow_hw
					ry = base_y - ux * arrow_hw

					Line(points=[ox + start_x, oy + start_y, ox + base_x, oy + base_y], width=dp(1.1))
					Triangle(points=[ox + x2, oy + y2, ox + lx, oy + ly, ox + rx, oy + ry])
					if edge.bidirectional:
						slx = start_x - uy * arrow_hw
						sly = start_y + ux * arrow_hw
						srx = start_x + uy * arrow_hw
						sry = start_y - ux * arrow_hw
						Triangle(points=[ox + x1, oy + y1, ox + slx, oy + sly, ox + srx, oy + sry])

				# 2. Highlighted edge glow + crisp highlighted arrow
				hl_arrow_len = dp(10)
				hl_arrow_hw = dp(4.5)
				for edge, x1, y1, x2, y2, ux, uy in highlighted_edges:
					er, eg, eb, _ = _hex_to_rgba(edge.color)
					start_x = x1 + ux * hl_arrow_len if edge.bidirectional else x1
					start_y = y1 + uy * hl_arrow_len if edge.bidirectional else y1
					base_x = x2 - ux * hl_arrow_len
					base_y = y2 - uy * hl_arrow_len
					for gw, alpha in ((dp(7.0), 0.22), (dp(4.2), 0.44)):
						Color(er, eg, eb, alpha)
						Line(points=[ox + start_x, oy + start_y, ox + base_x, oy + base_y], width=gw, cap='round')

					Color(er, eg, eb, 1.0)
					Line(points=[ox + start_x, oy + start_y, ox + base_x, oy + base_y], width=dp(2.0))

				# 2b. Ant-trail animation layer on top of highlighted shafts (under arrowheads & nodes)
				if active_hl is not None and not active_hl.is_cycle and highlighted_edges:
					pol_map = getattr(active_hl, 'edge_polarities', None) or {}
					for edge, x1, y1, x2, y2, ux, uy in highlighted_edges:
						pol = pol_map.get((edge.source_id, edge.target_id))
						self._ant_edges_geom.append((edge, ox + x1, oy + y1, ox + x2, oy + y2, ux, uy, pol))
					self._ant_group = InstructionGroup()
					self.canvas.add(self._ant_group)
					self._update_ant_group()

				# 2c. Highlighted arrowheads
				for edge, x1, y1, x2, y2, ux, uy in highlighted_edges:
					er, eg, eb, _ = _hex_to_rgba(edge.color)
					Color(er, eg, eb, 1.0)
					base_x = x2 - ux * hl_arrow_len
					base_y = y2 - uy * hl_arrow_len
					lx = base_x - uy * hl_arrow_hw
					ly = base_y + ux * hl_arrow_hw
					rx = base_x + uy * hl_arrow_hw
					ry = base_y - ux * hl_arrow_hw
					Triangle(points=[ox + x2, oy + y2, ox + lx, oy + ly, ox + rx, oy + ry])
					if edge.bidirectional:
						start_x = x1 + ux * hl_arrow_len
						start_y = y1 + uy * hl_arrow_len
						slx = start_x - uy * hl_arrow_hw
						sly = start_y + ux * hl_arrow_hw
						srx = start_x + uy * hl_arrow_hw
						sry = start_y - ux * hl_arrow_hw
						Triangle(points=[ox + x1, oy + y1, ox + slx, oy + sly, ox + srx, oy + sry])

				# 3. Highlighted node glow behind boxes
				first_hl_nodes = set()
				if active_hl is not None and not active_hl.is_cycle:
					if getattr(active_hl, 'first_node_ids', None):
						first_hl_nodes.update(active_hl.first_node_ids)
					if active_hl.first_node_id:
						first_hl_nodes.add(active_hl.first_node_id)

				for node in active_diagram.nodes:
					if node.node_id not in hl_nodes:
						continue
					cx, cy, nw, nh = rects[node.node_id]
					bx = ox + cx - nw / 2.0
					by = oy + cy - nh / 2.0
					is_earliest_generation = node.node_id in first_hl_nodes
					if is_earliest_generation:
						nr, ng, nb, _ = (0.533, 0.533, 0.533, 1.0)
					elif node.role in ('common_source', 'common_effect'):
						nr, ng, nb, _ = _hex_to_rgba(node.outline_color)
					elif node.fill_color == '#FFFFFF':
						nr, ng, nb = (0.6, 0.6, 0.6)
					else:
						nr, ng, nb, _ = _hex_to_rgba(node.fill_color)
					steps = ((dp(16), 0.30), (dp(10), 0.54), (dp(5), 0.82)) if is_earliest_generation else (
						(dp(14), 0.25), (dp(9), 0.45), (dp(4.5), 0.72)
					)
					for pad, alpha in steps:
						Color(nr, ng, nb, alpha)
						Rectangle(pos=(bx - pad / 2.0, by - pad / 2.0), size=(nw + pad, nh + pad))

				# 4. Node boxes & labels
				for node in active_diagram.nodes:
					cx, cy, nw, nh = rects[node.node_id]
					tex = textures[node.node_id]
					bx = ox + cx - nw / 2.0
					by = oy + cy - nh / 2.0
					is_hl = node.node_id in hl_nodes
					is_earliest_generation = node.node_id in first_hl_nodes

					Color(*_hex_to_rgba(node.fill_color))
					Rectangle(pos=(bx, by), size=(nw, nh))

					if node.role == 'target':
						outline_rgba = _hex_to_rgba(node.outline_color)
						outline_w = dp(3.0)
					elif node.role in ('common_source', 'common_effect'):
						outline_rgba = _hex_to_rgba(node.outline_color)
						outline_w = dp(2.0) if is_hl else dp(1.7)
					else:
						outline_rgba = (0.333, 0.333, 0.333, 1.0) if is_earliest_generation else _hex_to_rgba(node.outline_color)
						outline_w = dp(2.0) if is_earliest_generation else (dp(1.5) if is_hl else dp(1.0))

					Color(*outline_rgba)
					Line(rectangle=(bx, by, nw, nh), width=outline_w)

					if tex is not None:
						Color(1, 1, 1, 1)
						Rectangle(
							texture=tex,
							pos=(ox + cx - tex.width / 2.0, oy + cy - tex.height / 2.0),
							size=tex.size,
						)

				# 5. Feedback loop icons
				cycles_to_draw = list(getattr(active_diagram, 'cycles', []) or [])
				if active_hl is not None and active_hl.is_cycle and active_hl.cycle_polarity in (1, -1):
					if not any(c.edges == active_hl.edges for c in cycles_to_draw):
						cycles_to_draw.append(DiagramCycle(
							node_ids=list(active_hl.cycle_node_ids or active_hl.node_ids),
							edges=set(active_hl.edges),
							polarity=active_hl.cycle_polarity,
						))

				self._cycle_hits = []
				if cycles_to_draw:
					icon_sz = max(dp(30), min(dp(50), min(self.width, self.height) * 0.20))
					centers = compute_diagram_cycle_centers(cycles_to_draw, rects, min_sep=icon_sz * 1.15)

					def _draw_kivy_cycle_icon(mid_x: float, mid_y: float, polarity: int, is_hl_cyc: bool, is_secondary: bool = False):
						base_sz = icon_sz * (SIZE_MULTIPLIER_SECONDARY if is_secondary else SIZE_MULTIPLIER_PRIMARY)
						draw_sz = base_sz * (1.22 if is_hl_cyc else 1.0)
						badge_rgba = (0.11, 0.73, 0.33, 1) if polarity > 0 else (0.90, 0.22, 0.21, 1)
						br, bg, bb, _ = badge_rgba
						if is_hl_cyc:
							r_glow = draw_sz * 0.46
							for pad, alpha in ((dp(14), 0.22), (dp(9), 0.42), (dp(4), 0.68)):
								Color(br, bg, bb, alpha)
								Ellipse(
									pos=(mid_x - r_glow - pad / 2.0, mid_y - r_glow - pad / 2.0),
									size=(r_glow * 2.0 + pad, r_glow * 2.0 + pad),
								)
						icon_tex = self._load_cycle_icon_texture(polarity)
						if icon_tex is not None:
							Color(1, 1, 1, 1)
							Rectangle(
								texture=icon_tex,
								pos=(mid_x - draw_sz / 2.0, mid_y - draw_sz / 2.0),
								size=(draw_sz, draw_sz),
							)
							if is_hl_cyc:
								Color(*badge_rgba)
								Line(circle=(mid_x, mid_y, draw_sz * 0.50), width=dp(2.4))
						else:
							r_bg = draw_sz * 0.44
							Color(1, 1, 1, 0.94)
							Ellipse(pos=(mid_x - r_bg, mid_y - r_bg), size=(r_bg * 2.0, r_bg * 2.0))
							Color(*badge_rgba)
							Line(circle=(mid_x, mid_y, r_bg), width=dp(3.0) if is_hl_cyc else dp(2.0))
							arm = r_bg * 0.54
							half_t = max(dp(2.0), r_bg * (0.16 if is_hl_cyc else 0.13))
							Rectangle(pos=(mid_x - arm, mid_y - half_t), size=(arm * 2.0, half_t * 2.0))
							if polarity > 0:
								Rectangle(pos=(mid_x - half_t, mid_y - arm), size=(half_t * 2.0, arm * 2.0))

					normal_items = []
					hl_items = []
					for idx, cyc in enumerate(cycles_to_draw):
						if idx not in centers or cyc.polarity not in (1, -1):
							continue
						is_hl_cyc = bool(
							active_hl is not None
							and active_hl.is_cycle
							and active_hl.edges == cyc.edges
						)
						if is_hl_cyc:
							hl_items.append((idx, cyc))
						else:
							normal_items.append((idx, cyc))

					for idx, cyc in normal_items:
						cx_i, cy_i = centers[idx]
						px, py = ox + cx_i, oy + cy_i
						_draw_kivy_cycle_icon(px, py, cyc.polarity, False, cyc.is_secondary)
						base_sz = icon_sz * (SIZE_MULTIPLIER_SECONDARY if cyc.is_secondary else SIZE_MULTIPLIER_PRIMARY)
						self._cycle_hits.append((px, py, max(base_sz * 0.55, dp(16)), cyc, active_diagram))
					for idx, cyc in hl_items:
						cx_i, cy_i = centers[idx]
						px, py = ox + cx_i, oy + cy_i
						_draw_kivy_cycle_icon(px, py, cyc.polarity, True, cyc.is_secondary)
						base_sz = icon_sz * (SIZE_MULTIPLIER_SECONDARY if cyc.is_secondary else SIZE_MULTIPLIER_PRIMARY)
						self._cycle_hits.append((px, py, max(base_sz * 0.55, dp(16)), cyc, active_diagram))
			finally:
				StencilUnUse()
				Rectangle(pos=self.pos, size=self.size)
				StencilPop()

		if self._ant_edges_geom and self.opacity > 0:
			self._start_ant_animation()
		else:
			self._stop_ant_animation()

	def on_touch_down(self, touch):
		if self.collide_point(*touch.pos) and getattr(touch, 'button', None) in (None, 'left'):
			for mx, my, hit_r, cyc, diag in reversed(self._cycle_hits):
				dx = touch.pos[0] - mx
				dy = touch.pos[1] - my
				if (dx * dx + dy * dy) <= hit_r * hit_r:
					if self.highlight and self.highlight.is_cycle and self.highlight.edges == cyc.edges:
						self.set_highlight(None)
					else:
						self.set_highlight(AnswerHighlight(
							node_ids=set(cyc.node_ids),
							edges=set(cyc.edges),
							is_cycle=True,
							cycle_polarity=cyc.polarity,
							cycle_node_ids=list(cyc.node_ids),
							diagram=diag,
						))
					return True
		return super().on_touch_down(touch)

	def _stop_ant_animation(self):
		if self._ant_event is not None:
			self._ant_event.cancel()
			self._ant_event = None

	def _start_ant_animation(self):
		if self._ant_event is None and self._ant_edges_geom:
			self._ant_event = Clock.schedule_interval(self._on_ant_tick, 1.0 / 28.0)

	def _on_ant_tick(self, dt: float):
		if not self._ant_edges_geom or self.height < 20 or self.opacity == 0:
			self._stop_ant_animation()
			return
		self._ant_phase = (self._ant_phase + dp(22.0) * min(0.1, dt)) % dp(18.0)
		self._update_ant_group()

	def _update_ant_group(self):
		if self._ant_group is None:
			return
		self._ant_group.clear()
		if not self._ant_edges_geom:
			return
		dash_len = dp(9.0)
		gap_len = dp(9.0)
		trim = dp(10.0)
		for edge, sx1, sy1, sx2, sy2, ux, uy, pol in self._ant_edges_geom:
			segs = compute_ant_trail_segments(
				sx1, sy1, sx2, sy2, ux, uy,
				phase=self._ant_phase,
				dash_len=dash_len,
				gap_len=gap_len,
				start_trim=trim if edge.bidirectional else 0.0,
				end_trim=trim,
			)
			if not segs:
				continue
			ant_hex = (
				COLOR_ANT_POS if (pol is not None and pol > 0)
				else (COLOR_ANT_NEG if (pol is not None and pol < 0) else COLOR_ANT_NEUTRAL)
			)
			ar, ag, ab, _ = _hex_to_rgba(ant_hex)
			for ax1, ay1, ax2, ay2 in segs:
				self._ant_group.add(Color(1, 1, 1, 0.92))
				self._ant_group.add(Line(points=[ax1, ay1, ax2, ay2], width=dp(5.4), cap='round'))
				self._ant_group.add(Color(ar, ag, ab, 1.0))
				self._ant_group.add(Line(points=[ax1, ay1, ax2, ay2], width=dp(3.6), cap='round'))