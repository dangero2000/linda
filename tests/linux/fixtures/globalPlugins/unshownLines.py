"""A global plugin for test_chromiumWrappedLines.py: with LINDA_UNSHOWN_LINES set, every program's text
has no place on the screen and each of its lines is its whole text, as an Electron program's is before
Electron 45 unless it was started with --force-renderer-accessibility, Discord's among them. Unset, the
plugin does nothing.
"""

import os

import globalPluginHandler
from gi.repository import Atspi

ENVIRONMENT_VARIABLE = "LINDA_UNSHOWN_LINES"


class _AsLibatspi:
	def __init__(self, function) -> None:
		self._function = function

	def __call__(self, *args):
		return self._function(*args)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self) -> None:
		super().__init__()
		self._originals = None
		if not os.environ.get(ENVIRONMENT_VARIABLE):
			return
		extents, string = Atspi.Text.get_character_extents, Atspi.Text.get_string_at_offset
		self._originals = (extents, string)

		def noPlace(*args):
			rect = extents(*args)
			rect.width = rect.height = 0
			return rect

		def wholeLines(*args):
			found = string(*args)
			if args[-1] == Atspi.TextGranularity.LINE:
				found.start_offset, found.end_offset = 0, Atspi.Text.get_character_count(args[0])
				found.content = Atspi.Text.get_text(args[0], 0, -1)
			return found

		# Objects rather than functions, which linuxPlatform.atspi.client.call hands the object asked as
		# it hands libatspi's own functions.
		Atspi.Text.get_character_extents = _AsLibatspi(noPlace)
		Atspi.Text.get_string_at_offset = _AsLibatspi(wholeLines)

	def terminate(self) -> None:
		if self._originals is not None:
			Atspi.Text.get_character_extents, Atspi.Text.get_string_at_offset = self._originals
		super().terminate()
