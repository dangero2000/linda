"""App module for Chromium on Linux, and the base of those for programs built on it, Electron's among
them. On Windows these programs are served by NVDA's IAccessible2 support, and the module gives them
the default app module, as before.

Chromium joins the accessibility bus only when the desktop's accessibility status was on as it
started; then it shows its windows, but builds the accessible tree of a web page only once a client
asks for something that, by Chromium's reckoning, only a screen reader asks for: an object's
attributes or its relations. Asking for the attributes of each window that comes to the foreground
makes sure that happens whatever else NVDA happens to ask first.

A web page's landmarks are named for their kind, "main landmark" rather than "landmark", from the
ARIA roles Chromium gives with them, as NVDA does for Chromium's IAccessible2 objects on Windows.

A rich text editor, an editable element such as the one chat programs write messages in, keeps its
text in the paragraphs inside it, and its own text has an embedded object character for each of
them. Read as it is, the editor says that character and nothing of what was typed, and its caret is
nowhere. Its text is therefore read as one, its paragraphs' text with a line break between them, as
NVDA reads such an editor on Windows. Its caret, selection and text change in the paragraph, which
alone reports them, and the editor takes those reports as its own. Its lines are those the screen
shows, a paragraph wider than the editor on several, which the paragraph tells.
"""

import sys

import appModuleHandler

