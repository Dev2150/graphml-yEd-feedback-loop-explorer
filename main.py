import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
	sys.path.insert(0, APP_DIR)


def check_is_android() -> bool:
	if '--kivy' in sys.argv:
		return True
	if '--cli' in sys.argv:
		return False
	if any(k in os.environ for k in ('ANDROID_ARGUMENT', 'PYTHON_SERVICE_ARGUMENT', 'ANDROID_ENTRYPOINT')):
		return True
	try:
		from kivy.utils import platform
		return platform in ('android', 'ios')
	except ImportError:
		return False


def _show_fatal_error_app(tb_text: str):
	from kivy.app import App
	from kivy.metrics import dp
	from kivy.uix.boxlayout import BoxLayout
	from kivy.uix.label import Label
	from kivy.uix.scrollview import ScrollView

	class CrashScreenApp(App):
		def build(self):
			root = BoxLayout(orientation='vertical', padding=dp(12), spacing=dp(8))
			root.add_widget(Label(
				text='Startup Error:',
				size_hint_y=None,
				height=dp(32),
				bold=True,
				color=(1, 0.4, 0.4, 1),
			))
			sv = ScrollView()
			lbl = Label(
				text=tb_text,
				size_hint_y=None,
				halign='left',
				valign='top',
				font_size=dp(12),
			)
			lbl.bind(width=lambda inst, w: setattr(inst, 'text_size', (w, None)))
			lbl.bind(texture_size=lambda inst, ts: setattr(inst, 'height', ts[1] + dp(10)))
			sv.add_widget(lbl)
			root.add_widget(sv)
			return root

	CrashScreenApp().run()


def main():
	if check_is_android():
		try:
			from src.ui.android.app import run_android_app
			run_android_app()
		except Exception:
			import traceback
			_show_fatal_error_app(traceback.format_exc())
	else:
		from src.main import main as desktop_main
		desktop_main()


if __name__ == '__main__':
	main()