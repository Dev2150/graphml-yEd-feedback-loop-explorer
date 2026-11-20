import queue
import re
import threading
from typing import Optional

ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')


class ConsoleRedirector:
	encoding = "utf-8"

	def __init__(self, msg_queue: queue.Queue, orig_stream=None):
		self.msg_queue = msg_queue
		self.orig_stream = orig_stream

	def write(self, text: str):
		if text:
			if self.orig_stream is not None:
				try:
					self.orig_stream.write(text)
				except Exception:
					pass
			clean = ANSI_ESCAPE_RE.sub("", text)
			self.msg_queue.put(("text", clean))

	def flush(self):
		if self.orig_stream is not None:
			try:
				self.orig_stream.flush()
			except Exception:
				pass

	def isatty(self) -> bool:
		return False


class GameSession:
	def __init__(self):
		self.input_queue: queue.Queue = queue.Queue()
		self.cancel_event: threading.Event = threading.Event()
		self.thread: Optional[threading.Thread] = None
		self.waiting_for_input: bool = False
