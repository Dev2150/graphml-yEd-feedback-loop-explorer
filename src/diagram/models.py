
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

COLOR_GOLD = '#FFCC00'
COLOR_BLACK = '#000000'
COLOR_WHITE = '#FFFFFF'
COLOR_PINK = '#FF99CC'
COLOR_BLUE = '#00CCFF'
COLOR_RED = '#FF0000'
COLOR_SPOUSE_GREEN = '#77DD77'
COLOR_DARK_GREEN = '#006400'
COLOR_ANT_POS = '#00c947'
COLOR_ANT_NEG = '#c90000'
COLOR_ANT_NEUTRAL = '#34eb49'
COLOR_TRAIL_OUTLINE = "#ffffff"
NODE_WRAP_CHAR_THRESHOLD = 18
SIZE_MULTIPLIER_PRIMARY = 1.0
SIZE_MULTIPLIER_SECONDARY = 0.65


@dataclass
class DiagramNode:
	node_id: str
	label: str
	role: str  # 'target', 'common_source', 'common_effect', 'default'
	fill_color: str
	text_color: str
	outline_color: str = COLOR_BLACK


@dataclass
class DiagramEdge:
	source_id: str
	target_id: str
	correlation: int  # +1 -> black arrow, -1 -> red arrow
	color: str
	bidirectional: bool = False


@dataclass
class DiagramCycle:
	node_ids: List[str]
	edges: Set[Tuple[str, str]]
	polarity: Optional[int]  # +1 reinforcing (+), -1 balancing (-), None if ignored/neutral
	is_secondary: bool = False


@dataclass
class GraphDiagramData:
	title: str
	nodes: List[DiagramNode]
	edges: List[DiagramEdge]
	cycles: List[DiagramCycle] = field(default_factory=list)
	default_highlight: Optional['AnswerHighlight'] = None
	merged_nodes: Dict[str, List[str]] = field(default_factory=dict)
	highlights: List['AnswerHighlight'] = field(default_factory=list)


@dataclass
class AnswerHighlight:
	node_ids: Set[str]
	edges: Set[Tuple[str, str]]
	is_cycle: bool = False
	cycle_polarity: Optional[int] = None  # +1 reinforcing (+), -1 balancing (-), None if ignored/neutral
	cycle_node_ids: Optional[List[str]] = None
	diagram: Optional[GraphDiagramData] = None
	first_node_id: Optional[str] = None
	first_node_ids: Set[str] = field(default_factory=set)
	edge_polarities: Dict[Tuple[str, str], int] = field(default_factory=dict)


def blend_hex_with_white(hex_color: str, alpha: float) -> str:
	h = hex_color.lstrip('#')
	if len(h) != 6:
		return '#CCCCCC'
	r = int(h[0:2], 16)
	g = int(h[2:4], 16)
	b = int(h[4:6], 16)
	r_out = max(0, min(255, round(r * alpha + 255.0 * (1.0 - alpha))))
	g_out = max(0, min(255, round(g * alpha + 255.0 * (1.0 - alpha))))
	b_out = max(0, min(255, round(b * alpha + 255.0 * (1.0 - alpha))))
	return f"#{r_out:02X}{g_out:02X}{b_out:02X}"


def compute_cycle_center(
	highlight: Optional[AnswerHighlight],
	rects: Dict[str, Tuple[float, float, float, float]],
) -> Optional[Tuple[float, float]]:
	if highlight is None or not highlight.is_cycle:
		return None
	ids = highlight.cycle_node_ids if highlight.cycle_node_ids else list(highlight.node_ids)
	coords = [rects[nid] for nid in ids if nid in rects]
	if not coords:
		return None
	cx = sum(c[0] for c in coords) / len(coords)
	cy = sum(c[1] for c in coords) / len(coords)
	return cx, cy


def find_cycle_icon_path(polarity: Optional[int]) -> Optional[str]:
	if polarity not in (1, -1):
		return None
	diagram_dir = os.path.dirname(os.path.abspath(__file__))
	src_dir = os.path.dirname(diagram_dir)
	root_dir = os.path.dirname(src_dir)
	names = ('plus.png', 'cycle_plus.png', 'plus.jpg') if polarity > 0 else ('minus.png', 'cycle_minus.png', 'minus.jpg')
	for base_dir in (os.path.join(src_dir, 'assets'), os.path.join(root_dir, 'assets')):
		for name in names:
			candidate = os.path.join(base_dir, name)
			if os.path.isfile(candidate):
				return candidate
	return None

def highlight_contains_node(hl: Optional[AnswerHighlight], node_id: str) -> bool:
	if hl is None or not node_id:
		return False
	if node_id in hl.node_ids:
		return True
	return any(u == node_id or v == node_id for u, v in hl.edges)