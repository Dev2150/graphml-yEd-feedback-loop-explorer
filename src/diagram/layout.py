import math
import textwrap
from collections import deque
from typing import Dict, Iterable, List, Set, Tuple

from src.diagram.models import (
	NODE_WRAP_CHAR_THRESHOLD,
	DiagramCycle,
	DiagramEdge,
	GraphDiagramData,
)


def format_graph_node_label(label: str, max_chars_per_line: int = NODE_WRAP_CHAR_THRESHOLD) -> str:
	"""
	Formats a graph node label for visual rendering:
	- Preserves existing line breaks.
	- Any '→' starts on a new line beginning with '→'.
	- Lines longer than `max_chars_per_line` wrap cleanly.
	"""
	text = str(label or "").strip()
	if not text:
		return ""

	wrapped_lines: List[str] = []
	for raw_line in text.splitlines():
		raw_line = raw_line.strip()
		if not raw_line:
			continue

		segments: List[str] = []
		if '→' in raw_line:
			parts = raw_line.split('→')
			first = parts[0].strip()
			if first:
				segments.append(first)
			for part in parts[1:]:
				part_clean = part.strip()
				segments.append(f"→ {part_clean}" if part_clean else "→")
		else:
			segments.append(raw_line)

		for seg in segments:
			if len(seg) > max_chars_per_line:
				wrapped = textwrap.wrap(
					seg,
					width=max_chars_per_line,
					break_long_words=True,
					break_on_hyphens=True,
				)
				wrapped_lines.extend(wrapped if wrapped else [seg])
			else:
				wrapped_lines.append(seg)

	return "\n".join(wrapped_lines)


def compute_diagram_cycle_centers(
	cycles: List[DiagramCycle],
	rects: Dict[str, Tuple[float, float, float, float]],
	min_sep: float = 40.0,
) -> Dict[int, Tuple[float, float]]:
	"""
	Computes (cx, cy) icon positions for each cycle in `cycles`, gently separating
	cycles whose node centroids overlap (e.g. opposite-direction cycles on the same nodes).
	"""
	raw: Dict[int, List[float]] = {}
	for idx, cyc in enumerate(cycles):
		if cyc.polarity not in (1, -1):
			continue
		coords = [rects[nid] for nid in cyc.node_ids if nid in rects]
		if not coords:
			continue
		raw[idx] = [
			sum(c[0] for c in coords) / len(coords),
			sum(c[1] for c in coords) / len(coords),
		]

	if len(raw) <= 1:
		return {idx: (pos[0], pos[1]) for idx, pos in raw.items()}

	keys = list(raw.keys())

	# Pre-spread exact/near-identical centroids deterministically
	groups: List[List[int]] = []
	assigned: Set[int] = set()
	for i in keys:
		if i in assigned:
			continue
		grp = [i]
		assigned.add(i)
		xi, yi = raw[i]
		for j in keys:
			if j in assigned:
				continue
			xj, yj = raw[j]
			if math.hypot(xj - xi, yj - yi) < 2.0:
				grp.append(j)
				assigned.add(j)
		groups.append(grp)

	for grp in groups:
		if len(grp) == 2:
			off = min_sep * 0.55
			raw[grp[0]][0] -= off
			raw[grp[1]][0] += off
		elif len(grp) > 2:
			rad = min_sep * 0.65
			for k, idx in enumerate(grp):
				ang = (2.0 * math.pi * k) / len(grp)
				raw[idx][0] += rad * math.cos(ang)
				raw[idx][1] += rad * math.sin(ang)

	# Repulsion pass for close non-identical centers
	for _ in range(10):
		moved = False
		for a_i in range(len(keys)):
			i = keys[a_i]
			for b_i in range(a_i + 1, len(keys)):
				j = keys[b_i]
				dx = raw[j][0] - raw[i][0]
				dy = raw[j][1] - raw[i][1]
				dist = math.hypot(dx, dy)
				if dist < min_sep:
					moved = True
					if dist < 1e-3:
						ux, uy = 1.0, 0.0
					else:
						ux, uy = dx / dist, dy / dist
					push = (min_sep - dist) / 2.0
					raw[i][0] -= ux * push
					raw[i][1] -= uy * push
					raw[j][0] += ux * push
					raw[j][1] += uy * push
		if not moved:
			break

	return {idx: (pos[0], pos[1]) for idx, pos in raw.items()}


