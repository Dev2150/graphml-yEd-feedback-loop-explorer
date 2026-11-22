from typing import Optional, Set, Tuple


def ask_continue(ask_input) -> bool:
	user_input = ask_input().strip()
	if user_input == '0':
		print("Stopping the game.")
		return False
	return True


def path_edges(path: list) -> Set[Tuple]:
	return {(path[k], path[k + 1]) for k in range(len(path) - 1)}


def compute_cycle_polarity(path: list, edge_values: dict, ignore_polarity: bool) -> Optional[int]:
	if ignore_polarity:
		return None
	corr = 1
	for k in range(len(path) - 1):
		corr *= edge_values.get((path[k], path[k + 1]), 1)
	return 1 if corr > 0 else -1