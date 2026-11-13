import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
	sys.path.insert(0, ROOT_DIR)


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


def main():
	if check_is_android():
		from src.android_app import run_android_app
		run_android_app()
	else:
		from src.main import main as desktop_main
		desktop_main()


if __name__ == '__main__':
	main()