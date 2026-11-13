import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
	sys.path.insert(0, ROOT_DIR)


def main():
	if 'ANDROID_ARGUMENT' in os.environ or '--kivy' in sys.argv:
		from src.android_app import run_android_app
		run_android_app()
	else:
		from src.main import main as desktop_main
		desktop_main()


if __name__ == '__main__':
	main()