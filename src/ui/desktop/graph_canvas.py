import tkinter as tk
from typing import Callable, Optional

from src.diagram import (
	AnswerHighlight,
	DiagramCycle,
	GraphDiagramData,
	blend_hex_with_white,
	compute_circular_layout,
	compute_diagram_cycle_centers,
	compute_edge_geometry,
	find_cycle_icon_path,
	format_graph_node_label,
)

COLOR_GLOW_FIRST = "#888888"
COLOR_OUTLINE_FIRST = "#555555"
GLOW_STEP_FIRST = ((18.0, 0.32), (11.0, 0.56), (5.5, 0.85))
GLOW_STEP_NOT_FIRST = ((16.0, 0.28), (10.0, 0.50), (5.0, 0.78))


class TkCircularGraphCanvas(tk.Canvas):
	"""Self-contained Tkinter circular graph renderer with cycle-icon hover detection."""

	def __init__(
		self,
		parent,
		on_title_change: Optional[Callable[[str], None]] = None,
		on_cycle_hover: Optional[Callable[[frozenset, GraphDiagramData], None]] = None,
		on_cycle_hover_clear: Optional[Callable[[], None]] = None,
		**kwargs,
	):
		kwargs.setdefault("bg", "#FFFFFF")
		kwargs.setdefault("highlightthickness", 1)
		kwargs.setdefault("highlightbackground", "#CCCCCC")
		super().__init__(parent, **kwargs)

		self._on_title_change = on_title_change
		self._on_cycle_hover = on_cycle_hover
		self._on_cycle_hover_clear = on_cycle_hover_clear

		self.current_diagram: Optional[GraphDiagramData] = None
		self.active_highlight: Optional[AnswerHighlight] = None
		self._icon_photo_cache: dict = {}
		self._cycle_hits: list = []
		self._hovered_icon_edges: Optional[frozenset] = None
		self._hovered_icon_highlight: Optional[AnswerHighlight] = None

		self.bind("<Configure>", lambda _e: self.redraw())
		self.bind("<Motion>", self._on_motion)
		self.bind("<Leave>", lambda _e: self.clear_hovered_cycle_icon())

	def set_diagram(self, diagram: Optional[GraphDiagramData]):
		self.current_diagram = diagram
		self.clear_hovered_cycle_icon(redraw=False)
		self.active_highlight = None
		self.redraw()

	def set_highlight(self, highlight: Optional[AnswerHighlight]):
		self.active_highlight = highlight
		self.redraw()

	def clear_hovered_cycle_icon(self, redraw: bool = True):
		if self._on_cycle_hover_clear is not None:
			self._on_cycle_hover_clear()

		changed = (self._hovered_icon_edges is not None) or (self._hovered_icon_highlight is not None)
		self._hovered_icon_edges = None
		self._hovered_icon_highlight = None
		self.configure(cursor="")
		if changed and redraw:
			self.redraw()

	def _on_motion(self, event):
		best = None
		best_d2 = float("inf")
		for mx, my, hit_r, cyc, diag in self._cycle_hits:
			d2 = (event.x - mx) ** 2 + (event.y - my) ** 2
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

		self.configure(cursor="hand2")
		self.redraw()

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

	def redraw(self):
		self.delete("all")
		self._cycle_hits = []

		default_hl = self.current_diagram.default_highlight if self.current_diagram is not None else None
		active_hl = (
			self.active_highlight
			if self.active_highlight is not None
			else (self._hovered_icon_highlight if self._hovered_icon_highlight is not None else default_hl)
		)
		diagram = (
			active_hl.diagram
			if (active_hl is not None and active_hl.diagram is not None)
			else self.current_diagram
		)

		if self._on_title_change is not None:
			self._on_title_change(diagram.title if diagram is not None else "Reveal an answer to view graph")

		w = self.winfo_width()
		h = self.winfo_height()
		if w < 40 or h < 40:
			return

		if diagram is None or not diagram.nodes:
			self.create_text(
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
			tid = self.create_text(0, 0, text=wrapped, font=node_font, justify=tk.CENTER)
			bbox = self.bbox(tid)
			self.delete(tid)
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
			self.create_line(
				x1, y1, x2, y2,
				fill=edge.color,
				width=1.8,
				arrow=tk.BOTH if edge.bidirectional else tk.LAST,
				arrowshape=(10, 12, 4.5),
			)

		# 2. Highlighted edge glow + crisp highlighted arrow
		for edge, x1, y1, x2, y2, ux, uy in highlighted_edges:
			gx1 = x1 + ux * 10.0 if edge.bidirectional else x1
			gy1 = y1 + uy * 10.0 if edge.bidirectional else y1
			gx2 = x2 - ux * 10.0
			gy2 = y2 - uy * 10.0
			for gw, alpha in ((12.0, 0.24), (7.0, 0.48)):
				self.create_line(
					gx1, gy1, gx2, gy2,
					fill=blend_hex_with_white(edge.color, alpha),
					width=gw,
					capstyle=tk.ROUND,
				)
			self.create_line(
				x1, y1, x2, y2,
				fill=edge.color,
				width=3.0,
				arrow=tk.BOTH if edge.bidirectional else tk.LAST,
				arrowshape=(12, 15, 5.5),
			)

		# 3. Highlighted node glow behind node boxes
		first_hl_nodes = set()
		if active_hl is not None and not active_hl.is_cycle:
			if active_hl.first_node_ids:
				first_hl_nodes.update(active_hl.first_node_ids)
			if active_hl.first_node_id:
				first_hl_nodes.add(active_hl.first_node_id)

		for node in diagram.nodes:
			if node.node_id not in hl_nodes:
				continue
			cx, cy, nw, nh = rects[node.node_id]
			is_earliest_generation = (node.node_id in first_hl_nodes)
			if is_earliest_generation:
				glow_base = COLOR_GLOW_FIRST
			elif node.role in ('common_source', 'common_effect'):
				glow_base = node.outline_color
			else:
				glow_base = node.fill_color if node.fill_color != "#FFFFFF" else "#999999"
			glow_steps = GLOW_STEP_FIRST if is_earliest_generation else GLOW_STEP_NOT_FIRST
			for pad, alpha in glow_steps:
				self.create_rectangle(
					cx - (nw + pad) / 2.0,
					cy - (nh + pad) / 2.0,
					cx + (nw + pad) / 2.0,
					cy + (nh + pad) / 2.0,
					fill=blend_hex_with_white(glow_base, alpha),
					outline="",
				)

		# 4. Node boxes & labels
		for node in diagram.nodes:
			cx, cy, nw, nh = rects[node.node_id]
			is_hl = node.node_id in hl_nodes
			is_earliest_generation = (node.node_id in first_hl_nodes)
			if node.role == 'target':
				outline_col = node.outline_color
				outline_w = 4.0
			elif node.role in ('common_source', 'common_effect'):
				outline_col = node.outline_color
				outline_w = 2.8 if is_hl else 2.4
			else:
				outline_col = COLOR_OUTLINE_FIRST if is_earliest_generation else node.outline_color
				outline_w = 2.8 if is_earliest_generation else (2.2 if is_hl else 1.4)

			self.create_rectangle(
				cx - nw / 2.0,
				cy - nh / 2.0,
				cx + nw / 2.0,
				cy + nh / 2.0,
				fill=node.fill_color,
				outline=outline_col,
				width=outline_w,
			)
			self.create_text(
				cx,
				cy,
				text=wrapped_labels[node.node_id],
				fill=node.text_color,
				font=node_fonts[node.node_id],
				justify=tk.CENTER,
			)

		# 5. Feedback loop icons
		cycles_to_draw = list(getattr(diagram, "cycles", []) or [])
		if active_hl is not None and active_hl.is_cycle and active_hl.cycle_polarity in (1, -1):
			if not any(c.edges == active_hl.edges for c in cycles_to_draw):
				cycles_to_draw.append(DiagramCycle(
					node_ids=list(active_hl.cycle_node_ids or active_hl.node_ids),
					edges=set(active_hl.edges),
					polarity=active_hl.cycle_polarity,
				))

		if cycles_to_draw:
			icon_sz = max(34, min(56, int(min(w, h) * 0.16)))
			centers = compute_diagram_cycle_centers(cycles_to_draw, rects, min_sep=icon_sz * 1.15)

			def _draw_cycle_icon(mid_x: float, mid_y: float, polarity: int, is_hl_cyc: bool):
				badge_col = "#1DB954" if polarity > 0 else "#E53935"
				draw_sz = int(round(icon_sz * (1.22 if is_hl_cyc else 1.0)))
				if is_hl_cyc:
					r_glow = draw_sz * 0.46
					for pad, alpha in ((18.0, 0.22), (11.0, 0.42), (5.0, 0.72)):
						self.create_oval(
							mid_x - r_glow - pad / 2.0,
							mid_y - r_glow - pad / 2.0,
							mid_x + r_glow + pad / 2.0,
							mid_y + r_glow + pad / 2.0,
							fill=blend_hex_with_white(badge_col, alpha),
							outline="",
						)
				photo = self._load_tk_cycle_icon(polarity, draw_sz)
				if photo is not None:
					self.create_image(mid_x, mid_y, image=photo)
					if is_hl_cyc:
						r_ring = draw_sz * 0.50
						self.create_oval(
							mid_x - r_ring, mid_y - r_ring,
							mid_x + r_ring, mid_y + r_ring,
							outline=badge_col,
							width=3.0,
						)
				else:
					r_bg = draw_sz * 0.44
					self.create_oval(
						mid_x - r_bg, mid_y - r_bg,
						mid_x + r_bg, mid_y + r_bg,
						fill="#FFFFFF",
						outline=badge_col,
						width=4.0 if is_hl_cyc else 2.6,
					)
					arm = r_bg * 0.56
					thick = max(3.5, r_bg * (0.28 if is_hl_cyc else 0.22))
					self.create_line(
						mid_x - arm, mid_y, mid_x + arm, mid_y,
						fill=badge_col, width=thick, capstyle=tk.ROUND,
					)
					if polarity > 0:
						self.create_line(
							mid_x, mid_y - arm, mid_x, mid_y + arm,
							fill=badge_col, width=thick, capstyle=tk.ROUND,
						)

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
				mx, my = centers[idx]
				_draw_cycle_icon(mx, my, cyc.polarity, False)
				self._cycle_hits.append((mx, my, max(icon_sz * 0.55, 18.0), cyc, diagram))
			for idx, cyc in hl_items:
				mx, my = centers[idx]
				_draw_cycle_icon(mx, my, cyc.polarity, True)
				self._cycle_hits.append((mx, my, max(icon_sz * 0.55, 18.0), cyc, diagram))