def _score_circular_order(
	order: List[int],
	undirected_edges: List[Tuple[int, int]],
	n: int,
) -> Tuple[int, int]:
	pos = [0] * n
	for idx, node in enumerate(order):
		pos[node] = idx

	ep: List[Tuple[int, int]] = []
	total_dist = 0
	for u, v in undirected_edges:
		pu, pv = pos[u], pos[v]
		if pu > pv:
			pu, pv = pv, pu
		ep.append((pu, pv))
		d = pv - pu
		total_dist += d if d <= n - d else n - d

	ep.sort()
	crossings = 0
	m = len(ep)
	for i in range(m):
		a, b = ep[i]
		for j in range(i + 1, m):
			c, d = ep[j]
			if c >= b:
				break
			if a < c and b < d:
				crossings += 1
	return crossings, total_dist


def _normalize_cycle_order(order: List[int], anchor: int = 0) -> List[int]:
	if not order or anchor not in order:
		return list(order)
	idx = order.index(anchor)
	rotated = order[idx:] + order[:idx]
	if len(rotated) >= 3 and rotated[1] > rotated[-1]:
		rotated = [rotated[0]] + list(reversed(rotated[1:]))
	return rotated


def _improve_circular_order(
	initial_order: List[int],
	undirected_edges: List[Tuple[int, int]],
	n: int,
) -> Tuple[Tuple[int, int], List[int]]:
	order = list(initial_order)
	best_score = _score_circular_order(order, undirected_edges, n)
	max_passes = 20 if n <= 30 else 5

	for _ in range(max_passes):
		improved = False

		# Relocate single node to best position
		for i in range(n):
			node = order[i]
			base = order[:i] + order[i + 1:]
			best_cand = None
			for j in range(n):
				if j == i:
					continue
				cand = base[:j] + [node] + base[j:]
				sc = _score_circular_order(cand, undirected_edges, n)
				if sc < best_score:
					best_score = sc
					best_cand = cand
			if best_cand is not None:
				order = best_cand
				improved = True

		# 2-opt segment reversals
		for i in range(n - 1):
			for j in range(i + 1, n):
				cand = order[:i] + list(reversed(order[i:j + 1])) + order[j + 1:]
				sc = _score_circular_order(cand, undirected_edges, n)
				if sc < best_score:
					best_score = sc
					order = cand
					improved = True

		if not improved:
			break

	return best_score, _normalize_cycle_order(order, 0)


