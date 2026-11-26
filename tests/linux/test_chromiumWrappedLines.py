"""The lines of a message box in Chromium and in an Electron program, built as Discord's is, whose
paragraphs are longer than the box is wide: Up and Down move by the lines the screen shows, and each
reads the line it comes to, as NVDA reads them on Windows, rather than the whole paragraph from its start
to the next line break typed.

Electron 37, Discord's in 2026, tells where a line wraps only when started with
--force-renderer-accessibility; the rig's Electron, as Chromium, tells it without. A program that does
not tell it, as fixtures/globalPlugins/unshownLines.py makes Chromium, is said to need the option, once,
as soon as the focus settles in it: with nothing typed in its message box too, by the text of the page
around it.

LINDA_RIG_WM=marco nix develop . -c tests/linux/rig python3 -m pytest -q tests/linux/test_chromiumWrappedLines.py
"""

import time
from collections.abc import Iterator

import chromiumSession
import pytest
import webSession
from desktopSession import DesktopSession
from test_browseUsable import EXIT_BOUND, SETTLE, STARTUP_BOUND, TIMED_SPEECH, Session, step, typeEchoed

PAGE = "wrappedComposer.html"
#: A page as Discord's channel is with nothing typed: a message above an empty message box.
EMPTY_PAGE = "emptyComposer.html"
#: What the box says as the page focuses it, before its first paragraph.
BOX = "Message  number general edit multi line"
#: The lines the box shows its three paragraphs on, 30 characters wide: the second paragraph's
#: "epsilon zeta" is bold, an object of its own inside the paragraph.
LINES = (
	"one two three four five six",
	"seven eight nine ten eleven",
	"twelve thirteen fourteen",
	"fifteen",
	"alpha beta gamma delta",
	"epsilon zeta eta theta iota",
	"kappa lambda mu",
	"Last line",
)


#: What a program that does not tell where its lines wrap is said to need, once.
NOTICE = (
	"Chromium does not tell where its lines wrap, so Up and Down arrow read whole paragraphs. "
	"Start it with the option --force-renderer-accessibility to read each line."
)
#: The first paragraph whole, as such a program has it.
PARAGRAPHS = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen",)
#: The title of the window both programs show the page in.
TITLE = "Wrapped composer fixture"
#: The title of the window both programs show the empty page in.
EMPTY_TITLE = "Empty composer fixture"


@pytest.fixture(scope="module", params=["chromium", "electron"])
def session(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Session]:
	webSession.requireBrowseLibraries()
	directory = tmp_path_factory.mktemp("wrappedLines")
	with DesktopSession(directory / "desktop") as desktop:
		chromiumSession.clearAccessibilityStatus()
		nvda = desktop.startNVDA(webSession.BROWSE_CONFIG, env=TIMED_SPEECH)
		nvda.waitForLog("NVDA initialized", STARTUP_BOUND)
		if request.param == "chromium":
			program = chromiumSession.startChromium(desktop, PAGE)
		else:
			# The chat program of the fixtures, on the same page, a link in its directory.
			program = chromiumSession.startElectron(desktop, "electronChat", PAGE, window=TITLE)
		yield Session(desktop, nvda, program, directory)


def test_theBoxIsInFocusModeAsThePageOpens(session: Session):
	session.desktop.expect(f"{BOX}\N{HORIZONTAL ELLIPSIS}", "Focus mode", since=0, timeout=STARTUP_BOUND)
	# Past the moment Linda waits before telling of a program that does not say where its lines wrap.
	time.sleep(1 + SETTLE)
	assert not [text for text in session.desktop.spokenSince(0) if "force-renderer" in text]


def test_upAndDownReadTheLinesTheScreenShows(session: Session):
	step(session, "ctrl+Home", LINES[0])
	for line in LINES[1:]:
		step(session, "Down", line)
	for line in reversed(LINES[:-1]):
		step(session, "Up", line)


def test_readingTheCurrentLine(session: Session):
	step(session, "Down", LINES[1])
	step(session, "Insert+Up", LINES[1])
	step(session, "ctrl+End", LINES[-1])
	step(session, "Up", LINES[-2])
	step(session, "Insert+Up", LINES[-2])


