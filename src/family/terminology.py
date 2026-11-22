from typing import Dict, List

FAMILY_CONNECTION_TYPES = {
	'family', 'family-descendance', 'descendance', 'genealogy', 'tree', 'familytree', 'family-tree'
}

SPOUSE_KEYWORDS = (
	'spouse', 'wife', 'husband', 'married', 'partner', 'couple',
	'casad', 'matrimoni', 'espos', 'm.'
)


def get_parent_term(gender: str) -> str:
	return "Father" if gender == 'M' else "Mother" if gender == 'F' else "Parent"


def get_child_term(gender: str) -> str:
	return "Son" if gender == 'M' else "Daughter" if gender == 'F' else "Child"


def get_grandparent_term(gender: str) -> str:
	return "Grandfather" if gender == 'M' else "Grandmother" if gender == 'F' else "Grandparent"


def get_grandchild_term(gender: str) -> str:
	return "Grandson" if gender == 'M' else "Granddaughter" if gender == 'F' else "Grandchild"


def get_great_grandparent_term(gender: str) -> str:
	return "Great-Grandfather (Grand-grandfather)" if gender == 'M' else "Great-Grandmother (Grand-grandmother)" if gender == 'F' else "Great-Grandparent (Grand-grandparent)"


def get_great_grandchild_term(gender: str) -> str:
	return "Great-Grandson (Grand-grandson)" if gender == 'M' else "Great-Granddaughter (Grand-granddaughter)" if gender == 'F' else "Great-Grandchild (Grand-grandchild)"


def get_great_great_grandparent_term(gender: str) -> str:
	return "Great-Great-Grandfather (Grand-grand-grandfather)" if gender == 'M' else "Great-Great-Grandmother (Grand-grand-grandmother)" if gender == 'F' else "Great-Great-Grandparent (Grand-grand-grandparent)"


def get_great_great_grandchild_term(gender: str) -> str:
	return "Great-Great-Grandson (Grand-grand-grandson)" if gender == 'M' else "Great-Great-Granddaughter (Grand-grand-granddaughter)" if gender == 'F' else "Great-Great-Grandchild (Grand-grand-grandchild)"


def get_sibling_term(gender: str) -> str:
	return "Brother" if gender == 'M' else "Sister" if gender == 'F' else "Sibling"


def get_uncle_aunt_term(gender: str) -> str:
	return "Uncle" if gender == 'M' else "Aunt" if gender == 'F' else "Uncle/Aunt"


def get_nephew_niece_term(gender: str) -> str:
	return "Nephew" if gender == 'M' else "Niece" if gender == 'F' else "Nephew/Niece"


def get_great_uncle_aunt_term(gender: str) -> str:
	return "Great-Uncle (Grand-uncle)" if gender == 'M' else "Great-Aunt (Grand-aunt)" if gender == 'F' else "Great-Uncle/Aunt"


def get_great_nephew_niece_term(gender: str) -> str:
	return "Great-Nephew (Grand-nephew)" if gender == 'M' else "Great-Niece (Grand-niece)" if gender == 'F' else "Great-Nephew/Niece"


def get_spouse_term(gender: str) -> str:
	return "Husband" if gender == 'M' else "Wife" if gender == 'F' else "Spouse/Partner"


def ordinal(n: int) -> str:
	if 11 <= (n % 100) <= 13:
		return f"{n}th"
	rem = n % 10
	if rem == 1:
		return f"{n}st"
	if rem == 2:
		return f"{n}nd"
	if rem == 3:
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