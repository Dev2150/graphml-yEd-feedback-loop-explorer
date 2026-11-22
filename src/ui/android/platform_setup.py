import os
import sys
import types

from kivy.core.text import LabelBase
from kivy.resources import resource_find
from kivy.utils import platform

IS_DESKTOP = platform not in ('android', 'ios')


def configure_desktop_preview_window():
	"""Configure Galaxy A15 aspect ratio (1080x2340 -> 405x878) before importing Window."""
	if IS_DESKTOP:
		from kivy.config import Config as KivyConfig
		KivyConfig.set('graphics', 'width', '405')
		KivyConfig.set('graphics', 'height', '878')
		KivyConfig.set('graphics', 'resizable', '1')


def ensure_optional_stdlib_stubs():
	"""Must run before `import networkx` to avoid missing _bz2/_lzma on Android."""
	try:
		import bz2  # noqa: F401
	except ImportError:
		bz2_stub = types.ModuleType('bz2')
		bz2_stub.BZ2File = type('BZ2File', (), {})
		bz2_stub.BZ2Compressor = type('BZ2Compressor', (), {})
		bz2_stub.BZ2Decompressor = type('BZ2Decompressor', (), {})
		bz2_stub.open = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('bz2 not available on Android'))
		bz2_stub.compress = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('bz2 not available on Android'))
		bz2_stub.decompress = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('bz2 not available on Android'))
		sys.modules['bz2'] = bz2_stub

	try:
		import lzma  # noqa: F401
	except ImportError:
		lzma_stub = types.ModuleType('lzma')
		lzma_stub.LZMAError = type('LZMAError', (Exception,), {})
		lzma_stub.LZMAFile = type('LZMAFile', (), {})
		lzma_stub.LZMACompressor = type('LZMACompressor', (), {})
		lzma_stub.LZMADecompressor = type('LZMADecompressor', (), {})
		lzma_stub.open = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('lzma not available on Android'))
		lzma_stub.compress = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('lzma not available on Android'))
		lzma_stub.decompress = lambda *a, **kw: (_ for _ in ()).throw(NotImplementedError('lzma not available on Android'))
		sys.modules['lzma'] = lzma_stub


def resolve_console_font() -> str:
	for candidate in ('data/fonts/DejaVuSans.ttf', 'DejaVuSans.ttf'):
		font_path = resource_find(candidate)
		if font_path and os.path.isfile(font_path):
			try:
				LabelBase.register(name='DejaVuSans', fn_regular=font_path)
				return 'DejaVuSans'
			except Exception:
				pass
	return 'Roboto'


configure_desktop_preview_window()
ensure_optional_stdlib_stubs()