def compute_circular_order(
	node_ids: Iterable[str],
	edge_pairs: List[Tuple[str, str]],
	target_ids: Set[str],
	nodes_dict: Dict[str, str],
) -> List[str]:
	unique_ids = list(dict.fromkeys(node_ids))
	n = len(unique_ids)
	if n <= 2:
		return unique_ids

	base_nodes = sorted(
		unique_ids,
		key=lambda x: (0 if x in target_ids else 1, str(nodes_dict.get(x, x)).lower(), str(x)),
	)
	id_to_idx = {nid: idx for idx, nid in enumerate(base_nodes)}

	edge_set: Set[Tuple[int, int]] = set()
	adj: List[List[int]] = [[] for _ in range(n)]
	for u, v in edge_pairs:
		if u in id_to_idx and v in id_to_idx and u != v:
			iu, iv = id_to_idx[u], id_to_idx[v]
			pair = (iu, iv) if iu < iv else (iv, iu)
			if pair not in edge_set:
				edge_set.add(pair)
				adj[iu].append(iv)
				adj[iv].append(iu)

	for lst in adj:
		lst.sort()

	undirected_edges = sorted(edge_set)
	if len(undirected_edges) <= 1:
		return base_nodes

	# Candidate 1: DFS order
	dfs_order: List[int] = []
	visited: Set[int] = set()

	def dfs(curr: int):
		visited.add(curr)
		dfs_order.append(curr)
		for nxt in adj[curr]:
			if nxt not in visited:
				dfs(nxt)

	for start in range(n):
		if start not in visited:
			dfs(start)

	# Candidate 2: BFS order
	bfs_order: List[int] = []
	visited_bfs: Set[int] = set()
	for start in range(n):
		if start in visited_bfs:
			continue
		visited_bfs.add(start)
		q = deque([start])
		while q:
			curr = q.popleft()
			bfs_order.append(curr)
			for nxt in adj[curr]:
				if nxt not in visited_bfs:
					visited_bfs.add(nxt)
					q.append(nxt)

	# Candidate 3: Greedy min-crossing insertion
	deg_order = sorted(range(n), key=lambda x: (-len(adj[x]), x))
	greedy_order = [0]
	for node in deg_order:
		if node == 0:
			continue
		placed_set = set(greedy_order) | {node}
		sub_edges = [(u, v) for (u, v) in undirected_edges if u in placed_set and v in placed_set]
		best_pos = len(greedy_order)
		best_sub_score = None
		cur_len = len(greedy_order) + 1
		for pos_idx in range(cur_len):
			cand = greedy_order[:pos_idx] + [node] + greedy_order[pos_idx:]
			remap = {nid: idx for idx, nid in enumerate(cand)}
			remapped_edges = [(remap[u], remap[v]) for u, v in sub_edges]
			sc = _score_circular_order(list(range(cur_len)), remapped_edges, cur_len)
			if best_sub_score is None or sc < best_sub_score:
				best_sub_score = sc
				best_pos = pos_idx
		greedy_order.insert(best_pos, node)

	best_score = None
	best_order = list(range(n))
	seen_starts: Set[Tuple[int, ...]] = set()
	for start_cand in (greedy_order, dfs_order, bfs_order, list(range(n))):
		norm_start = tuple(_normalize_cycle_order(start_cand, 0))
		if norm_start in seen_starts:
			continue
		seen_starts.add(norm_start)
		sc, imp = _improve_circular_order(list(norm_start), undirected_edges, n)
		if best_score is None or sc < best_score:
			best_score = sc
			best_order = imp

	# Exact branch-and-bound for small graphs (fixes node 0 at index 0, breaks mirror symmetry)
	if 3 <= n <= 10 and best_score > (0, len(undirected_edges)):
		steps = 0
		steps_limit = 60000
		order = [0] * n
		pos = [-1] * n
		pos[0] = 0
		rem_deg = [len(adj[i]) for i in range(n)]
		for nb in adj[0]:
			rem_deg[nb] -= 1
		completed_edges: List[Tuple[int, int]] = []

		def bnb(k: int, cross_so_far: int):
			nonlocal steps, best_score, best_order
			if steps >= steps_limit:
				return
			if k == n:
				sc = _score_circular_order(order, undirected_edges, n)
				if sc < best_score:
					best_score = sc
					best_order = list(order)
				return

			for w in range(1, n):
				if pos[w] != -1:
					continue
				if k == 1 and w == n - 1:
					continue
				if k == n - 1 and w <= order[1]:
					continue

				steps += 1
				if steps > steps_limit:
					return

				placed_nbr_pos = [pos[nb] for nb in adj[w] if pos[nb] != -1]
				added_cross = 0
				for p in placed_nbr_pos:
					for a, b in completed_edges:
						if a < p < b:
							added_cross += 1

				next_cross = cross_so_far + added_cross
				if next_cross > best_score[0]:
					continue

				order[k] = w
				pos[w] = k
				for nb in adj[w]:
					rem_deg[nb] -= 1

				new_edges = [(p, k) for p in placed_nbr_pos]
				pref = [0] * (k + 2)
				for x in range(k + 1):
					pref[x + 1] = pref[x] + rem_deg[order[x]]

				lb_future = 0
				for a, b in completed_edges:
					lb_future += pref[b] - pref[a + 1]
				for p, _k in new_edges:
					lb_future += pref[k] - pref[p + 1]

				if next_cross + lb_future <= best_score[0]:
					completed_edges.extend(new_edges)
					bnb(k + 1, next_cross)
					if new_edges:
						del completed_edges[-len(new_edges):]

				for nb in adj[w]:
					rem_deg[nb] += 1
				pos[w] = -1

		bnb(1, 0)
		best_order = _normalize_cycle_order(best_order, 0)

	return [base_nodes[i] for i in best_order]


