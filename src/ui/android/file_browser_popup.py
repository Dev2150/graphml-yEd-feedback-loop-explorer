import os
from typing import Callable, Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from src.android_file_picker import (
	get_external_storage_root,
	has_all_files_access,
	list_directory_entries,
	request_storage_permissions,
)
from src.storage import clear_recent_files, get_sync_folder, load_app_state


def open_file_browser_popup(
	graphml_dir: str,
	current_graph_path: str,
	imported_dir: str,
	last_browse_dir: str,
	on_browse_dir_changed: Callable[[str], None],
	on_file_selected: Callable[[str], None],
	on_use_system_picker: Callable[[], None],
	on_show_message: Callable[[str, str], None],
	on_track_popup: Callable[[Popup], None],
	on_set_resume_refresh: Callable[[Optional[Callable[[], None]]], None],
):
	sync_dir = get_sync_folder()
	start_dir = ''
	for candidate in (
		last_browse_dir,
		os.path.dirname(current_graph_path)
		if current_graph_path and os.path.dirname(current_graph_path) != imported_dir
		else '',
		graphml_dir,
		sync_dir,
		get_external_storage_root(),
	):
		if candidate and os.path.isdir(candidate):
			start_dir = os.path.abspath(candidate)
			break
	if not start_dir:
		start_dir = os.getcwd()

	state = {'dir': start_dir}
	content = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))

	lbl_path = Label(
		text=state['dir'],
		size_hint_y=None,
		height=dp(32),
		halign='left',
		valign='middle',
		font_size=dp(11),
		color=(0.78, 0.85, 0.98, 1),
	)
	lbl_path.bind(size=lambda inst, sz: setattr(inst, 'text_size', sz))
	content.add_widget(lbl_path)

	nav_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
	btn_up = Button(text='Up (..)', font_size=dp(12))
	btn_storage = Button(text='Storage', font_size=dp(12))
	nav_row.add_widget(btn_up)
	nav_row.add_widget(btn_storage)
	if graphml_dir and os.path.isdir(graphml_dir):
		btn_gml = Button(text='GraphML Dir', font_size=dp(12))
		btn_gml.bind(on_release=lambda *_: _go_to(graphml_dir))
		nav_row.add_widget(btn_gml)
	if sync_dir and os.path.isdir(sync_dir):
		btn_sync = Button(text='Sync Dir', font_size=dp(12))
		btn_sync.bind(on_release=lambda *_: _go_to(sync_dir))
		nav_row.add_widget(btn_sync)
	content.add_widget(nav_row)

	filter_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
	ti_filter = TextInput(hint_text='Filter files...', multiline=False, font_size=dp(12))
	cb_all = CheckBox(active=False, size_hint_x=None, width=dp(34))
	lbl_all = Label(text='All files', size_hint_x=None, width=dp(58), font_size=dp(12))
	filter_row.add_widget(ti_filter)
	filter_row.add_widget(cb_all)
	filter_row.add_widget(lbl_all)
	content.add_widget(filter_row)

	sv = ScrollView(do_scroll_x=False)
	lst = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4), padding=(0, dp(2)))
	lst.bind(minimum_height=lst.setter('height'))
	sv.add_widget(lst)
	content.add_widget(sv)

	popup = Popup(title='Open GraphML File', content=content, size_hint=(0.95, 0.9))

	def _make_list_btn(label_text: str, bg_color, on_tap):
		btn = Button(
			text=label_text,
			size_hint_y=None,
			height=dp(42),
			font_size=dp(13),
			halign='left',
			valign='middle',
			shorten=True,
			shorten_from='right',
			background_color=bg_color,
			on_release=on_tap,
		)
		btn.bind(size=lambda inst, sz: setattr(inst, 'text_size', (max(0, sz[0] - dp(16)), sz[1])))
		return btn

	def _refresh_list(*_):
		lst.clear_widgets()
		lbl_path.text = state['dir']
		sv.scroll_y = 1

		dirs, files, err = list_directory_entries(state['dir'], show_all_files=cb_all.active)
		if err == 'permission_denied' or (not has_all_files_access() and not dirs and not files):
			msg = Label(
				text=(
					'Storage access is required to browse folders directly.\n'
					'Tap "Grant Storage Access" below, or use "System Picker".'
				),
				size_hint_y=None,
				height=dp(72),
				halign='center',
				valign='middle',
				font_size=dp(12),
			)
			msg.bind(size=lambda inst, sz: setattr(inst, 'text_size', sz))
			lst.add_widget(msg)
			lst.add_widget(Button(
				text='Grant Storage Access',
				size_hint_y=None,
				height=dp(44),
				background_color=(0.2, 0.5, 0.78, 1),
				on_release=lambda *_: request_storage_permissions(lambda _ok: _refresh_list()),
			))
			return

		if err:
			lst.add_widget(Label(text=err, size_hint_y=None, height=dp(44), font_size=dp(12)))
			return

		q = ti_filter.text.strip().lower()
		shown = 0
		for d in dirs:
			if q and q not in d.lower():
				continue
			full_d = os.path.join(state['dir'], d)
			lst.add_widget(_make_list_btn(f'[DIR] {d}', (0.24, 0.30, 0.38, 1), lambda _b, p=full_d: _go_to(p)))
			shown += 1

		for fname in files:
			if q and q not in fname.lower():
				continue
			full_f = os.path.join(state['dir'], fname)
			is_gml = fname.lower().endswith('.graphml')
			bg = (0.18, 0.45, 0.30, 1) if is_gml else (0.24, 0.24, 0.26, 1)

			def _on_file(_b, path=full_f, ok=is_gml):
				if not ok:
					on_show_message('Unsupported File', 'Please select a .graphml file.')
					return
				on_browse_dir_changed(state['dir'])
				popup.dismiss()
				on_file_selected(path)

			lst.add_widget(_make_list_btn(fname, bg, _on_file))
			shown += 1

		if shown == 0:
			hint = 'No matching files in this folder.'
			if not cb_all.active:
				hint += '\nCheck "All files" to view non-GraphML files.'
			empty_lbl = Label(text=hint, size_hint_y=None, height=dp(56), halign='center', font_size=dp(12))
			empty_lbl.bind(size=lambda inst, sz: setattr(inst, 'text_size', sz))
			lst.add_widget(empty_lbl)

	def _go_to(path: str):
		if path and os.path.isdir(path):
			state['dir'] = os.path.abspath(path)
			on_browse_dir_changed(state['dir'])
			_refresh_list()

	btn_up.bind(on_release=lambda *_: _go_to(os.path.dirname(state['dir'])))
	btn_storage.bind(on_release=lambda *_: _go_to(get_external_storage_root()))
	ti_filter.bind(text=_refresh_list)
	cb_all.bind(active=_refresh_list)

	bottom_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
	bottom_row.add_widget(Button(
		text='System Picker',
		font_size=dp(12),
		on_release=lambda *_: (popup.dismiss(), on_use_system_picker()),
	))
	bottom_row.add_widget(Button(text='Refresh', font_size=dp(12), on_release=_refresh_list))
	bottom_row.add_widget(Button(text='Cancel', font_size=dp(12), on_release=lambda *_: popup.dismiss()))
	content.add_widget(bottom_row)

	on_set_resume_refresh(_refresh_list)
	popup.bind(on_dismiss=lambda *_: on_set_resume_refresh(None))
	_refresh_list()
	on_track_popup(popup)


