"""
Kinship and genealogical relationship classification for family trees.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from src.family.terminology import (
	format_lineage_path,
	get_child_term,
	get_grandchild_term,
	get_grandparent_term,
	get_great_grandchild_term,
	get_great_grandparent_term,
	get_great_great_grandchild_term,
	get_great_great_grandparent_term,
	get_great_nephew_niece_term,
	get_great_uncle_aunt_term,
	get_nephew_niece_term,
	get_parent_term,
	get_sibling_term,
	get_uncle_aunt_term,
	ordinal,
	times_removed_str,
)
from src.io_graphml import detect_gender


@dataclass
class FamilyRelationshipResult:
	category: str  # 'parent_child', 'grandparent', 'sibling', 'uncle_nephew', 'first_cousin', 'second_third_cousin', 'in_law', 'irrelevant'
	primary_title: str
	details: List[str] = field(default_factory=list)
	lineages: List[str] = field(default_factory=list)

	@property
	def is_relevant(self) -> bool:
		return self.category != 'irrelevant'


def classify_blood_relationship(
	d1: int, d2: int, u_name: str, v_name: str, g1: str, g2: str
) -> Tuple[str, str, str]:
	"""
	d1 = distance from common ancestor down to u
	d2 = distance from common ancestor down to v
	g1 = gender of u ('M', 'F', 'U')
	g2 = gender of v ('M', 'F', 'U')
	"""
	# Direct Lineage: Parent / Child
	if d1 == 0 and d2 == 1:
		p_term = get_parent_term(g1)
		c_term = get_child_term(g2)
		return 'parent_child', f"{p_term} / {c_term}", f"{u_name} is {p_term} of {v_name} ({v_name} is {c_term})"
	if d1 == 1 and d2 == 0:
		c_term = get_child_term(g1)
		p_term = get_parent_term(g2)
		return 'parent_child', f"{c_term} / {p_term}", f"{u_name} is {c_term} of {v_name} ({v_name} is {p_term})"

	# Grandparent / Grandchild
	if d1 == 0 and d2 == 2:
		gp_term = get_grandparent_term(g1)
		gc_term = get_grandchild_term(g2)
		return 'grandparent', f"{gp_term} / {gc_term}", f"{u_name} is {gp_term} of {v_name} ({v_name} is {gc_term})"
	if d1 == 2 and d2 == 0:
		gc_term = get_grandchild_term(g1)
		gp_term = get_grandparent_term(g2)
		return 'grandparent', f"{gc_term} / {gp_term}", f"{u_name} is {gc_term} of {v_name} ({v_name} is {gp_term})"

	# Great-Grandparent / Great-Grandchild
	if d1 == 0 and d2 == 3:
		ggp_term = get_great_grandparent_term(g1)
		ggc_term = get_great_grandchild_term(g2)
		return 'grandparent', f"{ggp_term} / {ggc_term}", f"{u_name} is {ggp_term} of {v_name} ({v_name} is {ggc_term})"
	if d1 == 3 and d2 == 0:
		ggc_term = get_great_grandchild_term(g1)
		ggp_term = get_great_grandparent_term(g2)
		return 'grandparent', f"{ggc_term} / {ggp_term}", f"{u_name} is {ggc_term} of {v_name} ({v_name} is {ggp_term})"

	# Great-Great-Grandparent / Great-Great-Grandchild
	if d1 == 0 and d2 == 4:
		gggp_term = get_great_great_grandparent_term(g1)
		gggc_term = get_great_great_grandchild_term(g2)
		return 'grandparent', f"{gggp_term} / {gggc_term}", f"{u_name} is {gggp_term} of {v_name} ({v_name} is {gggc_term})"
	if d1 == 4 and d2 == 0:
		gggc_term = get_great_great_grandchild_term(g1)
		gggp_term = get_great_great_grandparent_term(g2)
		return 'grandparent', f"{gggc_term} / {gggp_term}", f"{u_name} is {gggc_term} of {v_name} ({v_name} is {gggp_term})"

	if d1 == 0 and d2 >= 5:
		k = d2 - 2
		gp_k = f"{k}-Great-Grandfather" if g1 == 'M' else f"{k}-Great-Grandmother" if g1 == 'F' else f"{k}-Great-Grandparent"
		gc_k = f"{k}-Great-Grandson" if g2 == 'M' else f"{k}-Great-Granddaughter" if g2 == 'F' else f"{k}-Great-Grandchild"
		return 'grandparent', f"{gp_k} / {gc_k}", f"{u_name} is {gp_k} of {v_name} ({v_name} is {gc_k})"
	if d1 >= 5 and d2 == 0:
		k = d1 - 2
		gc_k = f"{k}-Great-Grandson" if g1 == 'M' else f"{k}-Great-Granddaughter" if g1 == 'F' else f"{k}-Great-Grandchild"
		gp_k = f"{k}-Great-Grandfather" if g2 == 'M' else f"{k}-Great-Grandmother" if g2 == 'F' else f"{k}-Great-Grandparent"
		return 'grandparent', f"{gc_k} / {gp_k}", f"{u_name} is {gc_k} of {v_name} ({v_name} is {gp_k})"

	# Siblings
	if d1 == 1 and d2 == 1:
		s1 = get_sibling_term(g1)
		s2 = get_sibling_term(g2)
		if g1 == 'M' and g2 == 'M':
			title = "Brothers"
			detail = f"Brothers ({u_name} and {v_name} are Brothers)"
		elif g1 == 'F' and g2 == 'F':
			title = "Sisters"
			detail = f"Sisters ({u_name} and {v_name} are Sisters)"
		elif s1 != s2:
			title = f"{s1} / {s2}"
			detail = f"{s1} / {s2} ({u_name} is {s1}, {v_name} is {s2})"
		else:
			title = "Siblings"
			detail = f"Siblings ({u_name} and {v_name} are Siblings)"
		return 'sibling', title, detail

	# Uncles / Aunts & Nephews / Nieces
	if d1 == 1 and d2 == 2:
		u_term = get_uncle_aunt_term(g1)
		n_term = get_nephew_niece_term(g2)
		return 'uncle_nephew', f"{u_term} / {n_term}", f"{u_name} is {u_term} of {v_name} ({v_name} is {n_term})"
	if d1 == 2 and d2 == 1:
		n_term = get_nephew_niece_term(g1)
		u_term = get_uncle_aunt_term(g2)
		return 'uncle_nephew', f"{n_term} / {u_term}", f"{u_name} is {n_term} of {v_name} ({v_name} is {u_term})"

	# Great-Uncle / Great-Aunt & Great-Nephew / Great-Niece
	if d1 == 1 and d2 == 3:
		gu_term = get_great_uncle_aunt_term(g1)
		gn_term = get_great_nephew_niece_term(g2)
		return 'uncle_nephew', f"{gu_term} / {gn_term}", f"{u_name} is {gu_term} of {v_name} ({v_name} is {gn_term})"
	if d1 == 3 and d2 == 1:
		gn_term = get_great_nephew_niece_term(g1)
		gu_term = get_great_uncle_aunt_term(g2)
		return 'uncle_nephew', f"{gn_term} / {gu_term}", f"{u_name} is {gn_term} of {v_name} ({v_name} is {gu_term})"

	if d1 == 1 and d2 >= 4:
		k = d2 - 2
		gu_k = f"{k}-Great-Uncle" if g1 == 'M' else f"{k}-Great-Aunt" if g1 == 'F' else f"{k}-Great-Uncle/Aunt"
		gn_k = f"{k}-Great-Nephew" if g2 == 'M' else f"{k}-Great-Niece" if g2 == 'F' else f"{k}-Great-Nephew/Niece"
		return 'uncle_nephew', f"{gu_k} / {gn_k}", f"{u_name} is {gu_k} of {v_name} ({v_name} is {gn_k})"
	if d1 >= 4 and d2 == 1:
		k = d1 - 2
		gn_k = f"{k}-Great-Nephew" if g1 == 'M' else f"{k}-Great-Niece" if g1 == 'F' else f"{k}-Great-Nephew/Niece"
		gu_k = f"{k}-Great-Uncle" if g2 == 'M' else f"{k}-Great-Aunt" if g2 == 'F' else f"{k}-Great-Uncle/Aunt"
		return 'uncle_nephew', f"{gn_k} / {gu_k}", f"{u_name} is {gn_k} of {v_name} ({v_name} is {gu_k})"

	# Cousins (d1 >= 2 and d2 >= 2)
	deg = min(d1, d2) - 1
	rem = abs(d1 - d2)
	ord_deg = ordinal(deg)
	rem_str = times_removed_str(rem)

	cat = 'first_cousin' if deg == 1 else 'second_third_cousin'
	if rem == 0:
		title = f"{ord_deg} degree cousin"
		detail = f"{ord_deg} degree cousin ({u_name} and {v_name} are {ord_deg} cousins)"
	else:
		title = f"{ord_deg} cousin{rem_str}"
		if d1 < d2:
			detail = f"{ord_deg} cousin{rem_str} ({u_name} is {rem} gen. older than {v_name})"
		else:
			detail = f"{ord_deg} cousin{rem_str} ({u_name} is {rem} gen. younger than {v_name})"

	return cat, title, detail


def _analyze_blood_relationships(
	u: str,
	v: str,
	u_name: str,
	v_name: str,
	g_u: str,
	g_v: str,
	nodes_dict: Dict[str, str],
	children_map: Dict[str, List[str]],
	ancestor_paths: dict,
	ancestor_dist: dict,
) -> List[dict]:
	anc_u = ancestor_paths[u]
	anc_v = ancestor_paths[v]
	dist_u = ancestor_dist[u]
	dist_v = ancestor_dist[v]
	common_ancestors = set(dist_u.keys()).intersection(set(dist_v.keys()))

	blood_entries: List[dict] = []
	if not common_ancestors:
		return blood_entries

	mrcas = [a for a in common_ancestors if not any(c in common_ancestors for c in children_map.get(a, []))]
	mrcas.sort(key=lambda a: (dist_u[a] + dist_v[a], nodes_dict.get(a, '')))

	seen_signatures = set()
	for a in mrcas:
		d1 = dist_u[a]
		d2 = dist_v[a]
		cat, title, detail = classify_blood_relationship(d1, d2, u_name, v_name, g_u, g_v)

		lineage_strs = []
		for pu in anc_u[a][:2]:
			for pv in anc_v[a][:2]:
				p_u_to_a = list(reversed(pu))
				l_str = format_lineage_path(p_u_to_a, pv, nodes_dict)
				if l_str not in lineage_strs:
					lineage_strs.append(l_str)

		sig = (cat, title, d1, d2)
		if sig not in seen_signatures:
			seen_signatures.add(sig)
			blood_entries.append({
				'category': cat,
				'title': title,
				'detail': detail,
				'lineages': lineage_strs,
				'd1': d1,
				'd2': d2,
				'total_dist': d1 + d2,
			})
	return blood_entries


def _analyze_in_law_relationships(
	u: str,
	v: str,
	u_name: str,
	v_name: str,
	g_u: str,
	g_v: str,
	has_blood_relation: bool,
	nodes_dict: Dict[str, str],
	parents_map: Dict[str, List[str]],
	children_map: Dict[str, List[str]],
	spouses_map: Dict[str, Set[str]],
	ancestor_dist: dict,
) -> List[dict]:
	dist_u = ancestor_dist[u]
	dist_v = ancestor_dist[v]
	in_law_entries: List[dict] = []

	# Direct Spouse / Partner
	if v in spouses_map.get(u, set()):
		if g_u == 'M' and g_v == 'F':
			sp_title = "Husband / Wife"
		elif g_u == 'F' and g_v == 'M':
			sp_title = "Wife / Husband"
		elif g_u == 'M' and g_v == 'M':
			sp_title = "Husband / Husband (Spouses)"
		elif g_u == 'F' and g_v == 'F':
			sp_title = "Wife / Wife (Spouses)"
		else:
			sp_title = "Spouse / Partner"

		in_law_entries.append({
			'category': 'in_law',
			'title': sp_title,
			'detail': f"{sp_title} ({u_name} and {v_name})",
			'lineages': [f"{u_name} (Spouse) ↔ {v_name}"],
		})

	# u related to spouse(s) of v
	for s_v in spouses_map.get(v, set()):
		if s_v == u:
			continue
		s_v_name = nodes_dict.get(s_v, str(s_v))
		s_dist = ancestor_dist.get(s_v, {})
		s_ca = set(dist_u.keys()).intersection(set(s_dist.keys()))
		if not s_ca:
			continue
		s_mrcas = [a for a in s_ca if not any(c in s_ca for c in children_map.get(a, []))]
		for a in s_mrcas:
			d1 = dist_u[a]
			d2 = s_dist[a]
			a_name = nodes_dict.get(a, '')
			if d1 == 0 and d2 >= 1:
				p_in_law = _ancestor_in_law_term(d2, g_u)
				c_in_law = _descendant_in_law_term(d2, g_v)
				mid = "→" if d2 == 1 else "→ ... →"
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{p_in_law} / {c_in_law}",
					'detail': f"{u_name} is {p_in_law} of {v_name} ({v_name} is {c_in_law})",
					'lineages': [f"| {u_name} | {mid} {s_v_name} (Spouse) ↔ {v_name}"],
				})
			elif d1 >= 1 and d2 == 0:
				if v not in dist_u:
					sc_term = _step_descendant_term(d1, g_u)
					sp_term = _step_ancestor_term(d1, g_v)
					mid = "←" if d1 == 1 else "← ... ←"
					in_law_entries.append({
						'category': 'in_law',
						'title': f"{sc_term} / {sp_term}",
						'detail': f"{u_name} is {sc_term} of {v_name} ({v_name} is {sp_term})",
						'lineages': [f"{u_name} {mid} | {s_v_name} (Spouse) ↔ {v_name} |"],
					})
			elif d1 == 1 and d2 == 1:
				sib_in_law_u = "Brother-in-law" if g_u == 'M' else "Sister-in-law" if g_u == 'F' else "Sibling-in-law"
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{sib_in_law_u} (Sibling-in-law)",
					'detail': f"{u_name} is {sib_in_law_u} of {v_name} ({u_name} is sibling of {v_name}'s spouse {s_v_name})",
					'lineages': [f"{u_name} ← | {a_name} | → {s_v_name} (Spouse) ↔ {v_name}"],
				})
			elif d1 == 1 and d2 >= 2:
				u_in_law = _uncle_aunt_in_law_term(d2, g_u)
				n_in_law = _nephew_niece_in_law_term(d2, g_v)
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{u_in_law} / {n_in_law}",
					'detail': f"{u_name} is {u_in_law} of {v_name} ({v_name} is {n_in_law})",
					'lineages': [f"{u_name} ← | {a_name} | → ... → {s_v_name} (Spouse) ↔ {v_name}"],
				})
			elif d1 >= 2 and d2 == 1:
				n_in_law = _nephew_niece_in_law_term(d1, g_u)
				u_in_law = _uncle_aunt_in_law_term(d1, g_v)
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{n_in_law} / {u_in_law}",
					'detail': f"{u_name} is {n_in_law} of {v_name} ({v_name} is {u_in_law})",
					'lineages': [f"{u_name} ← ... ← | {a_name} | → {s_v_name} (Spouse) ↔ {v_name}"],
				})
			elif d1 >= 2 and d2 >= 2:
				deg = min(d1, d2) - 1
				rem = abs(d1 - d2)
				ord_deg = ordinal(deg)
				rem_str = times_removed_str(rem)
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{ord_deg} degree cousin-in-law",
					'detail': f"{ord_deg} cousin-in-law{rem_str} ({u_name} is {ord_deg} cousin of {v_name}'s spouse {s_v_name})",
					'lineages': [f"{u_name} ← ... ← | {a_name} | → ... → {s_v_name} (Spouse) ↔ {v_name}"],
				})

	# v related to spouse(s) of u
	for s_u in spouses_map.get(u, set()):
		if s_u == v:
			continue
		s_u_name = nodes_dict.get(s_u, str(s_u))
		s_dist = ancestor_dist.get(s_u, {})
		s_ca = set(dist_v.keys()).intersection(set(s_dist.keys()))
		if not s_ca:
			continue
		s_mrcas = [a for a in s_ca if not any(c in s_ca for c in children_map.get(a, []))]
		for a in s_mrcas:
			d1 = dist_v[a]
			d2 = s_dist[a]
			a_name = nodes_dict.get(a, '')
			if d1 == 0 and d2 >= 1:
				c_in_law = _descendant_in_law_term(d2, g_u)
				p_in_law = _ancestor_in_law_term(d2, g_v)
				mid = "←" if d2 == 1 else "← ... ←"
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{c_in_law} / {p_in_law}",
					'detail': f"{u_name} is {c_in_law} of {v_name} ({v_name} is {p_in_law})",
					'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} {mid} | {v_name} |"],
				})
			elif d1 >= 1 and d2 == 0:
				if u not in dist_v:
					sp_term = _step_ancestor_term(d1, g_u)
					sc_term = _step_descendant_term(d1, g_v)
					mid = "→" if d1 == 1 else "→ ... →"
					in_law_entries.append({
						'category': 'in_law',
						'title': f"{sp_term} / {sc_term}",
						'detail': f"{u_name} is {sp_term} of {v_name} ({v_name} is {sc_term})",
						'lineages': [f"| {u_name} (Spouse) ↔ {s_u_name} | {mid} {v_name}"],
					})
			elif d1 == 1 and d2 == 1:
				sib_in_law_u = "Brother-in-law" if g_u == 'M' else "Sister-in-law" if g_u == 'F' else "Sibling-in-law"
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{sib_in_law_u} (Sibling-in-law)",
					'detail': f"{u_name} is {sib_in_law_u} of {v_name} ({v_name} is sibling of {u_name}'s spouse {s_u_name})",
					'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← | {a_name} | → {v_name}"],
				})
			elif d1 == 1 and d2 >= 2:
				n_in_law = _nephew_niece_in_law_term(d2, g_u)
				u_in_law = _uncle_aunt_in_law_term(d2, g_v)
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{n_in_law} / {u_in_law}",
					'detail': f"{u_name} is {n_in_law} of {v_name} ({v_name} is {u_in_law})",
					'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← ... ← | {a_name} | → {v_name}"],
				})
			elif d1 >= 2 and d2 == 1:
				u_in_law = _uncle_aunt_in_law_term(d1, g_u)
				n_in_law = _nephew_niece_in_law_term(d1, g_v)
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{u_in_law} / {n_in_law}",
					'detail': f"{u_name} is {u_in_law} of {v_name} ({v_name} is {n_in_law})",
					'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← | {a_name} | → ... → {v_name}"],
				})
			elif d1 >= 2 and d2 >= 2:
				deg = min(d1, d2) - 1
				rem = abs(d1 - d2)
				ord_deg = ordinal(deg)
				rem_str = times_removed_str(rem)
				in_law_entries.append({
					'category': 'in_law',
					'title': f"{ord_deg} degree cousin-in-law",
					'detail': f"{ord_deg} cousin-in-law{rem_str} ({v_name} is {ord_deg} cousin of {u_name}'s spouse {s_u_name})",
					'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← ... ← | {a_name} | → ... → {v_name}"],
				})

	# Co-parents-in-law (children married)
	for c_u in children_map.get(u, []):
		for c_v in children_map.get(v, []):
			if c_v in spouses_map.get(c_u, set()):
				c_u_name = nodes_dict.get(c_u, str(c_u))
				c_v_name = nodes_dict.get(c_v, str(c_v))
				in_law_entries.append({
					'category': 'in_law',
					'title': 'Co-parents-in-law',
					'detail': f"Co-parents-in-law ({u_name}'s child {c_u_name} is married to {v_name}'s child {c_v_name})",
					'lineages': [f"| {u_name} | → {c_u_name} (Spouse) ↔ {c_v_name} ← | {v_name} |"],
				})

	# Step-siblings (parents married, no shared biological parents)
	if not has_blood_relation:
		for p_u in parents_map.get(u, []):
			for p_v in parents_map.get(v, []):
				if p_v in spouses_map.get(p_u, set()):
					p_u_name = nodes_dict.get(p_u, str(p_u))
					p_v_name = nodes_dict.get(p_v, str(p_v))
					if g_u == 'M' and g_v == 'M':
						st_title = "Step-brothers"
					elif g_u == 'F' and g_v == 'F':
						st_title = "Step-sisters"
					elif g_u == 'M' and g_v == 'F':
						st_title = "Step-brother / Step-sister"
					elif g_u == 'F' and g_v == 'M':
						st_title = "Step-sister / Step-brother"
					else:
						st_title = "Step-sibling"

					in_law_entries.append({
						'category': 'in_law',
						'title': st_title,
						'detail': f"{st_title} ({u_name}'s parent {p_u_name} is married to {v_name}'s parent {p_v_name})",
						'lineages': [f"{u_name} ← |{p_u_name} (Spouse) ↔ {p_v_name}| → {v_name}"],
					})

	dedup_map: Dict[Tuple[str, str, str], dict] = {}
	dedup_entries: List[dict] = []
	for entry in in_law_entries:
		key = (entry['category'], entry['title'], entry['detail'])
		if key not in dedup_map:
			cloned = {
				'category': entry['category'],
				'title': entry['title'],
				'detail': entry['detail'],
				'lineages': list(entry['lineages']),
			}
			dedup_map[key] = cloned
			dedup_entries.append(cloned)
		else:
			existing_lineages = dedup_map[key]['lineages']
			for lin in entry['lineages']:
				if lin not in existing_lineages:
					existing_lineages.append(lin)

	return dedup_entries


def analyze_family_pair(
	u: str,
	v: str,
	nodes_dict: Dict[str, str],
	node_colors: Dict[str, str],
	parents_map: Dict[str, List[str]],
	children_map: Dict[str, List[str]],
	spouses_map: Dict[str, Set[str]],
	ancestor_paths: dict,
	ancestor_dist: dict,
) -> FamilyRelationshipResult:
	u_name = nodes_dict.get(u, str(u))
	v_name = nodes_dict.get(v, str(v))
	g_u = detect_gender(node_colors.get(u, ''))
	g_v = detect_gender(node_colors.get(v, ''))

	blood_entries = _analyze_blood_relationships(
		u, v, u_name, v_name, g_u, g_v,
		nodes_dict, children_map, ancestor_paths, ancestor_dist,
	)
	in_law_entries = _analyze_in_law_relationships(
		u, v, u_name, v_name, g_u, g_v, bool(blood_entries),
		nodes_dict, parents_map, children_map, spouses_map, ancestor_dist,
	)

	all_entries = blood_entries + in_law_entries
	if not all_entries:
		return FamilyRelationshipResult(
			category='irrelevant',
			primary_title='IRRELEVANT',
			details=['No blood or marriage relationship found.'],
		)

	primary = blood_entries[0] if blood_entries else in_law_entries[0]
	details: List[str] = []
	seen_details: Set[str] = set()
	lineages: List[str] = []
	seen_lineages: Set[str] = set()

	for entry in all_entries:
		detail = entry['detail']
		if detail not in seen_details:
			seen_details.add(detail)
			details.append(detail)
		for l in entry['lineages']:
			if l not in seen_lineages:
				seen_lineages.add(l)
				lineages.append(l)

	return FamilyRelationshipResult(
		category=primary['category'],
		primary_title=primary['title'],
		details=details,
		lineages=lineages,
	)


def _ancestor_in_law_term(dist: int, gender: str) -> str:
	if dist == 1:
		return "Father-in-law" if gender == 'M' else "Mother-in-law" if gender == 'F' else "Parent-in-law"
	if dist == 2:
		return "Grandfather-in-law" if gender == 'M' else "Grandmother-in-law" if gender == 'F' else "Grandparent-in-law"
	if dist == 3:
		return (
			"Great-Grandfather-in-law (Grand-grandfather-in-law)" if gender == 'M'
			else "Great-Grandmother-in-law (Grand-grandmother-in-law)" if gender == 'F'
			else "Great-Grandparent-in-law"
		)
	if dist == 4:
		return "Great-Great-Grandfather-in-law" if gender == 'M' else "Great-Great-Grandmother-in-law" if gender == 'F' else "Great-Great-Grandparent-in-law"
	k = dist - 2
	return f"{k}-Great-Grandfather-in-law" if gender == 'M' else f"{k}-Great-Grandmother-in-law" if gender == 'F' else f"{k}-Great-Grandparent-in-law"


def _descendant_in_law_term(dist: int, gender: str) -> str:
	if dist == 1:
		return "Son-in-law" if gender == 'M' else "Daughter-in-law" if gender == 'F' else "Child-in-law"
	if dist == 2:
		return "Grandson-in-law" if gender == 'M' else "Granddaughter-in-law" if gender == 'F' else "Grandchild-in-law"
	if dist == 3:
		return (
			"Great-Grandson-in-law (Grand-grandson-in-law)" if gender == 'M'
			else "Great-Granddaughter-in-law (Grand-granddaughter-in-law)" if gender == 'F'
			else "Great-Grandchild-in-law"
		)
	if dist == 4:
		return "Great-Great-Grandson-in-law" if gender == 'M' else "Great-Great-Granddaughter-in-law" if gender == 'F' else "Great-Great-Grandchild-in-law"
	k = dist - 2
	return f"{k}-Great-Grandson-in-law" if gender == 'M' else f"{k}-Great-Granddaughter-in-law" if gender == 'F' else f"{k}-Great-Grandchild-in-law"


def _step_ancestor_term(dist: int, gender: str) -> str:
	if dist == 1:
		return "Step-father" if gender == 'M' else "Step-mother" if gender == 'F' else "Step-parent"
	if dist == 2:
		return "Step-grandfather" if gender == 'M' else "Step-grandmother" if gender == 'F' else "Step-grandparent"
	if dist == 3:
		return "Step-great-grandfather" if gender == 'M' else "Step-great-grandmother" if gender == 'F' else "Step-great-grandparent"
	if dist == 4:
		return "Step-great-great-grandfather" if gender == 'M' else "Step-great-great-grandmother" if gender == 'F' else "Step-great-great-grandparent"
	k = dist - 2
	return f"Step-{k}-great-grandfather" if gender == 'M' else f"Step-{k}-great-grandmother" if gender == 'F' else f"Step-{k}-great-grandparent"


def _step_descendant_term(dist: int, gender: str) -> str:
	if dist == 1:
		return "Step-son" if gender == 'M' else "Step-daughter" if gender == 'F' else "Step-child"
	if dist == 2:
		return "Step-grandson" if gender == 'M' else "Step-granddaughter" if gender == 'F' else "Step-grandchild"
	if dist == 3:
		return "Step-great-grandson" if gender == 'M' else "Step-great-granddaughter" if gender == 'F' else "Step-great-grandchild"
	if dist == 4:
		return "Step-great-great-grandson" if gender == 'M' else "Step-great-great-granddaughter" if gender == 'F' else "Step-great-great-grandchild"
	k = dist - 2
	return f"Step-{k}-great-grandson" if gender == 'M' else f"Step-{k}-great-granddaughter" if gender == 'F' else f"Step-{k}-great-grandchild"


def _uncle_aunt_in_law_term(dist: int, gender: str) -> str:
	if dist == 2:
		return "Uncle-in-law" if gender == 'M' else "Aunt-in-law" if gender == 'F' else "Uncle/Aunt-in-law"
	if dist == 3:
		return (
			"Great-Uncle-in-law (Grand-uncle-in-law)" if gender == 'M'
			else "Great-Aunt-in-law (Grand-aunt-in-law)" if gender == 'F'
			else "Great-Uncle/Aunt-in-law"
		)
	k = dist - 2
	return f"{k}-Great-Uncle-in-law" if gender == 'M' else f"{k}-Great-Aunt-in-law" if gender == 'F' else f"{k}-Great-Uncle/Aunt-in-law"


def _nephew_niece_in_law_term(dist: int, gender: str) -> str:
	if dist == 2:
		return "Nephew-in-law" if gender == 'M' else "Niece-in-law" if gender == 'F' else "Nephew/Niece-in-law"
	if dist == 3:
		return (
			"Great-Nephew-in-law (Grand-nephew-in-law)" if gender == 'M'
			else "Great-Niece-in-law (Grand-niece-in-law)" if gender == 'F'
			else "Great-Nephew/Niece-in-law"
		)
	k = dist - 2
	return f"{k}-Great-Nephew-in-law" if gender == 'M' else f"{k}-Great-Niece-in-law" if gender == 'F' else f"{k}-Great-Nephew/Niece-in-law"