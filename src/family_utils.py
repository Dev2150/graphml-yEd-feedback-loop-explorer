"""
Kinship and genealogical relationship analyzer for family trees.
Supports:
  - Direct lineage: Parent/Child, Grandparent, Grand-grandparent, Grand-grand-grandparent
  - Sibling relationships
  - Uncle / Aunt & Nephew / Niece (including Great/Grand-uncle and Grand-nephew)
  - 1st, 2nd, and 3rd degree cousins (and removed variants)
  - In-law & Affinity variants: Spouses, Parents-in-law, Siblings-in-law, Children-in-law,
    Uncles/Aunts-in-law, Grandparents-in-law, Cousins-in-law, Co-parents-in-law, Step-family.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple
import networkx as nx

FAMILY_CONNECTION_TYPES = {
	'family', 'family-descendance', 'descendance', 'genealogy', 'tree', 'familytree', 'family-tree'
}

SPOUSE_KEYWORDS = (
	'spouse', 'wife', 'husband', 'married', 'partner', 'couple',
	'casad', 'matrimoni', 'espos', 'm.'
)


def ordinal(n: int) -> str:
	if 11 <= (n % 100) <= 13:
		return f"{n}th"
	rem = n % 10
	if rem == 1:
		return f"{n}st"
	elif rem == 2:
		return f"{n}nd"
	elif rem == 3:
		return f"{n}rd"
	return f"{n}th"


def times_removed_str(r: int) -> str:
	if r == 0:
		return ""
	if r == 1:
		return " once removed"
	if r == 2:
		return " twice removed"
	return f" {r}x removed"


@dataclass
class FamilyRelationshipResult:
	category: str  # 'parent_child', 'grandparent', 'sibling', 'uncle_nephew', 'first_cousin', 'second_third_cousin', 'in_law', 'irrelevant'
	primary_title: str
	details: List[str] = field(default_factory=list)
	lineages: List[str] = field(default_factory=list)

	@property
	def is_relevant(self) -> bool:
		return self.category != 'irrelevant'


def is_spouse_edge(u: str, v: str, edge_labels: Dict[Tuple[str, str], str]) -> bool:
	lbl = edge_labels.get((u, v), '').lower()
	return any(kw in lbl for kw in SPOUSE_KEYWORDS)


def build_family_structures(g: nx.DiGraph, edge_labels: Dict[Tuple[str, str], str]):
	parents_map = defaultdict(list)
	children_map = defaultdict(list)
	spouses_map = defaultdict(set)

	# 1. Classify edges into parent-child vs explicit spouse edges
	for u, v in g.edges():
		if is_spouse_edge(u, v, edge_labels) or is_spouse_edge(v, u, edge_labels):
			spouses_map[u].add(v)
			spouses_map[v].add(u)
		else:
			# u is parent of v
			parents_map[v].append(u)
			children_map[u].append(v)

	# 2. Co-parents (two people who share at least one child are partners/spouses)
	for child, p_list in parents_map.items():
		for i in range(len(p_list)):
			for j in range(i + 1, len(p_list)):
				p1, p2 = p_list[i], p_list[j]
				spouses_map[p1].add(p2)
				spouses_map[p2].add(p1)

	return parents_map, children_map, spouses_map


def compute_all_ancestors(nodes: List[str], parents_map: Dict[str, List[str]]):
	"""
	For every node, precomputes:
	  ancestor_paths[node][ancestor] -> list of all shortest paths from ancestor to node [ancestor, ..., node]
	  ancestor_dist[node][ancestor] -> distance (generations)
	"""
	ancestor_paths = {}
	ancestor_dist = {}

	for n in nodes:
		paths_to_n = {n: [[n]]}
		dist_to_n = {n: 0}
		queue = deque([n])

		while queue:
			curr = queue.popleft()
			curr_d = dist_to_n[curr]
			for p in parents_map.get(curr, []):
				if p not in dist_to_n:
					dist_to_n[p] = curr_d + 1
					paths_to_n[p] = []
					queue.append(p)
				if dist_to_n[p] == curr_d + 1:
					for subpath in paths_to_n[curr]:
						paths_to_n[p].append([p] + subpath)

		ancestor_paths[n] = paths_to_n
		ancestor_dist[n] = dist_to_n

	return ancestor_paths, ancestor_dist


def format_lineage_path(path_u_to_a: List[str], path_a_to_v: List[str], nodes_dict: Dict[str, str]) -> str:
	parts = []
	for i in range(len(path_u_to_a) - 1):
		parts.append(nodes_dict.get(path_u_to_a[i], str(path_u_to_a[i])))
		parts.append("←")
	parts.append(nodes_dict.get(path_u_to_a[-1], str(path_u_to_a[-1])))
	for i in range(1, len(path_a_to_v)):
		parts.append("→")
		parts.append(nodes_dict.get(path_a_to_v[i], str(path_a_to_v[i])))
	return " ".join(parts)


def classify_blood_relationship(d1: int, d2: int, u_name: str, v_name: str) -> Tuple[str, str, str]:
	"""
	d1 = distance from common ancestor down to u
	d2 = distance from common ancestor down to v
	Returns (category, title, detail_description)
	"""
	# Direct Lineage
	if d1 == 0 and d2 == 1:
		return 'parent_child', 'Parent / Child', f"{u_name} is Parent of {v_name}"
	if d1 == 1 and d2 == 0:
		return 'parent_child', 'Parent / Child', f"{u_name} is Child of {v_name}"
	if d1 == 0 and d2 == 2:
		return 'grandparent', 'Grandparent / Grandchild', f"{u_name} is Grandparent of {v_name}"
	if d1 == 2 and d2 == 0:
		return 'grandparent', 'Grandparent / Grandchild', f"{u_name} is Grandchild of {v_name}"
	if d1 == 0 and d2 == 3:
		return 'grandparent', 'Grand-grandparent / Grand-grandchild (Great-grandparent)', f"{u_name} is Grand-grandparent (Great-grandparent) of {v_name}"
	if d1 == 3 and d2 == 0:
		return 'grandparent', 'Grand-grandparent / Grand-grandchild (Great-grandparent)', f"{u_name} is Grand-grandchild (Great-grandchild) of {v_name}"
	if d1 == 0 and d2 == 4:
		return 'grandparent', 'Grand-grand-grandparent / Grand-grand-grandchild (Great-great-grandparent)', f"{u_name} is Grand-grand-grandparent (Great-great-grandparent) of {v_name}"
	if d1 == 4 and d2 == 0:
		return 'grandparent', 'Grand-grand-grandparent / Grand-grand-grandchild (Great-great-grandparent)', f"{u_name} is Grand-grand-grandchild (Great-great-grandchild) of {v_name}"
	if d1 == 0 and d2 >= 5:
		k = d2 - 2
		return 'grandparent', f"{k}-Great-grandparent / Grandchild", f"{u_name} is {k}-Great-grandparent of {v_name}"
	if d1 >= 5 and d2 == 0:
		k = d1 - 2
		return 'grandparent', f"{k}-Great-grandparent / Grandchild", f"{u_name} is {k}-Great-grandchild of {v_name}"

	# Siblings
	if d1 == 1 and d2 == 1:
		return 'sibling', 'Sibling', f"Sibling ({u_name} and {v_name} are Siblings)"

	# Uncles / Aunts & Nephews / Nieces
	if d1 == 1 and d2 == 2:
		return 'uncle_nephew', 'Uncle / Aunt & Nephew / Niece', f"{u_name} is Uncle/Aunt of {v_name}"
	if d1 == 2 and d2 == 1:
		return 'uncle_nephew', 'Uncle / Aunt & Nephew / Niece', f"{u_name} is Nephew/Niece of {v_name}"
	if d1 == 1 and d2 == 3:
		return 'uncle_nephew', 'Grand-uncle / Grand-aunt (Great-Uncle / Aunt)', f"{u_name} is Grand-uncle/aunt (Great-Uncle/Aunt) of {v_name}"
	if d1 == 3 and d2 == 1:
		return 'uncle_nephew', 'Grand-uncle / Grand-aunt (Great-Uncle / Aunt)', f"{u_name} is Grand-nephew/niece (Great-Nephew/Niece) of {v_name}"
	if d1 == 1 and d2 >= 4:
		k = d2 - 2
		return 'uncle_nephew', f"{k}-Great-Uncle / Aunt", f"{u_name} is {k}-Great-Uncle/Aunt of {v_name}"
	if d1 >= 4 and d2 == 1:
		k = d1 - 2
		return 'uncle_nephew', f"{k}-Great-Nephew / Niece", f"{u_name} is {k}-Great-Nephew/Niece of {v_name}"

	# Cousins (d1 >= 2 and d2 >= 2)
	deg = min(d1, d2) - 1
	rem = abs(d1 - d2)
	ord_deg = ordinal(deg)
	rem_str = times_removed_str(rem)

	cat = 'first_cousin' if deg == 1 else 'second_third_cousin'
	if rem == 0:
		title = f"{ord_deg} degree cousin"
		detail = f"{ord_deg} degree cousin"
	else:
		title = f"{ord_deg} cousin{rem_str}"
		if d1 < d2:
			detail = f"{ord_deg} cousin{rem_str}"
		else:
			detail = f"{ord_deg} cousin{rem_str}"

	return cat, title, detail


def analyze_family_pair(
	u: str,
	v: str,
	nodes_dict: Dict[str, str],
	parents_map: Dict[str, List[str]],
	children_map: Dict[str, List[str]],
	spouses_map: Dict[str, Set[str]],
	ancestor_paths: dict,
	ancestor_dist: dict
) -> FamilyRelationshipResult:
	u_name = nodes_dict.get(u, str(u))
	v_name = nodes_dict.get(v, str(v))

	anc_u = ancestor_paths[u]
	anc_v = ancestor_paths[v]
	dist_u = ancestor_dist[u]
	dist_v = ancestor_dist[v]

	common_ancestors = set(dist_u.keys()).intersection(set(dist_v.keys()))

	# 1. Blood Relationships
	blood_entries = []
	if common_ancestors:
		# Filter to Most Recent Common Ancestors (MRCAs)
		mrcas = [a for a in common_ancestors if not any(c in common_ancestors for c in children_map.get(a, []))]
		mrcas.sort(key=lambda a: (dist_u[a] + dist_v[a], nodes_dict.get(a, '')))

		seen_signatures = set()
		for a in mrcas:
			d1 = dist_u[a]
			d2 = dist_v[a]
			cat, title, detail = classify_blood_relationship(d1, d2, u_name, v_name)

			# Generate Lineage examples
			lineage_strs = []
			paths_u = anc_u[a]
			paths_v = anc_v[a]
			for pu in paths_u[:2]:
				for pv in paths_v[:2]:
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
					'total_dist': d1 + d2
				})

	# 2. In-Law / Affinity Relationships
	in_law_entries = []

	# Direct Spouse / Partner
	if v in spouses_map.get(u, set()):
		in_law_entries.append({
			'category': 'in_law',
			'title': 'Spouse / Partner',
			'detail': f"Spouse / Partner ({u_name} ↔ {v_name})",
			'lineages': [f"{u_name} (Spouse) ↔ {v_name}"]
		})

	# u related to spouse(s) of v
	for s_v in spouses_map.get(v, set()):
		if s_v == u:
			continue
		s_v_name = nodes_dict.get(s_v, str(s_v))
		s_anc = ancestor_paths.get(s_v, {})
		s_dist = ancestor_dist.get(s_v, {})
		s_ca = set(dist_u.keys()).intersection(set(s_dist.keys()))
		if s_ca:
			s_mrcas = [a for a in s_ca if not any(c in s_ca for c in children_map.get(a, []))]
			for a in s_mrcas:
				d1 = dist_u[a]
				d2 = s_dist[a]
				if d1 == 0 and d2 == 1:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Parent-in-law / Child-in-law',
						'detail': f"{u_name} is Father/Mother-in-law of {v_name}",
						'lineages': [f"{u_name} → {s_v_name} (Spouse) ↔ {v_name}"]
					})
				elif d1 == 1 and d2 == 0:
					if u not in children_map.get(v, []):
						in_law_entries.append({
							'category': 'in_law',
							'title': 'Step-parent / Step-child',
							'detail': f"{u_name} is Step-child of {v_name}",
							'lineages': [f"{u_name} ← {s_v_name} (Spouse) ↔ {v_name}"]
						})
				elif d1 == 1 and d2 == 1:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Brother-in-law / Sister-in-law (Sibling-in-law)',
						'detail': f"{u_name} is Sibling-in-law of {v_name} ({u_name} is sibling of {v_name}'s spouse {s_v_name})",
						'lineages': [f"{u_name} ← {nodes_dict.get(a, '')} → {s_v_name} (Spouse) ↔ {v_name}"]
					})
				elif d1 == 0 and d2 == 2:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Grandparent-in-law / Grandchild-in-law',
						'detail': f"{u_name} is Grandparent-in-law of {v_name} ({v_name} is Grandchild-in-law)",
						'lineages': [f"{u_name} → ... → {s_v_name} (Spouse) ↔ {v_name}"]
					})
				elif d1 == 0 and d2 == 3:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Grand-grandparent-in-law (Great-grandparent-in-law)',
						'detail': f"{u_name} is Grand-grandparent-in-law of {v_name}",
						'lineages': [f"{u_name} → ... → {s_v_name} (Spouse) ↔ {v_name}"]
					})
				elif d1 == 1 and d2 == 2:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Uncle-in-law / Aunt-in-law',
						'detail': f"{u_name} is Uncle/Aunt-in-law of {v_name} ({u_name} is uncle/aunt of {v_name}'s spouse {s_v_name})",
						'lineages': [f"{u_name} ← ... → {s_v_name} (Spouse) ↔ {v_name}"]
					})
				elif d1 == 2 and d2 == 1:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Nephew-in-law / Niece-in-law',
						'detail': f"{u_name} is Nephew/Niece-in-law of {v_name} ({u_name} is nephew/niece of {v_name}'s spouse {s_v_name})",
						'lineages': [f"{u_name} ← ... → {s_v_name} (Spouse) ↔ {v_name}"]
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
						'lineages': [f"{u_name} ← ... → {s_v_name} (Spouse) ↔ {v_name}"]
					})

	# v related to spouse(s) of u
	for s_u in spouses_map.get(u, set()):
		if s_u == v:
			continue
		s_u_name = nodes_dict.get(s_u, str(s_u))
		s_anc = ancestor_paths.get(s_u, {})
		s_dist = ancestor_dist.get(s_u, {})
		s_ca = set(dist_v.keys()).intersection(set(s_dist.keys()))
		if s_ca:
			s_mrcas = [a for a in s_ca if not any(c in s_ca for c in children_map.get(a, []))]
			for a in s_mrcas:
				d1 = dist_v[a]
				d2 = s_dist[a]
				if d1 == 0 and d2 == 1:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Parent-in-law / Child-in-law',
						'detail': f"{u_name} is Son/Daughter-in-law of {v_name}",
						'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← {v_name}"]
					})
				elif d1 == 1 and d2 == 0:
					if v not in children_map.get(u, []):
						in_law_entries.append({
							'category': 'in_law',
							'title': 'Step-parent / Step-child',
							'detail': f"{u_name} is Step-parent of {v_name}",
							'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} → {v_name}"]
						})
				elif d1 == 1 and d2 == 1:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Brother-in-law / Sister-in-law (Sibling-in-law)',
						'detail': f"{u_name} is Sibling-in-law of {v_name} ({v_name} is sibling of {u_name}'s spouse {s_u_name})",
						'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← {nodes_dict.get(a, '')} → {v_name}"]
					})
				elif d1 == 0 and d2 == 2:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Grandparent-in-law / Grandchild-in-law',
						'detail': f"{u_name} is Grandchild-in-law of {v_name}",
						'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← ... ← {v_name}"]
					})
				elif d1 == 0 and d2 == 3:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Grand-grandparent-in-law (Great-grandparent-in-law)',
						'detail': f"{u_name} is Grand-grandchild-in-law of {v_name}",
						'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← ... ← {v_name}"]
					})
				elif d1 == 1 and d2 == 2:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Nephew-in-law / Niece-in-law',
						'detail': f"{u_name} is Nephew/Niece-in-law of {v_name} ({v_name} is uncle/aunt of {u_name}'s spouse {s_u_name})",
						'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← ... → {v_name}"]
					})
				elif d1 == 2 and d2 == 1:
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Uncle-in-law / Aunt-in-law',
						'detail': f"{u_name} is Uncle/Aunt-in-law of {v_name} ({v_name} is nephew/niece of {u_name}'s spouse {s_u_name})",
						'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← ... → {v_name}"]
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
						'lineages': [f"{u_name} (Spouse) ↔ {s_u_name} ← ... → {v_name}"]
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
					'lineages': [f"{u_name} → {c_u_name} (Spouse) ↔ {c_v_name} ← {v_name}"]
				})

	# Step-siblings (parents married, no shared biological parents)
	if not blood_entries:
		for p_u in parents_map.get(u, []):
			for p_v in parents_map.get(v, []):
				if p_v in spouses_map.get(p_u, set()):
					p_u_name = nodes_dict.get(p_u, str(p_u))
					p_v_name = nodes_dict.get(p_v, str(p_v))
					in_law_entries.append({
						'category': 'in_law',
						'title': 'Step-sibling',
						'detail': f"Step-sibling ({u_name}'s parent {p_u_name} is married to {v_name}'s parent {p_v_name})",
						'lineages': [f"{u_name} ← {p_u_name} (Spouse) ↔ {p_v_name} → {v_name}"]
					})

	# Merge and format results
	all_entries = blood_entries + in_law_entries
	if not all_entries:
		return FamilyRelationshipResult(
			category='irrelevant',
			primary_title='IRRELEVANT',
			details=['No blood or marriage relationship found.']
		)

	# Primary entry determined by blood relation if available, else in-law
	primary = blood_entries[0] if blood_entries else in_law_entries[0]

	details = []
	lineages = []
	seen_lineages = set()

	for entry in all_entries:
		details.append(entry['detail'])
		for l in entry['lineages']:
			if l not in seen_lineages:
				seen_lineages.add(l)
				lineages.append(l)

	return FamilyRelationshipResult(
		category=primary['category'],
		primary_title=primary['title'],
		details=details,
		lineages=lineages
	)