def open_folder_picker_popup(
	title: str,
	initial_dir: str,
	on_selected: Callable[[str], None],
	on_track_popup: Callable[[Popup], None],
	on_set_resume_refresh: Callable[[Optional[Callable[[], None]]], None],
):
	start_dir = (
		initial_dir.strip()
		if initial_dir and os.path.isdir(initial_dir.strip())
		else get_external_storage_root()
	)
	if not os.path.isdir(start_dir):
		start_dir = os.getcwd()
	state = {'dir': os.path.abspath(start_dir)}

	content = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))
	lbl_path = Label(
		text=state['dir'],
		size_hint_y=None,
		height=dp(32),
		halign='left',
		valign='middle',
		font_size=dp(11),
	)
	lbl_path.bind(size=lambda inst, sz: setattr(inst, 'text_size', sz))
	content.add_widget(lbl_path)

	nav_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
	btn_up = Button(text='Up (..)', font_size=dp(12))
	btn_storage = Button(text='Storage', font_size=dp(12))
	nav_row.add_widget(btn_up)
	nav_row.add_widget(btn_storage)
	content.add_widget(nav_row)

	sv = ScrollView(do_scroll_x=False)
	lst = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4))
	lst.bind(minimum_height=lst.setter('height'))
	sv.add_widget(lst)
	content.add_widget(sv)

	popup = Popup(title=title, content=content, size_hint=(0.94, 0.85))

	def _refresh(*_):
		lst.clear_widgets()
		lbl_path.text = state['dir']
		dirs, _files, err = list_directory_entries(state['dir'], show_all_files=False)
		if err == 'permission_denied' or (not has_all_files_access() and not dirs):
			lst.add_widget(Button(
				text='Grant Storage Access',
				size_hint_y=None,
				height=dp(44),
				on_release=lambda *_: request_storage_permissions(lambda _ok: _refresh()),
			))
			return
		for d in dirs:
			full_d = os.path.join(state['dir'], d)
			btn = Button(
				text=f'[DIR] {d}',
				size_hint_y=None,
				height=dp(40),
				halign='left',
				valign='middle',
				font_size=dp(12),
			)
			btn.bind(size=lambda inst, sz: setattr(inst, 'text_size', (max(0, sz[0] - dp(12)), sz[1])))
			btn.bind(on_release=lambda _b, p=full_d: _go(p))
			lst.add_widget(btn)

	def _go(p: str):
		if p and os.path.isdir(p):
			state['dir'] = os.path.abspath(p)
			_refresh()

	btn_up.bind(on_release=lambda *_: _go(os.path.dirname(state['dir'])))
	btn_storage.bind(on_release=lambda *_: _go(get_external_storage_root()))

	bottom = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
	bottom.add_widget(Button(
		text='Select This Folder',
		background_color=(0.18, 0.52, 0.32, 1),
		on_release=lambda *_: (popup.dismiss(), on_selected(state['dir'])),
	))
	bottom.add_widget(Button(text='Cancel', on_release=lambda *_: popup.dismiss()))
	content.add_widget(bottom)

	on_set_resume_refresh(_refresh)
	popup.bind(on_dismiss=lambda *_: on_set_resume_refresh(None))
	_refresh()
	on_track_popup(popup)


def open_recent_files_popup(
	on_file_selected: Callable[[str], None],
	on_track_popup: Callable[[Popup], None],
):
	state = load_app_state()
	recent = [p for p in state.get('recent_files', []) if os.path.isfile(p)]

	content = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
	scroll = ScrollView()
	lst = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(6))
	lst.bind(minimum_height=lst.setter('height'))

	popup = Popup(title='Recent GraphML Files', content=content, size_hint=(0.92, 0.78))

	if not recent:
		lst.add_widget(Label(text='No recent files found.', size_hint_y=None, height=dp(40)))
	else:
		for p in recent[:50]:
			btn = Button(
				text=os.path.basename(p),
				size_hint_y=None,
				height=dp(44),
				on_release=lambda _b, path=p: (popup.dismiss(), on_file_selected(path)),
			)
			lst.add_widget(btn)

	scroll.add_widget(lst)
	content.add_widget(scroll)

	btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
	btn_row.add_widget(Button(
		text='Clear Recent',
		on_release=lambda *_: (clear_recent_files(), popup.dismiss()),
	))
	btn_row.add_widget(Button(text='Close', on_release=lambda *_: popup.dismiss()))
	content.add_widget(btn_row)
	on_track_popup(popup)