def compute_circular_layout(
	diagram: GraphDiagramData,
	width: float,
	height: float,
	node_sizes: Dict[str, Tuple[float, float]],
	margin: float = 16.0,
	flip_y: bool = False,
) -> Dict[str, Tuple[float, float, float, float]]:
	"""
	Positions nodes on a circle/ellipse centered in (width, height).
	Returns node_id -> (cx, cy, w, h).
	"""
	nodes = diagram.nodes
	n = len(nodes)
	if n == 0:
		return {}

	max_w = max(node_sizes[node.node_id][0] for node in nodes)
	max_h = max(node_sizes[node.node_id][1] for node in nodes)

	rx_avail = max(10.0, (width - max_w) / 2.0 - margin)
	ry_avail = max(10.0, (height - max_h) / 2.0 - margin)
	rx = min(rx_avail, ry_avail * 2.2)
	ry = ry_avail

	cx_center = width / 2.0
	cy_center = height / 2.0
	rects: Dict[str, Tuple[float, float, float, float]] = {}

	for idx, node in enumerate(nodes):
		nw, nh = node_sizes[node.node_id]
		if n == 1:
			cx, cy = cx_center, cy_center
		elif n == 2:
			angle = math.pi if idx == 0 else 0.0
			cx = cx_center + rx_avail * math.cos(angle)
			cy = cy_center
		else:
			angle = -math.pi / 2.0 + (2.0 * math.pi * idx) / n
			cx = cx_center + rx * math.cos(angle)
			dy = ry * math.sin(angle)
			cy = (cy_center - dy) if flip_y else (cy_center + dy)

		cx = max(nw / 2.0 + margin * 0.5, min(width - nw / 2.0 - margin * 0.5, cx))
		cy = max(nh / 2.0 + margin * 0.5, min(height - nh / 2.0 - margin * 0.5, cy))
		rects[node.node_id] = (cx, cy, nw, nh)

	# Resolve any remaining box overlaps on compact viewports
	if n >= 2:
		node_ids = [node.node_id for node in nodes]
		pad = 6.0
		for _ in range(12):
			moved = False
			for i in range(n):
				id1 = node_ids[i]
				cx1, cy1, w1, h1 = rects[id1]
				for j in range(i + 1, n):
					id2 = node_ids[j]
					cx2, cy2, w2, h2 = rects[id2]
					dx = cx2 - cx1
					dy = cy2 - cy1
					req_x = (w1 + w2) / 2.0 + pad
					req_y = (h1 + h2) / 2.0 + pad
					ox = req_x - abs(dx)
					oy = req_y - abs(dy)
					if ox > 0 and oy > 0:
						moved = True
						if ox <= oy * 1.4:
							sgn = 1.0 if dx >= 0 else -1.0
							shift = ox / 2.0
							cx1 -= sgn * shift
							cx2 += sgn * shift
						else:
							sgn = 1.0 if dy >= 0 else -1.0
							shift = oy / 2.0
							cy1 -= sgn * shift
							cy2 += sgn * shift
						cx1 = max(w1 / 2.0 + margin * 0.5, min(width - w1 / 2.0 - margin * 0.5, cx1))
						cy1 = max(h1 / 2.0 + margin * 0.5, min(height - h1 / 2.0 - margin * 0.5, cy1))
						cx2 = max(w2 / 2.0 + margin * 0.5, min(width - w2 / 2.0 - margin * 0.5, cx2))
						cy2 = max(h2 / 2.0 + margin * 0.5, min(height - h2 / 2.0 - margin * 0.5, cy2))
						rects[id1] = (cx1, cy1, w1, h1)
						rects[id2] = (cx2, cy2, w2, h2)
			if not moved:
				break

	return rects


