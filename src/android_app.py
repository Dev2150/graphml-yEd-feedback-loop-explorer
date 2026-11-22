import os
import sys

# Ensure project root is on sys.path when running src/android_app.py directly
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SRC_DIR)
if ROOT_DIR not in sys.path:
	sys.path.insert(0, ROOT_DIR)

from src.ui.android.app import GraphMLAndroidApp, run_android_app

__all__ = ['GraphMLAndroidApp', 'run_android_app']

if __name__ == '__main__':
	run_android_app()