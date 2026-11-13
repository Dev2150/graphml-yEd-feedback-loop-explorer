COUNTER_CONNECTION_TYPES = {'counter', 'counters', 'game', 'game-counters'}


def get_box_prefix(index: int) -> str:
	return "🟦" if index % 2 == 0 else "🟥"


def format_node_name(node_id: str, nodes_dict: dict, index: int = 0, is_counter: bool = False) -> str:
	name = nodes_dict.get(node_id, str(node_id))
	if is_counter:
		return f"{get_box_prefix(index)} {name}"
	return name


def get_edge_arrow(val: int, ignore_edge_colors: bool = False) -> str:
	if ignore_edge_colors:
		return "→"
	return "↘" if val < 0 else "↗"


def edge_value_string(p_edge_value: int, is_simple: bool = False, ignore_edge_colors: bool = False) -> str:
	if ignore_edge_colors:
		return ' → ' if not is_simple else '→'
	if not is_simple:
		return ":--->:" if p_edge_value > 0 else ":--X->:"
	return "→" if p_edge_value > 0 else "-X>"


def edge_value(node1: str, node2: str, edge_values_dict: dict) -> int:
	return edge_values_dict.get((node1, node2), 1)


def rgb_print(text: str, r: int, g: int, b: int) -> str:
	return f"\033[38;2;{r};{g};{b}m{text}\033[0m"


def set_text_color_by_node_properties(text: str, cycle_correlation: int, convenience: int) -> str:
	if convenience < 0:
		return rgb_print(text, 255, 0, 0) if cycle_correlation > 0 else rgb_print(text, 255, 155, 155)
	if convenience > 0:
		return rgb_print(text, 0, 255, 0) if cycle_correlation > 0 else rgb_print(text, 155, 255, 155)
	return rgb_print(text, 255, 255, 255) if cycle_correlation > 0 else rgb_print(text, 96, 96, 96)


def get_color_by_node_properties(cycle_correlation: int, convenience: int) -> str:
	if convenience < 0:
		return "#FF0000" if cycle_correlation > 0 else "#FFAAAA"
	if convenience > 0:
		return "#00FF00" if cycle_correlation > 0 else "#AAFFAA"
	return "#FFFFFF" if cycle_correlation > 0 else "#777777"


def format_path_string(path: list, nodes_dict: dict, edge_values_dict: dict, edge_labels_dict: dict = None,
					   ignore_edge_colors: bool = False, is_counter: bool = False, start_index: int = 0) -> str:
	if not path:
		return ""
	parts = [format_node_name(path[0], nodes_dict, start_index, is_counter)]
	is_direct = (len(path) == 2)
	lbl_str = ""
	cum_val = 1

	for k in range(len(path) - 1):
		u = path[k]
		v = path[k + 1]
		val = edge_values_dict.get((u, v), 1)
		cum_val *= val
		arrow = get_edge_arrow(cum_val, ignore_edge_colors=(ignore_edge_colors or is_counter))
		if is_direct and edge_labels_dict:
			lbl = edge_labels_dict.get((u, v), "")
			if lbl:
				lbl_str = f"\n      ({lbl})"
		v_formatted = format_node_name(v, nodes_dict, start_index + k + 1, is_counter)
		parts.append(f"{arrow} {v_formatted}")
	return " ".join(parts) + lbl_str


def get_path_net_effect_arrow(path: list, edge_values_dict: dict) -> str:
	corr = 1
	for k in range(len(path) - 1):
		corr *= edge_values_dict.get((path[k], path[k + 1]), 1)
	return get_edge_arrow(corr)