import copy
import os
from typing import Callable, Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from src.android_file_picker import has_all_files_access, request_all_files_access
from src.app_controller import AppController, parse_graph_settings_dict
from src.config import Config, GRAPH_SETTING_KEYS, build_effective_config
from src.io_graphml import list_graph_elements_and_groups
from src.storage import get_sync_folder


def open_exclusion_picker_popup(
	graph_path: str,
	ti_excluded: TextInput,
	on_show_message: Callable[[str, str], None],
	on_track_popup: Callable[[Popup], None],
):
	if not graph_path or not os.path.isfile(graph_path):
		on_show_message('No Graph Loaded', 'Load a GraphML file first to pick elements or groups.')
		return

	try:
		groups, elements = list_graph_elements_and_groups(graph_path)
	except Exception as exc:
		on_show_message('Inspect Error', f'Could not read GraphML elements:\n{exc}')
		return

	all_items = [('Group', g) for g in groups] + [('Node', e) for e in elements]
	current_lower = {line.strip().lower(): line.strip() for line in ti_excluded.text.splitlines() if line.strip()}
	selected_map = {(kind, name): (name.lower() in current_lower) for kind, name in all_items}

	content = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))
	search_ti = TextInput(hint_text='Filter groups / nodes...', multiline=False, size_hint_y=None, height=dp(38))
	content.add_widget(search_ti)

	sv = ScrollView()
	lst = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(2))
	lst.bind(minimum_height=lst.setter('height'))
	sv.add_widget(lst)
	content.add_widget(sv)

	def _render_rows(*_):
		lst.clear_widgets()
		q = search_ti.text.strip().lower()
		for kind, name in all_items:
			if q and q not in name.lower() and q not in kind.lower():
				continue
			row_box = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
			cb = CheckBox(active=selected_map[(kind, name)], size_hint_x=None, width=dp(36))
			cb.bind(active=lambda _inst, val, k=(kind, name): selected_map.__setitem__(k, bool(val)))
			lbl = Label(text=f'[{kind}] {name}', halign='left', valign='middle', font_size=dp(13))
			lbl.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
			row_box.add_widget(cb)
			row_box.add_widget(lbl)
			lst.add_widget(row_box)

	search_ti.bind(text=_render_rows)
	_render_rows()

	popup = Popup(title='Pick Excluded Groups / Nodes', content=content, size_hint=(0.94, 0.86))

	def _confirm(*_):
		seen = set()
		result = []
		for (_kind, name), is_checked in selected_map.items():
			if is_checked and name.lower() not in seen:
				seen.add(name.lower())
				result.append(name)
		known_lower = {name.lower() for _, name in all_items}
		for low, orig in current_lower.items():
			if low not in known_lower and low not in seen:
				seen.add(low)
				result.append(orig)
		ti_excluded.text = '\n'.join(result)
		popup.dismiss()

	def _clear_all(*_):
		for k in selected_map:
			selected_map[k] = False
		_render_rows()

	btn_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
	btn_row.add_widget(Button(text='Clear All', on_release=_clear_all))
	btn_row.add_widget(Button(text='Apply Selection', on_release=_confirm))
	btn_row.add_widget(Button(text='Cancel', on_release=lambda *_: popup.dismiss()))
	content.add_widget(btn_row)
	on_track_popup(popup)


