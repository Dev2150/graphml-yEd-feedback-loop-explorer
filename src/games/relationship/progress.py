import random
import sys
from typing import Optional


def get_canonical_cycle_tuple(cycle_nodes, nodes_dict):
	n = len(cycle_nodes)
	rotations = [cycle_nodes[i:] + cycle_nodes[:i] for i in range(n)]
	return min(rotations, key=lambda rot: [nodes_dict.get(x, str(x)).lower() for x in rot])


def get_pair_key(u_node, v_node, nodes_dict) -> str:
	name1 = nodes_dict.get(u_node, str(u_node))
	name2 = nodes_dict.get(v_node, str(v_node))
	return ",".join(sorted([name1, name2]))


def get_item_key(item, nodes_dict) -> str:
	itype, data = item
	if itype == 'leaf_src':
		return f"leaf_src:{nodes_dict.get(data, str(data))}"
	if itype == 'leaf_dst':
		return f"leaf_dst:{nodes_dict.get(data, str(data))}"
	if itype == 'cycle':
		canonical_names = [nodes_dict.get(x, str(x)) for x in data]
		return "cycle:" + "->".join(canonical_names) + f"->{canonical_names[0]}"
	return get_pair_key(data[0], data[1], nodes_dict)


def build_stats_snapshot(
	nodes_dict: dict,
	category_config: list,
	game_progress: dict,
	chance_irrelevant: float = 0.2,
) -> dict:
	rows = []
	min_tier = sys.maxsize
	has_relevant = any(cat_name != 'Irrelevant' and items for cat_name, items in category_config)
	exclude_irrelevant = (chance_irrelevant <= 0.0 and has_relevant)

	total_answered = 0
	total_items = 0

	for cat_name, items in category_config:
		if not items:
			continue
		counts = [game_progress.get(get_item_key(it, nodes_dict), 0) for it in items]
		tier = min(counts)
		total = len(counts)
		answered = total - sum(1 for c in counts if c == tier)
		pct = int(100 * answered / total) if total else 0
		count_in_total = not (exclude_irrelevant and cat_name == 'Irrelevant')
		if count_in_total:
			if min_tier > tier:
				min_tier = tier
			total_answered += answered
			total_items += total
		rows.append({
			"category": cat_name,
			"answered": answered,
			"total": total,
			"pct": pct,
			"tier": tier,
			"left": total - answered,
			"count_in_total": count_in_total,
		})
	return {
		"rows": rows,
		"current_tier": min_tier if min_tier != sys.maxsize else 0,
		"total_answered": total_answered,
		"total_items": total_items,
	}


def choose_next_item(
	category_config: list,
	all_relevant_items: list,
	game_progress: dict,
	nodes_dict: dict,
	chance_irrelevant: float,
) -> Optional[tuple]:
	def get_count(it):
		return game_progress.get(get_item_key(it, nodes_dict), 0)

	min_rel_count = min((get_count(it) for it in all_relevant_items), default=0)

	eligible_by_cat = {}
	for cat_name, items in category_config:
		if not items:
			continue
		if cat_name == 'Irrelevant':
			min_irr = min(get_count(it) for it in items)
			avail = [it for it in items if get_count(it) == min_irr]
			if avail:
				eligible_by_cat['irrelevant'] = avail
		else:
			avail = [it for it in items if get_count(it) == min_rel_count]
			if avail:
				eligible_by_cat[cat_name] = avail

	if not eligible_by_cat:
		return None

	active_cats = list(eligible_by_cat.keys())
	relevant_cats = [c for c in active_cats if c != 'irrelevant']
	total_rel_count = sum(len(eligible_by_cat[c]) for c in relevant_cats)

	active_weights = []
	for c in active_cats:
		if c == 'irrelevant':
			if relevant_cats and total_rel_count > 0:
				active_weights.append(chance_irrelevant)
			else:
				active_weights.append(1.0)
		else:
			if 'irrelevant' in active_cats:
				chance_relevant = max(0.0, 1.0 - chance_irrelevant)
				active_weights.append(chance_relevant * (len(eligible_by_cat[c]) / total_rel_count))
			else:
				active_weights.append(len(eligible_by_cat[c]) / total_rel_count)

	chosen_cat = random.choices(active_cats, weights=active_weights, k=1)[0]
	return random.choice(eligible_by_cat[chosen_cat])