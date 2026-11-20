import copy
import os
import queue
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from src.config import (
	COUNTER_CONNECTION_TYPES,
	GRAPH_SETTING_KEYS,
	Config,
	build_effective_config,
	create_input_file,
	read_config_file,
	save_config_file,
)
from src.games.relationship.runner import run_relationship_guessing_game, compute_relationship_stats, GameCancelledError
from src.games.relationship.preparer import prepare_relationship_game_data
from src.graph_diagram import AnswerHighlight, GraphDiagramData
from src.html_exporter import generate_html_and_graphml
from src.io_graphml import read_from_graph_xml
from src.models import GraphContext
from src.progress_storage import (
	load_app_state,
	load_graph_config,
	record_recent_file,
	save_graph_config,
	set_sync_folder,
)
from src.ui.desktop.session import ConsoleRedirector, GameSession


def parse_graph_settings_dict(raw: Dict[str, Any], scope_label: str) -> Dict[str, Any]:
	"""Validates and normalizes raw UI form values into a per-graph settings dict."""
	out: Dict[str, Any] = {}
	out["connection_type"] = str(raw["connection_type"]).strip().lower() or "correlation"
	out["ignore_edge_colors"] = bool(raw["ignore_edge_colors"])
	try:
		out["color_threshold"] = int(str(raw["color_threshold"]).strip())
		out["connections_skipped"] = int(str(raw["connections_skipped"]).strip())
		out["max_cycle_length_html"] = int(str(raw["max_cycle_length_html"]).strip())
		out["max_indirectness"] = int(str(raw["max_indirectness"]).strip())
		out["max_cycle_length_game"] = int(str(raw["max_cycle_length_game"]).strip())
		out["max_indirectness_game"] = int(str(raw["max_indirectness_game"]).strip())
		chance = float(str(raw["chance_irrelevant"]).strip())
	except ValueError as exc:
		raise ValueError(f"[{scope_label}] Check numeric fields: {exc}") from exc

	if chance > 1.0:
		chance /= 100.0
	out["chance_irrelevant"] = chance
	out["show_connections_list"] = bool(raw["show_connections_list"])
	out["show_only_edges"] = bool(raw["show_only_edges"])
	out["show_edge_labels"] = bool(raw["show_edge_labels"])
	out["enable_non_cycle_printing"] = bool(raw["enable_non_cycle_printing"])
	out["sort_by_len"] = bool(raw["sort_by_len"])
	out["sort_connections_alphabetically"] = bool(raw["sort_connections_alphabetically"])
	out["source_node"] = str(raw["source_node"]).strip().lower()
	out["target_node"] = str(raw["target_node"]).strip().lower()

	block_raw = raw["block_starting_node"]
	if isinstance(block_raw, list):
		out["block_starting_node"] = [str(x).strip().lower() for x in block_raw if str(x).strip()]
	else:
		out["block_starting_node"] = [x.strip().lower() for x in str(block_raw).split(",") if x.strip()]

	excl_raw = raw["excluded_elements"]
	if isinstance(excl_raw, list):
		out["excluded_elements"] = [str(x).strip() for x in excl_raw if str(x).strip()]
	else:
		out["excluded_elements"] = [line.strip() for line in str(excl_raw).splitlines() if line.strip()]

	out["leaf_only"] = bool(raw["leaf_only"])
	out["include_secondary_cycles"] = bool(raw["include_secondary_cycles"])
	return out