def _ray_rect_exit(
	ox: float,
	oy: float,
	vx: float,
	vy: float,
	cx: float,
	cy: float,
	hw: float,
	hh: float,
) -> Tuple[float, float]:
	t_candidates: List[float] = []
	if vx > 1e-9:
		t_candidates.append((cx + hw - ox) / vx)
	elif vx < -1e-9:
		t_candidates.append((cx - hw - ox) / vx)
	if vy > 1e-9:
		t_candidates.append((cy + hh - oy) / vy)
	elif vy < -1e-9:
		t_candidates.append((cy - hh - oy) / vy)

	valid = [t for t in t_candidates if t >= 0.0]
	t = min(valid) if valid else 0.0
	return ox + t * vx, oy + t * vy


def compute_edge_geometry(
	diagram: GraphDiagramData,
	rects: Dict[str, Tuple[float, float, float, float]],
	parallel_offset: float = 7.0,
	target_pad: float = 1.0,
) -> List[Tuple[DiagramEdge, float, float, float, float, float, float]]:
	"""
	Computes clipped start/end points on rectangle boundaries for each edge.
	Returns list of (edge, x1, y1, x2, y2, ux, uy).
	"""
	edge_set = {(e.source_id, e.target_id) for e in diagram.edges}
	result: List[Tuple[DiagramEdge, float, float, float, float, float, float]] = []

	for edge in diagram.edges:
		if edge.source_id not in rects or edge.target_id not in rects:
			continue
		cx1, cy1, w1, h1 = rects[edge.source_id]
		cx2, cy2, w2, h2 = rects[edge.target_id]

		dx = cx2 - cx1
		dy = cy2 - cy1
		dist = math.hypot(dx, dy)
		if dist < 1e-3:
			continue

		ux = dx / dist
		uy = dy / dist

		if (edge.target_id, edge.source_id) in edge_set:
			shift = min(parallel_offset, 0.32 * min(w1, h1, w2, h2))
			px = -uy * shift
			py = ux * shift
		else:
			px = 0.0
			py = 0.0

		ox1, oy1 = cx1 + px, cy1 + py
		ox2, oy2 = cx2 + px, cy2 + py

		x1, y1 = _ray_rect_exit(
			ox1, oy1, ux, uy, cx1, cy1,
			w1 / 2.0 + (target_pad if edge.bidirectional else 0.0),
			h1 / 2.0 + (target_pad if edge.bidirectional else 0.0),
		)
		x2, y2 = _ray_rect_exit(ox2, oy2, -ux, -uy, cx2, cy2, w2 / 2.0 + target_pad, h2 / 2.0 + target_pad)

		# Skip inverted arrows if boxes overlap on a tiny viewport
		if (x2 - x1) * ux + (y2 - y1) * uy <= 2.0:
			continue

		result.append((edge, x1, y1, x2, y2, ux, uy))

	return result


def compute_ant_trail_segments(
	x1: float,
	y1: float,
	x2: float,
	y2: float,
	ux: float,
	uy: float,
	phase: float,
	dash_len: float = 12.0,
	gap_len: float = 12.0,
	start_trim: float = 0.0,
	end_trim: float = 14.0,
) -> List[Tuple[float, float, float, float]]:
	"""
	Computes animated dash segments along an edge from (x1, y1) to (x2, y2),
	advancing in the direction of (ux, uy) as `phase` increases.
	"""
	total_len = math.hypot(x2 - x1, y2 - y1)
	t_start = max(0.0, start_trim)
	t_end = total_len - max(0.0, end_trim)
	if t_end - t_start <= 2.0:
		return []

	period = dash_len + gap_len
	if period <= 1e-3:
		return [(x1 + ux * t_start, y1 + uy * t_start, x1 + ux * t_end, y1 + uy * t_end)]

	p = phase % period
	k = math.floor((t_start - p - dash_len) / period)
	segments: List[Tuple[float, float, float, float]] = []

	while True:
		seg_a = k * period + p
		if seg_a >= t_end:
			break
		seg_b = seg_a + dash_len
		a = max(t_start, seg_a)
		b = min(t_end, seg_b)
		if b - a >= 1.5:
			segments.append((
				x1 + ux * a,
				y1 + uy * a,
				x1 + ux * b,
				y1 + uy * b,
			))
		k += 1

	return segments