if sys.platform == "linux":
	import api
	import aria
	import controlTypes
	import textInfos
	from gi.repository import Atspi
	from linuxPlatform.atspi import handler
	from linuxPlatform.atspi.client import Node, NodeGone, call
	from locationHelper import RectLTWH
	from logHandler import log
	from NVDAObjects.AtSpi import AtSpi
	from textInfos.offsets import OffsetsTextInfo, findEndOfLine, findStartOfLine

	#: What stands in an object's text for each child that is not text.
	EMBEDDED_OBJECT = "￼"
	#: How deep paragraphs, spans and links nest inside an editor before the rest is left out.
	MAX_DEPTH = 12
	#: How far inside an editor the paragraph and the run of text that report its caret are.
	INSIDE_DEPTH = 4
	#: How many characters of an editor are read; a message is far shorter.
	MAX_CHARACTERS = 100000

	class Run:
		"""Characters flatStart to flatEnd of an editor's text, standing for nodeLength of node's own
		characters from nodeStart on: as many as they are for its text, one for the name of a picture in
		it, and none for a line break put between paragraphs."""

		__slots__ = ("flatEnd", "flatStart", "node", "nodeLength", "nodeStart")

		def __init__(self, flatStart: int, flatEnd: int, node: Node, nodeStart: int, nodeLength: int):
			self.flatStart = flatStart
			self.flatEnd = flatEnd
			self.node = node
			self.nodeStart = nodeStart
			self.nodeLength = nodeLength

		def nodeOffset(self, flatOffset: int) -> int:
			if self.nodeLength == self.flatEnd - self.flatStart:
				return self.nodeStart + flatOffset - self.flatStart
			return self.nodeStart + (self.nodeLength if flatOffset >= self.flatEnd else 0)

	def _embeddedChild(node: Node, offset: int, children: list[Node], index: int) -> Node | None:
		"""The child the embedded object character at offset in node's text stands for, by its
		hyperlink, or else as the index-th child that is not a run of text."""
		client = handler.client()
		try:
			link = call(node, Atspi.Hypertext.get_link_index, offset)
			if link >= 0:
				hyperlink = call(node, Atspi.Hypertext.get_link, link)
				if hyperlink is not None:
					child = client.node(call(node, lambda: hyperlink.get_object(0)))
					if child is not None:
						return child
		except NodeGone:
			pass
		try:
			others = [c for c in children if not (client.role(c) == "static" and client.childCount(c) == 0)]
		except NodeGone:
			return None
		return others[index] if index < len(others) else None

	def _isBlock(node: Node) -> bool:
		try:
			display = handler.client().attributes(node).get("display", "block")
		except NodeGone:
			return False
		return not display.startswith("inline")

	class EditorText:
		"""An editor's text read as one, and where each of its characters comes from."""

		def __init__(self, root: Node) -> None:
			self.root = root
			self.runs: list[Run] = []
			self.depths: dict[Node, int] = {}
			self._parts: list[str] = []
			self.length = 0
			#: The line break owed after a paragraph, given once something follows it, as (its node, its length).
			self._break: tuple[Node, int] | None = None
			#: Each object inside the editor, as the object whose text holds its embedded object character and
			#: that character's offset there; and where in the whole text its own text starts.
			self.parents: dict[Node, tuple[Node, int]] = {}
			self.childStarts: dict[tuple[Node, int], int] = {}
			#: The objects that are paragraphs, which say where the screen breaks their lines: the editor
			#: itself, and each block inside it.
			self.blocks: set[Node] = {root}
			self._add(root, 0)
			self.text = "".join(self._parts)

		def _append(self, text: str, node: Node, nodeStart: int, nodeLength: int | None = None) -> None:
			if not text:
				return
			if nodeLength is None:
				nodeLength = len(text)
			if self._break is not None and nodeLength:
				breakNode, end = self._break
				self._break = None
				if not self._parts[-1].endswith("\n"):
					self._append("\n", breakNode, end, 0)
			self.runs.append(Run(self.length, self.length + len(text), node, nodeStart, nodeLength))
			self._parts.append(text)
			self.length += len(text)

		def _add(self, node: Node, depth: int) -> None:
			client = handler.client()
			self.depths[node] = depth
			try:
				text = client.text(node)
			except NodeGone:
				return
			if EMBEDDED_OBJECT not in text or depth >= MAX_DEPTH:
				self._append(text, node, 0)
				return
			try:
				children = client.children(node)
			except NodeGone:
				children = []
			runStart = 0
			index = 0
			for offset, character in enumerate(text):
				if self.length >= MAX_CHARACTERS:
					break
				if character != EMBEDDED_OBJECT:
					continue
				self._append(text[runStart:offset], node, runStart)
				runStart = offset + 1
				child = _embeddedChild(node, offset, children, index)
				index += 1
				try:
					hasText = child is not None and "Text" in client.interfaces(child)
				except NodeGone:
					hasText = False
				if not hasText:
					# A picture, as a chat program shows an emoji, said by its name.
					try:
						name = client.name(child) if child is not None else ""
					except NodeGone:
						name = ""
					self._append(name or EMBEDDED_OBJECT, node, offset, 1)
					continue
				block = _isBlock(child)
				if block and self._break is None and self._parts and not self._parts[-1].endswith("\n"):
					self._append("\n", node, offset, 0)
				self.parents[child] = (node, offset)
				if block:
					self.blocks.add(child)
				before = self.length
				self.childStarts[(node, offset)] = before
				self._add(child, depth + 1)
				if block and self.length > before:
					try:
						self._break = (child, client.characterCount(child))
					except NodeGone:
						self._break = (child, 0)
			self._append(text[runStart:], node, runStart)

		def runAt(self, offset: int) -> Run | None:
			return next((run for run in self.runs if run.flatStart <= offset < run.flatEnd), None)

		def locate(self, offset: int) -> tuple[Node, int]:
			"""The object and its own offset for the character at offset, or for the end."""
			run = self.runAt(offset)
			if run is not None:
				return run.node, run.nodeOffset(offset)
			if self.runs:
				last = self.runs[-1]
				return last.node, last.nodeOffset(last.flatEnd)
			return self.root, 0

		def offsetOf(self, node: Node, nodeOffset: int) -> int | None:
			"""The offset in the whole text of node's own nodeOffset."""
			ending = None
			for run in self.runs:
				if run.node != node or not run.nodeLength:
					continue
				if run.nodeStart <= nodeOffset < run.nodeStart + run.nodeLength:
					if run.nodeLength == run.flatEnd - run.flatStart:
						return run.flatStart + nodeOffset - run.nodeStart
					return run.flatStart
				if nodeOffset == run.nodeStart + run.nodeLength:
					ending = run.flatEnd
			if ending is not None:
				return ending
			return None

		def _flatOffset(self, node: Node, nodeOffset: int) -> int | None:
			"""The offset in the whole text of node's own nodeOffset, an embedded object character's among
			them: where the text of the object it stands for starts."""
			start = self.childStarts.get((node, nodeOffset))
			return start if start is not None else self.offsetOf(node, nodeOffset)

		def shownLine(self, offset: int) -> tuple[int, int] | None:
			"""The line of the screen the character at offset is on, as (start, end) in the whole text,
			from the paragraph holding it; None when it cannot say. The text of a bold word or a link is
			an object of its own, inside the paragraph, which knows only its own part of the line."""
			run = self.runAt(offset)
			if run is None or not run.nodeLength:
				return None
			node, nodeOffset = run.node, run.nodeOffset(offset)
			while node not in self.blocks:
				parent = self.parents.get(node)
				if parent is None:
					return None
				node, nodeOffset = parent
			try:
				line = call(node, Atspi.Text.get_string_at_offset, nodeOffset, Atspi.TextGranularity.LINE)
			except NodeGone:
				return None
			if not line.start_offset <= nodeOffset < line.end_offset:
				return None
			start = self._flatOffset(node, line.start_offset)
			end = self._flatOffset(node, line.end_offset)
			if start is None or end is None or not start <= offset < end:
				return None
			return (start, end)

		def caret(self) -> int:
			"""Where the caret is in the whole text; the deepest object holding it says."""
			client = handler.client()
			holders = sorted(self.depths, key=self.depths.__getitem__, reverse=True)
			for node in holders:
				try:
					offset = client.caretOffset(node)
				except NodeGone:
					continue
				if offset < 0:
					continue
				found = self.offsetOf(node, offset)
				if found is not None:
					return found
			raise RuntimeError("no caret in this editor")

		def selection(self) -> tuple[int, int] | None:
			"""The selected part of the whole text, from the start of the first paragraph's selection to
			the end of the last's, or None when nothing is selected."""
			client = handler.client()
			found: list[int] = []
			for node, depth in self.depths.items():
				if depth == 0 and len(self.depths) > 1:
					# Its own selection covers whole paragraphs, as embedded object characters.
					continue
				try:
					selections = client.selections(node)
				except NodeGone:
					continue
				for start, end in selections:
					if start == end:
						continue
					for offset in (start, end):
						mapped = self.offsetOf(node, offset)
						if mapped is not None:
							found.append(mapped)
			if not found:
				return None
			return (min(found), max(found))

	class EditorTextInfo(OffsetsTextInfo):
		"""The text of a rich text editor, its paragraphs' text read as one. The whole text is read
		again for each TextInfo, which an editor of a message or two allows."""

		detectFormattingAfterCursorMaybeSlow = False
		encoding = None

		def _get_editorText(self) -> EditorText:
			editorText = self.__dict__.get("editorTextCache")
			if editorText is None:
				editorText = self.editorTextCache = EditorText(self.obj.node)
			return editorText

		def _getStoryText(self) -> str:
			return self.editorText.text

		def _getStoryLength(self) -> int:
			return self.editorText.length

		def _getTextRange(self, start: int, end: int) -> str:
			return self.editorText.text[start:end]

		def _getCaretOffset(self) -> int:
			return self.editorText.caret()

		def _setCaretOffset(self, offset: int) -> None:
			node, nodeOffset = self.editorText.locate(offset)
			try:
				handler.client().setCaretOffset(node, nodeOffset)
			except NodeGone:
				pass

		def _getSelectionOffsets(self) -> tuple[int, int]:
			selection = self.editorText.selection()
			if selection is not None:
				return selection
			caret = self._getCaretOffset()
			return (caret, caret)

		def _setSelectionOffsets(self, start: int, end: int) -> None:
			self._setCaretOffset(start)

		def _getCharacterOffsets(self, offset: int) -> tuple[int, int]:
			run = self.editorText.runAt(offset)
			if run is not None and run.nodeLength == 1 and run.flatEnd - run.flatStart > 1:
				# A picture's name is one character of the editor's.
				return (run.flatStart, run.flatEnd)
			return super()._getCharacterOffsets(offset)

		def _getLineOffsets(self, offset: int) -> tuple[int, int]:
			"""The line of the screen offset is on, as NVDA reads a line on Windows: a paragraph longer than
			the editor is wide is broken onto several, which Chromium tells. A paragraph's line break goes
			with its last line, and the caret at the end of the paragraph is on that line."""
			start, end = self._getParagraphOffsets(offset)
			text = self.editorText.text
			atEnd = offset >= len(text) or text[offset] == "\n"
			shown = self.editorText.shownLine(offset - 1 if atEnd and offset > start else offset)
			if shown is None:
				return (start, end)
			shownStart, shownEnd = max(start, shown[0]), min(end, shown[1])
			if text[shownEnd:end] in ("", "\n"):
				shownEnd = end
			if not (shownStart <= offset < shownEnd or offset == shownEnd == end):
				return (start, end)
			return (shownStart, shownEnd)

		def _getParagraphOffsets(self, offset: int) -> tuple[int, int]:
			text = self.editorText.text
			return (findStartOfLine(text, offset), findEndOfLine(text, offset))

		def _getBoundingRectFromOffset(self, offset: int) -> RectLTWH:
			node, nodeOffset = self.editorText.locate(offset)
			try:
				extents = call(
					node,
					Atspi.Text.get_character_extents,
					nodeOffset,
					Atspi.CoordType.SCREEN,
				)
			except NodeGone as e:
				raise LookupError(str(e)) from None
			if extents.width <= 0 and extents.height <= 0:
				raise LookupError(f"no extents at offset {offset}")
			return RectLTWH(extents.x, extents.y, extents.width, extents.height)

		def _getFormatFieldAndOffsets(self, offset, formatConfig, calculateOffsets=True):
			return (textInfos.FormatField(), self._getLineOffsets(offset))

	class RichTextEditor(AtSpi):
		def _get_TextInfo(self):
			return EditorTextInfo

	#: Characters with no width of their own, which a program may give no place on the screen whatever
	#: it tells: an empty paragraph's in Discord's editor among them.
	NO_WIDTH = frozenset("\ufeff\u200b\u2060" + EMBEDDED_OBJECT)
	#: The programs, by process, looked at for whether they tell where their lines wrap.
	_linesLookedAt: set[int] = set()
	#: Milliseconds from the focus coming to a message box to looking at its program, when the focus has
	#: moved no further: as a window comes to the front or a page loads, the focus moves several times.
	UNSHOWN_LINES_DELAY_MS = 300
	#: Objects with text looked at, at most, for one with something to see.
	SHOWN_TEXT_LIMIT = 20
	#: How far up from the focus the document holding it is looked for.
	DOCUMENT_DEPTH = 40
	_pendingLook = None

	def _lookForUnshownLinesSoon(obj) -> None:
		"""Look at obj's program once the focus has stayed on obj a moment, unless it was looked at."""
		global _pendingLook
		import core

		if obj.processID in _linesLookedAt:
			return
		if _pendingLook is not None:
			_pendingLook.Stop()
		_pendingLook = core.callLater(UNSHOWN_LINES_DELAY_MS, _tellOfUnshownLines, obj)

	def _firstSeen(text: str) -> int | None:
		"""The offset of text's first character with something to see, or None."""
		return next((i for i, c in enumerate(text) if not c.isspace() and c not in NO_WIDTH), None)

	def _documentHolding(node: Node) -> Node | None:
		client = handler.client()
		for _level in range(DOCUMENT_DEPTH):
			try:
				if call(node, Atspi.Accessible.get_role) == Atspi.Role.DOCUMENT_WEB:
					return node
				node = client.parent(node)
			except NodeGone:
				return None
			if node is None:
				return None
		return None

	def _shownCharacter(obj) -> tuple[Node, int] | None:
		"""A character the screen shows in or near obj, a message box, as the object holding it and its
		offset there: the box's own first; else, with nothing typed in it, the first in the document
		holding it, as even Electron 37 gives an empty paragraph's zero-width space a place. None when obj
		is not a message box or nothing shown has more than spaces."""
		if not isinstance(obj, RichTextEditor):
			# Asked where text other than the focus's is, Chromium loses the next key's caret movement
			# now and then: a page that is loading has the focus on the document a moment, and a key
			# soon after would go unread. A message box is where lines matter.
			return None
		text = EditorText(obj.node)
		offset = _firstSeen(text.text)
		if offset is not None:
			return text.locate(offset)
		document = _documentHolding(obj.node)
		if document is None:
			return None
		client = handler.client()
		rule = Atspi.MatchRule.new(
			Atspi.StateSet.new([Atspi.StateType.SHOWING]),
			Atspi.CollectionMatchType.ALL,
			None,
			Atspi.CollectionMatchType.NONE,
			None,
			Atspi.CollectionMatchType.NONE,
			["Text"],
			Atspi.CollectionMatchType.ALL,
			False,
		)
		try:
			matches = call(
				document,
				Atspi.Collection.get_matches,
				rule,
				Atspi.CollectionSortOrder.CANONICAL,
				SHOWN_TEXT_LIMIT,
				True,
			)
		except NodeGone:
			return None
		for match in matches or ():
			node = client.node(match)
			if node is None:
				continue
			try:
				offset = _firstSeen(client.text(node))
			except NodeGone:
				continue
			if offset is not None:
				return (node, offset)
		return None

	def _tellOfUnshownLines(obj) -> None:
		"""Say, once while a program runs, that it does not tell where its lines wrap, as an Electron
		program such as Discord does not before Electron 45 unless it was started with
		--force-renderer-accessibility: Up and Down in its message box then read a paragraph whole, from
		its start to the next line break typed. Such a program gives no place on the screen to any of its
		text. Said as soon as the focus settles in its message box, as its window comes to the front too,
		interrupting what is being said of it."""
		global _pendingLook
		_pendingLook = None
		if api.getFocusObject() != obj or obj.processID in _linesLookedAt:
			return
		shown = _shownCharacter(obj)
		if shown is None:
			# Nothing to look at yet; the next time the focus comes to a message box, there may be.
			return
		_linesLookedAt.add(obj.processID)
		node, offset = shown
		try:
			extents = call(node, Atspi.Text.get_character_extents, offset, Atspi.CoordType.SCREEN)
		except NodeGone:
			return
		if extents.width > 0 or extents.height > 0:
			return
		import ui

		# The name the program gives the bus, as Discord, else its executable's.
		program = handler._applicationName(obj.node.busName) or obj.appModule.appName
		log.info(f"Chromium: {program} gives its text no place on the screen")
		ui.message(
			# Translators: Said once when the focus first comes to the message box of a program built on
			# Electron, such as Discord, which tells a screen reader where its lines wrap only when started
			# with the option named.
			_(
				"{program} does not tell where its lines wrap, so Up and Down arrow read whole paragraphs. "
				"Start it with the option --force-renderer-accessibility to read each line.",
			).format(program=program),
		)

	def _editorHolding(obj) -> RichTextEditor | None:
		"""The focus, when it is a rich text editor and obj is inside it."""
		focus = api.getFocusObject()
		if not isinstance(focus, RichTextEditor) or not isinstance(obj, AtSpi) or obj is focus:
			return None
		node = obj.node
		if node.busName != focus.node.busName:
			return None
		try:
			for _ in range(INSIDE_DEPTH):
				node = handler.client().parent(node)
				if node is None:
					return None
				if node == focus.node:
					return focus
		except NodeGone:
			pass
		return None

	class WebLandmark(AtSpi):
		def _get_landmark(self) -> str | None:
			xmlRoles = self.atspiAttributes.get("xml-roles", "").split(" ")
			return next((role for role in xmlRoles if role in aria.landmarkRoles), None)

	class AppModule(appModuleHandler.AppModule):
		def chooseNVDAObjectOverlayClasses(self, obj, clsList):
			if not isinstance(obj, AtSpi):
				return
			if obj.role == controlTypes.Role.LANDMARK:
				clsList.insert(0, WebLandmark)
			elif (
				# One with no role, as YouTube's comment box is, is a section, and one made a combo box, as
				# Discord's search box is, keeps its text in a paragraph as well: as on Windows, every
				# editable element that takes the focus is an editor, whatever its role.
				(
					obj.role == controlTypes.Role.EDITABLETEXT
					or ("focusable" in obj.atspiStates and obj.role != controlTypes.Role.DOCUMENT)
				)
				and controlTypes.State.MULTILINE in obj.states
				and "editable" in obj.atspiStates
				and "Text" in obj.atspiInterfaces
			):
				clsList.insert(0, RichTextEditor)

		# A rich text editor's caret, selection and text change in the paragraph that holds them, which
		# alone reports them; the editor, which has the focus, takes them as its own, so that it says
		# what a key selected.
		def event_caret(self, obj, nextHandler):
			editor = _editorHolding(obj)
			if editor is None:
				nextHandler()
			else:
				editor.event_caret()

		def event_textChange(self, obj, nextHandler):
			editor = _editorHolding(obj)
			if editor is None:
				nextHandler()
			else:
				editor.event_textChange()

		def event_textInsert(self, obj, nextHandler):
			editor = _editorHolding(obj)
			if editor is None:
				nextHandler()
			else:
				editor.event_textInsert()

		def event_textRemove(self, obj, nextHandler):
			editor = _editorHolding(obj)
			if editor is None:
				nextHandler()
			else:
				editor.event_textRemove()

		def event_gainFocus(self, obj, nextHandler):
			nextHandler()
			if isinstance(obj, AtSpi):
				_lookForUnshownLinesSoon(obj)

		def event_foreground(self, obj, nextHandler):
			if isinstance(obj, AtSpi):
				try:
					handler.client().attributes(obj.node)
				except NodeGone:
					pass
			nextHandler()

else:
	AppModule = appModuleHandler.AppModule