def test_exitIsClean(session: Session):
	step(session, "Insert+q", "Exit Linda\N{HORIZONTAL ELLIPSIS}")
	session.desktop.press("Return")
	session.nvda.waitForExit(EXIT_BOUND)
	assert session.nvda.process.returncode == 0, session.nvda.describe()
	session.nvda.assertClean(logNames=("nvda.log",))


@pytest.mark.parametrize("page", [PAGE, EMPTY_PAGE])
def test_aProgramThatDoesNotTellWhereLinesWrapIsSaidToNeedTheOption(
	page: str,
	tmp_path_factory: pytest.TempPathFactory,
):
	webSession.requireBrowseLibraries()
	directory = tmp_path_factory.mktemp("unshownLines")
	with DesktopSession(directory / "desktop") as desktop:
		chromiumSession.clearAccessibilityStatus()
		nvda = desktop.startNVDA(webSession.BROWSE_CONFIG, env={**TIMED_SPEECH, "LINDA_UNSHOWN_LINES": "1"})
		nvda.waitForLog("NVDA initialized", STARTUP_BOUND)
		program = chromiumSession.startChromium(desktop, page)
		session = Session(desktop, nvda, program, directory)
		# Said as the focus settles in the program, before any key: with nothing typed in the box too.
		desktop.expect(f"{BOX}\N{HORIZONTAL ELLIPSIS}", NOTICE, since=0, timeout=STARTUP_BOUND)
		if page == PAGE:
			# Up and Down read each paragraph whole, as before, there being nothing to tell its lines by:
			# Down to the paragraph's second line reads it all again.
			step(session, "ctrl+Home", PARAGRAPHS[0])
			step(session, "Down", PARAGRAPHS[0])
		# Once while the program runs: not again as the box takes the focus again.
		mark = step(session, "Escape", "Browse mode")
		step(session, "Return", "Focus mode")
		time.sleep(1 + SETTLE)
		assert desktop.spokenSince(0).count(NOTICE) == 1, desktop.spokenSince(mark)
		step(session, "Insert+q", "Exit Linda\N{HORIZONTAL ELLIPSIS}")
		desktop.press("Return")
		nvda.waitForExit(EXIT_BOUND)
		assert nvda.process.returncode == 0, nvda.describe()
		nvda.assertClean(logNames=("nvda.log",))


@pytest.mark.parametrize("kind", ["chromium", "electron"])
def test_anEmptyBoxIsTypedInAsBeforeWhereLinesAreTold(kind: str, tmp_path_factory: pytest.TempPathFactory):
	"""Looking at the page around an empty box, which the rig's Chromium and Electron tell the place of,
	says nothing and leaves the keys that follow as they were."""
	webSession.requireBrowseLibraries()
	directory = tmp_path_factory.mktemp("emptyBox")
	with DesktopSession(directory / "desktop") as desktop:
		chromiumSession.clearAccessibilityStatus()
		nvda = desktop.startNVDA(webSession.BROWSE_CONFIG, env=TIMED_SPEECH)
		nvda.waitForLog("NVDA initialized", STARTUP_BOUND)
		if kind == "chromium":
			program = chromiumSession.startChromium(desktop, EMPTY_PAGE)
		else:
			program = chromiumSession.startElectron(desktop, "electronChat", EMPTY_PAGE, window=EMPTY_TITLE)
		session = Session(desktop, nvda, program, directory)
		desktop.expect(f"{BOX} blank", since=0, timeout=STARTUP_BOUND)
		# Past the moment Linda waits before looking at the program.
		time.sleep(1 + SETTLE)
		typeEchoed(session, "ab")
		step(session, "Left", "b")
		step(session, "Left", "a")
		assert not [text for text in desktop.spokenSince(0) if "force-renderer" in text]
		step(session, "Insert+q", "Exit Linda\N{HORIZONTAL ELLIPSIS}")
		desktop.press("Return")
		nvda.waitForExit(EXIT_BOUND)
		assert nvda.process.returncode == 0, nvda.describe()
		nvda.assertClean(logNames=("nvda.log",))