def open_config_popup(
	controller: AppController,
	is_desktop: bool,
	on_open_folder_picker: Callable[[str, str, Callable[[str], None]], None],
	on_show_message: Callable[[str, str], None],
	on_track_popup: Callable[[Popup], None],
	on_load_graph: Callable[[str, Optional[Config], Optional[dict]], None],
):
	g_cfg = controller.base_config
	loc = controller.local_overrides
	cur_path = controller.current_graph_path
	has_file = bool(cur_path and os.path.isfile(cur_path))

	outer = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))
	if has_file:
		active_count = sum(1 for k in GRAPH_SETTING_KEYS if k in loc)
		status_text = f"{os.path.basename(cur_path)} ({active_count}/{len(GRAPH_SETTING_KEYS)} local)"
	else:
		status_text = 'No file loaded — Global & App Settings only'

	status_lbl = Label(
		text=status_text,
		size_hint_y=None,
		height=dp(22),
		font_size=dp(12),
		bold=True,
		color=(0.75, 0.85, 1.0, 1),
	)
	outer.add_widget(status_lbl)

	tab_bar = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
	btn_tab_graph = Button(text='Graph (Global/Local)', font_size=dp(12), background_color=(0.24, 0.45, 0.70, 1))
	btn_tab_app = Button(text='App Settings', font_size=dp(12), background_color=(0.25, 0.27, 0.30, 1))
	tab_bar.add_widget(btn_tab_graph)
	tab_bar.add_widget(btn_tab_app)
	outer.add_widget(tab_bar)

	content_area = BoxLayout()
	outer.add_widget(content_area)

	# ------------------------------------------------------------------
	# View 1: Graph Settings
	# ------------------------------------------------------------------
	graph_scroll = ScrollView()
	form = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(8), padding=dp(4))
	form.bind(minimum_height=form.setter('height'))
	graph_scroll.add_widget(form)

	global_fields = {}
	local_enabled_cbs = {}
	local_fields = {}
	local_widgets = {}

	def update_local_state(key: str):
		enabled = bool(has_file and local_enabled_cbs[key].active)
		for w in local_widgets.get(key, []):
			w.disabled = not enabled

	def add_card_header(key: str, label: str):
		hdr = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(4))
		lbl = Label(text=label, halign='left', valign='middle', bold=True, font_size=dp(12))
		lbl.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
		hdr.add_widget(lbl)

		is_local = has_file and (key in loc)
		hdr.add_widget(Label(text='Local', size_hint_x=None, width=dp(38), font_size=dp(11), color=(0.75, 0.85, 1.0, 1)))
		en_cb = CheckBox(active=is_local, disabled=not has_file, size_hint_x=None, width=dp(34))
		en_cb.bind(active=lambda _inst, _val, k=key: update_local_state(k))
		local_enabled_cbs[key] = en_cb
		hdr.add_widget(en_cb)
		return hdr, is_local

	def add_text_pair(key: str, label: str, g_val, l_raw_val=None, fmt_fn=str):
		card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(70), spacing=dp(2))
		hdr, is_local = add_card_header(key, label)
		card.add_widget(hdr)

		g_str = fmt_fn(g_val)
		l_str = fmt_fn(l_raw_val) if is_local else g_str

		row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
		g_box = BoxLayout(spacing=dp(3))
		g_box.add_widget(Label(text='G:', size_hint_x=None, width=dp(20), font_size=dp(11)))
		g_ti = TextInput(text=g_str, multiline=False, font_size=dp(12))
		g_box.add_widget(g_ti)

		l_box = BoxLayout(spacing=dp(3))
		l_box.add_widget(Label(text='L:', size_hint_x=None, width=dp(20), font_size=dp(11)))
		l_ti = TextInput(text=l_str, multiline=False, font_size=dp(12))
		l_box.add_widget(l_ti)

		row.add_widget(g_box)
		row.add_widget(l_box)
		card.add_widget(row)
		form.add_widget(card)

		global_fields[key] = g_ti
		local_fields[key] = l_ti
		local_widgets[key] = [l_ti]
		update_local_state(key)

	def add_spinner_pair(key: str, label: str, g_val: str, l_raw_val, values: tuple):
		card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(70), spacing=dp(2))
		hdr, is_local = add_card_header(key, label)
		card.add_widget(hdr)

		row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
		g_box = BoxLayout(spacing=dp(3))
		g_box.add_widget(Label(text='G:', size_hint_x=None, width=dp(20), font_size=dp(11)))
		g_sp = Spinner(text=str(g_val), values=values, font_size=dp(12))
		g_box.add_widget(g_sp)

		l_box = BoxLayout(spacing=dp(3))
		l_box.add_widget(Label(text='L:', size_hint_x=None, width=dp(20), font_size=dp(11)))
		l_sp = Spinner(text=str(l_raw_val) if is_local else str(g_val), values=values, font_size=dp(12))
		l_box.add_widget(l_sp)

		row.add_widget(g_box)
		row.add_widget(l_box)
		card.add_widget(row)
		form.add_widget(card)

		global_fields[key] = g_sp
		local_fields[key] = l_sp
		local_widgets[key] = [l_sp]
		update_local_state(key)

	def add_bool_pair(key: str, label: str, g_val: bool, l_raw_val):
		card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(66), spacing=dp(2))
		hdr, is_local = add_card_header(key, label)
		card.add_widget(hdr)

		row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
		g_box = BoxLayout(spacing=dp(4))
		g_box.add_widget(Label(text='Global:', size_hint_x=None, width=dp(50), font_size=dp(12)))
		g_cb = CheckBox(active=bool(g_val), size_hint_x=None, width=dp(36))
		g_box.add_widget(g_cb)

		l_box = BoxLayout(spacing=dp(4))
		l_box.add_widget(Label(text='Local:', size_hint_x=None, width=dp(46), font_size=dp(12)))
		l_cb = CheckBox(active=bool(l_raw_val) if is_local else bool(g_val), size_hint_x=None, width=dp(36))
		l_box.add_widget(l_cb)

		row.add_widget(g_box)
		row.add_widget(l_box)
		card.add_widget(row)
		form.add_widget(card)

		global_fields[key] = g_cb
		local_fields[key] = l_cb
		local_widgets[key] = [l_cb]
		update_local_state(key)

	add_spinner_pair('connection_type', 'Connection Type', g_cfg.connection_type, loc.get('connection_type'), ('correlation', 'counter', 'family'))
	add_bool_pair('ignore_edge_colors', 'Ignore Edge Colors', g_cfg.ignore_edge_colors, loc.get('ignore_edge_colors'))
	add_text_pair('color_threshold', 'Color Threshold', g_cfg.color_threshold, loc.get('color_threshold'))
	add_bool_pair('show_connections_list', 'Show Connections List', g_cfg.show_connections_list, loc.get('show_connections_list'))
	add_text_pair('connections_skipped', 'Connections Skipped', g_cfg.connections_skipped, loc.get('connections_skipped'))
	add_bool_pair('show_only_edges', 'Show Only Edges', g_cfg.show_only_edges, loc.get('show_only_edges'))
	add_bool_pair('show_edge_labels', 'Show Edge Labels', g_cfg.show_edge_labels, loc.get('show_edge_labels'))
	add_bool_pair('enable_non_cycle_printing', 'Non-Cycle Printing', g_cfg.enable_non_cycle_printing, loc.get('enable_non_cycle_printing'))
	add_bool_pair('sort_by_len', 'Sort Cycles by Length', g_cfg.sort_by_len, loc.get('sort_by_len'))
	add_bool_pair('sort_connections_alphabetically', 'Sort Connections Alpha', g_cfg.sort_connections_alphabetically, loc.get('sort_connections_alphabetically'))
	add_text_pair('max_cycle_length_html', 'Max Cycle Len (HTML)', g_cfg.max_cycle_length_html, loc.get('max_cycle_length_html'))
	add_text_pair('max_indirectness', 'Max Indirectness (HTML)', g_cfg.max_indirectness, loc.get('max_indirectness'))
	add_text_pair('source_node', 'Source Node', g_cfg.source_node, loc.get('source_node'))
	add_text_pair('target_node', 'Target Node', g_cfg.target_node, loc.get('target_node'))
	add_text_pair(
		'block_starting_node',
		'Block Starting Nodes',
		g_cfg.block_starting_node,
		loc.get('block_starting_node'),
		fmt_fn=lambda xs: ', '.join(xs) if isinstance(xs, list) else str(xs or ''),
	)

	# Excluded Elements / Groups (Global + Local)
	excl_card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(132), spacing=dp(2))
	excl_hdr, is_local_excl = add_card_header('excluded_elements', 'Excluded Elements / Groups (1/line)')
	excl_card.add_widget(excl_hdr)

	l_excl_list = (
		loc.get('excluded_elements')
		if (is_local_excl and isinstance(loc.get('excluded_elements'), list))
		else g_cfg.excluded_elements
	)
	excl_row = BoxLayout(size_hint_y=None, height=dp(96), spacing=dp(6))

	g_excl_box = BoxLayout(orientation='vertical', spacing=dp(2))
	g_ti_excl = TextInput(text='\n'.join(g_cfg.excluded_elements), multiline=True, font_size=dp(11))
	g_excl_box.add_widget(g_ti_excl)
	if has_file:
		g_excl_box.add_widget(Button(
			text='Pick Global...',
			size_hint_y=None,
			height=dp(26),
			font_size=dp(11),
			on_release=lambda *_: open_exclusion_picker_popup(cur_path, g_ti_excl, on_show_message, on_track_popup),
		))

	l_excl_box = BoxLayout(orientation='vertical', spacing=dp(2))
	l_ti_excl = TextInput(text='\n'.join(l_excl_list), multiline=True, font_size=dp(11))
	l_excl_box.add_widget(l_ti_excl)
	l_excl_widgets = [l_ti_excl]
	if has_file:
		btn_l_pick = Button(
			text='Pick Local...',
			size_hint_y=None,
			height=dp(26),
			font_size=dp(11),
			on_release=lambda *_: open_exclusion_picker_popup(cur_path, l_ti_excl, on_show_message, on_track_popup),
		)
		l_excl_box.add_widget(btn_l_pick)
		l_excl_widgets.append(btn_l_pick)

	excl_row.add_widget(g_excl_box)
	excl_row.add_widget(l_excl_box)
	excl_card.add_widget(excl_row)
	form.add_widget(excl_card)

	global_fields['excluded_elements'] = g_ti_excl
	local_fields['excluded_elements'] = l_ti_excl
	local_widgets['excluded_elements'] = l_excl_widgets
	update_local_state('excluded_elements')

	add_text_pair('chance_irrelevant', 'Chance Irrelevant', g_cfg.chance_irrelevant, loc.get('chance_irrelevant'))
	add_text_pair('max_cycle_length_game', 'Max Cycle Len (Game)', g_cfg.max_cycle_length_game, loc.get('max_cycle_length_game'))
	add_text_pair('max_indirectness_game', 'Max Indirectness (Game)', g_cfg.max_indirectness_game, loc.get('max_indirectness_game'))
	add_bool_pair('leaf_only', 'Leaf Nodes Only', g_cfg.leaf_only, loc.get('leaf_only'))
	add_bool_pair('include_secondary_cycles', 'Include Secondary Cycles', g_cfg.include_secondary_cycles, loc.get('include_secondary_cycles'))

	# ------------------------------------------------------------------
	# View 2: App Settings
	# ------------------------------------------------------------------
	app_scroll = ScrollView()
	app_form = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(8), padding=dp(6))
	app_form.bind(minimum_height=app_form.setter('height'))
	app_scroll.add_widget(app_form)

	app_info = Label(
		text='App Settings (GraphML folder stored in input.txt; Sync folder stored in sync_settings.json):',
		size_hint_y=None,
		height=dp(36),
		halign='left',
		valign='middle',
		font_size=dp(12),
		color=(0.75, 0.85, 1.0, 1),
	)
	app_info.bind(size=lambda inst, v: setattr(inst, 'text_size', v))
	app_form.add_widget(app_info)

	app_form.add_widget(Label(text='Default GraphML Folder:', size_hint_y=None, height=dp(24), halign='left', font_size=dp(12)))
	row_gml = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
	ti_app_folder = TextInput(
		text=g_cfg.folder_path,
		hint_text='/storage/emulated/0/Documents/Graphs',
		multiline=False,
	)
	row_gml.add_widget(ti_app_folder)
	row_gml.add_widget(Button(
		text='Browse',
		size_hint_x=None,
		width=dp(76),
		font_size=dp(12),
		on_release=lambda *_: on_open_folder_picker(
			'Select Default GraphML Folder',
			ti_app_folder.text,
			lambda p: setattr(ti_app_folder, 'text', p),
		),
	))
	app_form.add_widget(row_gml)

	app_form.add_widget(Label(text='Default File Name / Path:', size_hint_y=None, height=dp(24), halign='left', font_size=dp(12)))
	ti_app_file = TextInput(text=g_cfg.file_name, multiline=False, size_hint_y=None, height=dp(40))
	app_form.add_widget(ti_app_file)

	app_form.add_widget(Label(
		text='Default Sync Folder (for Syncthing):',
		size_hint_y=None,
		height=dp(24),
		halign='left',
		font_size=dp(12),
	))
	row_sync = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
	ti_sync_folder = TextInput(
		text=get_sync_folder(),
		hint_text='/storage/emulated/0/Syncthing/GraphML',
		multiline=False,
	)
	row_sync.add_widget(ti_sync_folder)
	row_sync.add_widget(Button(
		text='Browse',
		size_hint_x=None,
		width=dp(76),
		font_size=dp(12),
		on_release=lambda *_: on_open_folder_picker(
			'Select Default Sync Folder',
			ti_sync_folder.text,
			lambda p: setattr(ti_sync_folder, 'text', p),
		),
	))
	app_form.add_widget(row_sync)

	def _show_tab(tab_name: str):
		content_area.clear_widgets()
		if tab_name == 'graph':
			content_area.add_widget(graph_scroll)
			btn_tab_graph.background_color = (0.24, 0.45, 0.70, 1)
			btn_tab_app.background_color = (0.25, 0.27, 0.30, 1)
		else:
			content_area.add_widget(app_scroll)
			btn_tab_app.background_color = (0.24, 0.45, 0.70, 1)
			btn_tab_graph.background_color = (0.25, 0.27, 0.30, 1)

	btn_tab_graph.bind(on_release=lambda *_: _show_tab('graph'))
	btn_tab_app.bind(on_release=lambda *_: _show_tab('app'))
	_show_tab('graph')

	popup_title = f'Config — {os.path.basename(cur_path)}' if has_file else 'Configuration'
	popup = Popup(title=popup_title, content=outer, size_hint=(0.96, 0.92))

	def _collect_raw(fmap: dict) -> dict:
		return {
			k: (w.active if isinstance(w, CheckBox) else w.text)
			for k, w in fmap.items()
		}

	def _apply(mode: str):
		try:
			global_dict = parse_graph_settings_dict(_collect_raw(global_fields), 'Global')
			new_base = copy.deepcopy(controller.base_config)
			new_base.folder_path = ti_app_folder.text.strip()
			new_base.file_name = ti_app_file.text.strip()
			for k, v in global_dict.items():
				setattr(new_base, k, v)

			new_local = {}
			if has_file:
				local_parsed = parse_graph_settings_dict(_collect_raw(local_fields), 'Local')
				for k in GRAPH_SETTING_KEYS:
					if local_enabled_cbs[k].active:
						new_local[k] = local_parsed[k]
		except ValueError as exc:
			on_show_message('Invalid Value', str(exc))
			return

		sync_path = ti_sync_folder.text.strip()
		if mode == 'save' and sync_path and not is_desktop and not has_all_files_access():
			request_all_files_access()

		try:
			action, path = controller.apply_config(
				new_base,
				new_local,
				mode=mode,
				sync_folder=sync_path,
			)
		except Exception as exc:
			on_show_message('Save Error', str(exc))
			return

		popup.dismiss()

		if action == 'reload_current' and path:
			effective = build_effective_config(controller.base_config, controller.local_overrides, path)
			on_load_graph(path, effective, controller.local_overrides)
		elif action == 'load_default' and path:
			on_load_graph(path, None, None)

	def _clear_all_local(*_):
		for k, cb in local_enabled_cbs.items():
			cb.active = False
			update_local_state(k)

	btn_bar = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
	btn_bar.add_widget(Button(text='Apply (Session)', font_size=dp(12), on_release=lambda *_: _apply('session')))
	btn_bar.add_widget(Button(text='Save & Apply', font_size=dp(12), on_release=lambda *_: _apply('save')))
	btn_bar.add_widget(Button(text='Cancel', font_size=dp(12), on_release=lambda *_: popup.dismiss()))
	outer.add_widget(btn_bar)

	if has_file:
		btn_bar2 = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
		btn_bar2.add_widget(Button(text='Clear All Local', font_size=dp(11), on_release=_clear_all_local))
		outer.add_widget(btn_bar2)

	on_track_popup(popup)