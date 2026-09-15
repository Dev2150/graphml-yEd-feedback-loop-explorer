from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set
import networkx as nx
from src.config import Config


@dataclass
class GraphContext:
	graph: nx.DiGraph
	nodes: Dict[str, str]					   # node_id -> node_label
	node_values: Dict[str, int]				 # node_id -> polarity value (-1, 0, +1)
	edges: List[Tuple[str, str]]				# list of (source_id, target_id)
	edge_values: Dict[Tuple[str, str], int]	 # (source_id, target_id) -> polarity value
	config: Config
	source_node_id: str = None
	target_node_id: str = None
	nodes_printed: Set[str] = field(default_factory=set)
	edge_labels: Dict[Tuple[str, str], str] = field(default_factory=dict)
	node_colors: Dict[str, str] = field(default_factory=dict)