class AppController:
	"""Shared application state, background workers, and game session lifecycle for Desktop and Android UIs."""

	def __init__(self, input_file: str, output_folder: str):
		self.input_file = os.path.abspath(input_file)
		self.output_folder = os.path.abspath(output_folder)

		self.base_config: Config = Config()
		self.local_overrides: Dict[str, Any] = {}
		self.config_obj: Config = Config()
		self.ctx: Optional[GraphContext] = None
		self.current_graph_path: str = ""
		self.last_html_path: str = ""
		self.is_busy: bool = False
		self.active_session: Optional[GameSession] = None
		self.prepared_game_data: Optional[dict] = None

		self.output_queue: queue.Queue = queue.Queue()
		self._orig_stdout = None
		self._orig_stderr = None
		self._redirect_installed: bool = False

	# ------------------------------------------------------------------
	# Stdout / Stderr Redirection
	# ------------------------------------------------------------------
	def install_console_redirect(self):
		if self._redirect_installed:
			return
		self._orig_stdout = sys.stdout
		self._orig_stderr = sys.stderr
		sys.stdout = ConsoleRedirector(self.output_queue, self._orig_stdout)
		sys.stderr = ConsoleRedirector(self.output_queue, self._orig_stderr)
		self._redirect_installed = True

	def restore_console_redirect(self):
		if not self._redirect_installed:
			return
		if self._orig_stdout is not None:
			sys.stdout = self._orig_stdout
		if self._orig_stderr is not None:
			sys.stderr = self._orig_stderr
		self._redirect_installed = False

	# ------------------------------------------------------------------
	# Startup & Config Resolution
	# ------------------------------------------------------------------
	def initialize_startup(self) -> Tuple[bool, str]:
		config_created = False
		if not os.path.exists(self.input_file):
			create_input_file(self.input_file)
			config_created = True

		self.base_config = read_config_file(self.input_file)
		self.config_obj = copy.deepcopy(self.base_config)

		app_state = load_app_state()
		last_file = app_state.get("last_file", "")

		candidate_path = ""
		if last_file and os.path.isfile(last_file):
			candidate_path = last_file
		else:
			cfg_path = self.resolve_graph_path_from_config(self.base_config)
			if cfg_path and os.path.isfile(cfg_path):
				candidate_path = os.path.abspath(cfg_path)

		return config_created, candidate_path

	@staticmethod
	def resolve_graph_path_from_config(cfg: Config) -> str:
		if not cfg.file_name:
			return ""
		if "/" in cfg.file_name or "\\" in cfg.file_name or os.path.isabs(cfg.file_name):
			return cfg.file_name if cfg.file_name.endswith(".graphml") else cfg.file_name + ".graphml"
		return os.path.join(
			cfg.folder_path,
			cfg.file_name + ("" if cfg.file_name.endswith(".graphml") else ".graphml"),
		)

	def resolve_effective_config(self, filepath: str) -> Tuple[Config, Dict[str, Any]]:
		norm_path = os.path.abspath(filepath)
		saved_dict = load_graph_config(norm_path) or {}
		local_overrides = {k: v for k, v in saved_dict.items() if k in GRAPH_SETTING_KEYS}
		return build_effective_config(self.base_config, local_overrides, norm_path), local_overrides

	def apply_config(
		self,
		new_base: Config,
		new_local: Dict[str, Any],
		mode: str = "session",
		sync_folder: Optional[str] = None,
	) -> Tuple[str, Optional[str]]:
		"""
		Applies global and local settings (optionally persisting them when mode == 'save').
		Returns ('reload_current', path) | ('load_default', path) | ('none', None).
		"""
		if mode == "save":
			if sync_folder is not None:
				set_sync_folder(sync_folder)
			save_config_file(self.input_file, new_base)
			if self.current_graph_path:
				save_graph_config(self.current_graph_path, new_local)

		self.base_config = copy.deepcopy(new_base)
		self.local_overrides = copy.deepcopy(new_local)

		if self.current_graph_path and os.path.isfile(self.current_graph_path):
			return "reload_current", self.current_graph_path

		self.config_obj = copy.deepcopy(self.base_config)
		target_path = self.resolve_graph_path_from_config(self.base_config)
		if target_path and os.path.isfile(target_path):
			return "load_default", os.path.abspath(target_path)

		return "none", None

	# ------------------------------------------------------------------
	# Graph Loading & HTML Generation
	# ------------------------------------------------------------------
	def cancel_active_game(self):
		if self.active_session is not None:
			self.active_session.cancel_event.set()
			self.active_session.input_queue.put(None)
			self.active_session.waiting_for_input = False
			self.active_session = None

	def load_graph_file(
		self,
		filepath: str,
		override_config: Optional[Config] = None,
		override_local: Optional[Dict[str, Any]] = None,
	) -> str:
		self.prepared_game_data = None
		self.cancel_active_game()

		norm_path = os.path.abspath(filepath)
		self.current_graph_path = norm_path
		if override_local is not None:
			self.local_overrides = copy.deepcopy(override_local)
		else:
			saved_dict = load_graph_config(norm_path) or {}
			self.local_overrides = {k: v for k, v in saved_dict.items() if k in GRAPH_SETTING_KEYS}

		self.config_obj = (
			copy.deepcopy(override_config)
			if override_config is not None
			else build_effective_config(self.base_config, self.local_overrides, norm_path)
		)
		self.is_busy = True
		record_recent_file(norm_path)

		cfg_snapshot = copy.deepcopy(self.config_obj)
		output_folder = self.output_folder

		def worker():
			try:
				if cfg_snapshot.excluded_elements:
					print(
						f"Excluding {len(cfg_snapshot.excluded_elements)} element/group(s): "
						f"{', '.join(cfg_snapshot.excluded_elements)}"
					)

				nodes, edges, edge_values, node_values, edge_labels, node_colors = read_from_graph_xml(
					norm_path, cfg_snapshot.color_threshold, cfg_snapshot.excluded_elements
				)

				if cfg_snapshot.ignore_edge_colors or cfg_snapshot.connection_type in COUNTER_CONNECTION_TYPES:
					edge_values = {k: 1 for k in edge_values}
					node_values = {k: 0 for k in node_values}
					print("Note: edge colors ignored — all edge values set to +1.")

				g = nx.DiGraph()
				g.add_nodes_from(nodes.keys())
				g.add_edges_from(edges)

				src_id = (
					next((nid for nid, label in nodes.items() if label.lower() == cfg_snapshot.source_node), None)
					if cfg_snapshot.source_node
					else None
				)
				tgt_id = (
					next((nid for nid, label in nodes.items() if label.lower() == cfg_snapshot.target_node), None)
					if cfg_snapshot.target_node
					else None
				)

				if cfg_snapshot.source_node and not src_id:
					raise ValueError(f"Could not find source node '{cfg_snapshot.source_node}' in this graph.")
				if cfg_snapshot.target_node and not tgt_id:
					raise ValueError(f"Could not find target node '{cfg_snapshot.target_node}' in this graph.")

				ctx = GraphContext(
					graph=g,
					nodes=nodes,
					node_values=node_values,
					edges=edges,
					edge_values=edge_values,
					config=cfg_snapshot,
					source_node_id=src_id,
					target_node_id=tgt_id,
					edge_labels=edge_labels,
					node_colors=node_colors,
				)

				html_path = generate_html_and_graphml(ctx, output_folder, norm_path)
				prepared = prepare_relationship_game_data(ctx)
				stats = compute_relationship_stats(ctx, prepared)
				self.output_queue.put(("loaded", (ctx, html_path, norm_path, prepared, stats)))
			except Exception as exc:
				self.output_queue.put(("load_error", str(exc)))

		threading.Thread(target=worker, daemon=True).start()
		return norm_path

	def regenerate_html(self) -> bool:
		if self.is_busy or not self.ctx or not self.current_graph_path:
			return False

		self.cancel_active_game()
		self.is_busy = True

		ctx_ref = self.ctx
		ctx_ref.nodes_printed.clear()
		graph_path = self.current_graph_path
		output_folder = self.output_folder

		def worker():
			try:
				html_path = generate_html_and_graphml(ctx_ref, output_folder, graph_path)
				self.output_queue.put(("html_done", html_path))
			except Exception as exc:
				self.output_queue.put(("load_error", str(exc)))

		threading.Thread(target=worker, daemon=True).start()
		return True

	# ------------------------------------------------------------------
	# Relationship Game Runner & Controls
	# ------------------------------------------------------------------
	def start_game(self) -> bool:
		if self.is_busy or not self.ctx:
			return False

		self.cancel_active_game()
		session = GameSession()
		self.active_session = session

		ctx_ref = self.ctx
		prepared_ref = self.prepared_game_data

		def on_stats(stats_dict: dict):
			self.output_queue.put(("stats", (session, stats_dict)))

		def on_graph(diagram_data: GraphDiagramData):
			self.output_queue.put(("graph", (session, diagram_data)))

		def on_answer_output(text: str, highlight: Optional[AnswerHighlight]):
			self.output_queue.put(("answer_line", (session, text, highlight)))

		def gui_input() -> str:
			if session.cancel_event.is_set():
				raise GameCancelledError()
			self.output_queue.put(("waiting_input", (session, True)))
			while True:
				if session.cancel_event.is_set():
					raise GameCancelledError()
				try:
					val = session.input_queue.get(timeout=0.1)
					if val is None or session.cancel_event.is_set():
						raise GameCancelledError()
					self.output_queue.put(("waiting_input", (session, False)))
					return val
				except queue.Empty:
					continue

		def game_worker():
			try:
				run_relationship_guessing_game(
					ctx_ref,
					input_fn=gui_input,
					exit_on_finish=False,
					on_stats_update=on_stats,
					prepared_data=prepared_ref,
					on_graph_update=on_graph,
					on_answer_output=on_answer_output,
				)
				self.output_queue.put(("game_finished", session))
			except GameCancelledError:
				pass
			except Exception as exc:
				self.output_queue.put(("game_error", (session, str(exc))))

		session.thread = threading.Thread(target=game_worker, daemon=True)
		session.thread.start()
		return True

	def send_reveal_next(self) -> bool:
		if self.active_session and self.active_session.waiting_for_input:
			self.active_session.waiting_for_input = False
			self.active_session.input_queue.put("")
			return True
		return False

	def send_stop_game(self) -> Optional[str]:
		if self.active_session and self.active_session.waiting_for_input:
			self.active_session.waiting_for_input = False
			self.active_session.input_queue.put("0")
			return "sent_quit"
		if self.active_session is not None:
			self.cancel_active_game()
			return "cancelled"
		return None

	# ------------------------------------------------------------------
	# Queue Polling & Cleanup
	# ------------------------------------------------------------------
	def poll_events(self) -> List[Tuple[str, Any]]:
		events: List[Tuple[str, Any]] = []
		try:
			while True:
				kind, payload = self.output_queue.get_nowait()

				if kind == "text":
					events.append(("text", payload))

				elif kind == "loaded":
					ctx, html_path, norm_path, prepared, stats = payload
					self.ctx = ctx
					self.prepared_game_data = prepared
					self.last_html_path = html_path or ""
					self.is_busy = False
					events.append(("loaded", payload))

				elif kind == "html_done":
					self.last_html_path = payload or self.last_html_path
					self.is_busy = False
					events.append(("html_done", self.last_html_path))

				elif kind == "load_error":
					self.is_busy = False
					self.prepared_game_data = None
					events.append(("load_error", payload))

				elif kind == "waiting_input":
					session, is_waiting = payload
					if session is self.active_session:
						session.waiting_for_input = is_waiting
						events.append(("waiting_input", is_waiting))

				elif kind == "game_finished":
					session = payload
					if session is self.active_session:
						self.active_session = None
						events.append(("game_finished", None))

				elif kind == "game_error":
					session, err_msg = payload
					if session is self.active_session:
						self.active_session = None
						events.append(("game_error", err_msg))

				elif kind == "stats":
					session, stats_dict = payload
					if session is self.active_session:
						events.append(("stats", stats_dict))

				elif kind == "graph":
					session, diagram_data = payload
					if session is self.active_session:
						events.append(("graph", diagram_data))

				elif kind == "answer_line":
					session, text, highlight = payload
					if session is self.active_session:
						events.append(("answer_line", (text, highlight)))

		except queue.Empty:
			pass
		return events

	def cleanup(self, join_timeout: float = 0.0):
		session = self.active_session
		self.cancel_active_game()
		if join_timeout > 0 and session is not None and session.thread is not None and session.thread.is_alive():
			session.thread.join(timeout=join_timeout)
		self.restore_console_redirect()