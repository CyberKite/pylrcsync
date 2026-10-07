#!/usr/bin/env python3
from collections.abc import Iterator, Iterable
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import argparse
import curses
import curses.ascii
import logging
import os
import shlex
import shutil
import subprocess
import tempfile

import liblrc
import mpv_client


logging.basicConfig(
    filename="/tmp/pylrcedit.log",
    level=logging.DEBUG,
)


EDITOR = (os.environ.get("VISUAL")
          or os.environ.get("EDITOR")
          or ("vim" if shutil.which("vim") else "vi"))


@contextmanager
def uncursed(stdscr: curses.window) -> Iterator[None]:
    curses.def_prog_mode()
    curses.endwin()
    try:
        yield
    finally:
        curses.reset_prog_mode()
        stdscr.clearok(True)


@dataclass
class FormatFragment:
    text: str = ""
    attrs: int = 0

    def __str__(self) -> str:
        return self.text


def addfrags(
    win: curses.window,
    y: int,
    x: int,
    fragments: Iterable[FormatFragment],
) -> None:
    win.move(y, x)
    for fragment in fragments:
        win.addstr(fragment.text, fragment.attrs)


@dataclass
class State:
    playing: bool = False
    speed: float = 1.0
    timestamp: int = 0
    duration: int = 0
    cursor: int = 0
    scroll_pos: int = 0
    modified: bool = False
    running: bool = True
    lyrics: list[liblrc.Line] = field(default_factory=list)
    hist: list[list[liblrc.Line]] = field(default_factory=list)
    message: tuple[FormatFragment, ...] = ()

    def undo_push(self) -> None:
        self.hist.append(deepcopy(self.lyrics))
        # should hopefully be nicer towards the allocator.
        if len(self.hist) > 30:
            del self.hist[:-20]

    # TODO: Use a @property or something...
    def undo_pop(self, count: int = 1) -> None:
        if count < 1:
            logging.warning(f"someone just tried to undo {count} operations")
            # this is nonsense, just return
            return
        if len(self.hist) < count:
            raise ValueError('undo history too short')
        self.lyrics = self.hist[-count]
        del self.hist[-count:]
        self.modified = True


def ellipsize(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[:width - 1] + "…"


def ellipsize_frags(
    fragments: Iterable[FormatFragment],
    width: int,
) -> tuple[FormatFragment, ...]:
    result = []

    if width <= 0:
        return ()

    for frag in fragments:
        if len(frag.text) <= width:
            result.append(frag)
            width -= len(frag.text)
        else:
            result.append(FormatFragment(
                ellipsize(frag.text, width),
                frag.attrs,
            ))
            break

    return tuple(result)


def clamp_viewport(state: State, line_count: int, height: int):
    if line_count == 0:
        state.cursor = 0
        state.scroll_pos = 0
        return

    # Cursor must refer to an existing line.
    state.cursor = max(0, min(state.cursor, line_count - 1))

    # If cursor left the viewport, recenter around it.
    rel_cursor = state.cursor - state.scroll_pos
    if rel_cursor < 0 or rel_cursor >= height:
        state.scroll_pos = state.cursor - height // 3

    # Viewport itself must stay within the document.
    max_scroll = max(0, line_count - height)
    state.scroll_pos = max(0, min(state.scroll_pos, max_scroll))


def draw_editor(
    editor: curses.window,
    state: State,
) -> None:
    h, w = editor.getmaxyx()

    clamp_viewport(state, len(state.lyrics), h)

    editor.erase()
    if curses.has_colors():
        ts_attr = curses.color_pair(1)
    else:
        ts_attr = curses.A_DIM
    for y in range(h):
        i = state.scroll_pos + y
        if i >= len(state.lyrics):
            break
        line = state.lyrics[i]
        stamp = liblrc.format_timestamp(line.timestamp)
        if i + 1 < len(state.lyrics):
            end_time = state.lyrics[i + 1].timestamp
        else:
            end_time = None
        text = line.text
        text_start = max(len(stamp), 12)
        flags = 0
        if line.timestamp is not None and state.timestamp >= line.timestamp:
            flags |= curses.A_BOLD
            if end_time is None or state.timestamp < end_time:
                flags |= curses.A_REVERSE
        if i == state.cursor:
            flags |= curses.A_UNDERLINE
        editor.addstr(y, 0, stamp, ts_attr | flags)
        editor.addstr(y, text_start,
                      ellipsize(text, w - text_start - 1), flags)

    # yes this is stupid but it's visually okay
    editor.move(state.cursor - state.scroll_pos, 6)
    editor.noutrefresh()


def update_status(status: curses.window, state: State) -> None:
    playback_indicator = "[PLAYING]" if state.playing else "[PAUSED]"
    pos_indicator = (
        liblrc.format_timestamp(state.timestamp) +
        " / " +
        liblrc.format_timestamp(state.duration)
    )

    h, w = status.getmaxyx()
    status.erase()
    status.addstr(0, 0, playback_indicator)
    if state.modified:
        status.addstr(0, 9, "[+]")
    if abs(state.speed-1.0) > 0.01:
        status.addstr(0, 13, f"{state.speed:.2f}x")

    right_start = w - len(pos_indicator) - 10
    message_space = right_start - 20 - 1
    addfrags(status, 0, 20, ellipsize_frags(state.message, message_space))

    if state.hist:
        status.addstr(0, right_start, f"[{len(state.hist)}]")
    status.addstr(0, w-len(pos_indicator)-1, pos_indicator)

    status.noutrefresh()


def handle_key(
    key: str | int,
    state: State,
    mpv: mpv_client.Mpv,
    lrc_file: str,
    stdscr: curses.window
) -> None:
    # TODO: Think of a context object. Or bundle it all into a State.
    match key:
        case '\x1b':
            state.message = (FormatFragment('-- NORMAL --', curses.A_BOLD),)
        case 'v':
            state.message = (FormatFragment('-- TEXTUAL --', curses.A_BOLD),)
        case '/':
            state.message = (
                FormatFragment('Pattern not found: .*', curses.A_BOLD),)
        case '?':
            pipe = FormatFragment(' | ', curses.A_DIM)
            state.message = (
                FormatFragment('jk'), pipe,
                FormatFragment('Space'), pipe,
                FormatFragment('<-/->'), pipe,
                FormatFragment('Enter'), pipe,
                FormatFragment('hl'), pipe,
                FormatFragment('euwq'),
            )
        case ':':
            state.message = (FormatFragment('E492: Not an editor command',
                                            curses.A_BOLD),)
        case 'y':
            state.message = (FormatFragment('0 lines yanked', curses.A_DIM),)
        case 'd' | 'c' | 'R' | 'i':
            state.message = (FormatFragment(
                'E21: Cannot make changes, modifiable is off', curses.A_BOLD),)
        case 'q':
            if state.modified:
                state.message = (FormatFragment(
                    "Refusing, file has been modified.", curses.A_BOLD),)
            else:
                state.running = False
        case 'Q':
            state.running = False
        case 'j':
            state.cursor += 1
        case 'k':
            state.cursor -= 1
        case 'G':
            state.cursor = len(state.lyrics) - 1
        case 'g':
            state.cursor = 0
        case 'p':
            mpv.toggle_pause()
        case 'P':
            mpv.pause()
        case ' ':
            state.undo_push()
            state.lyrics[state.cursor].set_time(state.timestamp)
            state.modified = True
            state.cursor += 1
        case 't':
            state.undo_push()
            state.lyrics[state.cursor].set_time(state.timestamp)
            state.modified = True
        case 'h':
            state.undo_push()
            state.lyrics[state.cursor].adj_time(-50)
            state.modified = True
        case 'l':
            state.undo_push()
            state.lyrics[state.cursor].adj_time(50)
            state.modified = True
        case 'H':
            state.undo_push()
            state.lyrics[state.cursor].adj_time(-250)
            state.modified = True
        case 'L':
            state.undo_push()
            state.lyrics[state.cursor].adj_time(250)
            state.modified = True
        case 'u':
            if state.hist:
                state.undo_pop()
                state.message = (FormatFragment("Undid ", curses.A_DIM),
                                 FormatFragment(str(1)),
                                 FormatFragment(" operation", curses.A_DIM),)
            else:
                state.message = (FormatFragment("Already at oldest change",
                                                curses.A_BOLD),)
        case '\n':
            ts = state.lyrics[state.cursor].timestamp
            if ts is not None:
                ts += 10  # yes, this is evil, but it reduces visual glitches
                mpv.seek(ts / 1000, "absolute+exact")
                mpv.play()
        case 's':
            ts = state.lyrics[state.cursor].timestamp
            if ts is not None:
                mpv.seek(ts / 1000, "absolute+exact")
        case curses.KEY_LEFT:
            mpv.seek(-1, "relative")
        case curses.KEY_RIGHT:
            mpv.seek(1, "relative")
        case '[':
            mpv.set_property("speed", state.speed * (9/10))
        case ']':
            mpv.set_property("speed", state.speed * (10/9))
        case '{':
            mpv.set_property("speed", state.speed * (1/2))
        case '}':
            mpv.set_property("speed", state.speed * 2)
        case '=':
            mpv.set_property("speed", 1)
        case 'w':
            write_lrc(lrc_file, state.lyrics)
            if state.modified:
                state.message = (FormatFragment("Saved.", curses.A_DIM),)
                state.modified = False
            else:
                state.message = (
                    FormatFragment("No changes to save. ", curses.A_DIM),
                    FormatFragment("Wrote it anyway.",
                                   curses.A_DIM | curses.A_ITALIC),
                )
        case 'x':
            write_lrc(lrc_file, state.lyrics)
            state.running = False
        case 'e':
            try:
                mpv.pause()
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".lrc",
                    encoding="utf-8",
                ) as temp_lrc_file:
                    state.undo_push()
                    state.modified = True
                    temp_lrc_file.write(liblrc.serialize(state.lyrics))
                    temp_lrc_file.flush()

                    with uncursed(stdscr):
                        subprocess.run((*shlex.split(EDITOR),
                                        temp_lrc_file.name),
                                       check=True)

                    # there's a reason we're doing it this way, namely in case
                    # the editor creates a new inode. Or sth evil like that.
                    state.lyrics = read_lrc(temp_lrc_file.name)
            except subprocess.CalledProcessError as e:
                state.message = (
                    FormatFragment("Editor exited with status "),
                    FormatFragment(str(e.returncode), curses.A_BOLD),
                )
            except UnicodeDecodeError:
                state.message = (
                    FormatFragment("Editor wrote invalid Unicode (…?)",
                                   curses.A_BOLD),
                )
            except OSError as e:
                state.message = (
                    FormatFragment("External edit failed: ", curses.A_BOLD),
                    FormatFragment(str(e)),)
            finally:
                # this works because we poll and mpv can't
                # update us while we block.
                if state.playing:
                    mpv.play()


def read_lrc(lrc_file: str) -> list[liblrc.Line]:
    with open(lrc_file, "r", encoding="utf-8") as f:
        lyrics = liblrc.parse_lrc_file(f)
    logging.debug(lyrics)
    return lyrics


def write_lrc(lrc_file: str, lyrics: list[liblrc.Line]) -> None:
    data = liblrc.serialize(lyrics)
    with open(lrc_file, "w", encoding="utf-8") as f:
        f.write(data)


def app(
    stdscr: curses.window,
    lrc_file: str,
    mpv_socket: str,
) -> None:
    state = State()

    mpv = mpv_client.Mpv(mpv_socket)

    mpv.observe(1, "pause")
    mpv.observe(2, "time-pos")
    mpv.observe(3, "duration")
    mpv.observe(4, "speed")

    # Clear screen
    stdscr.clear()
    stdscr.timeout(32)

    curses.set_escdelay(50)

    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)

    h, w = stdscr.getmaxyx()

    state.lyrics = read_lrc(lrc_file)

    editor = curses.newwin(h - 1, w, 0, 0)
    status = curses.newwin(1, w, h - 1, 0)

    while state.running:
        try:
            key = stdscr.get_wch()
        except curses.error:
            key = None

        for message in mpv.poll():
            match message.get("name"):
                case "pause":  # pause
                    state.playing = not message["data"]
                case "time-pos":  # time-pos
                    if message.get("data") is not None:
                        state.timestamp = round(message["data"] * 1000)
                case "duration":
                    if message.get("data") is not None:
                        state.duration = round(message["data"] * 1000)
                case "speed":
                    if message.get("data") is not None:
                        state.speed = message["data"]
                case _:
                    logging.warning("unhandled event:" + repr(message))

        if key == curses.KEY_RESIZE:
            h, w = stdscr.getmaxyx()

            stdscr.erase()
            editor.resize(h - 1, w)
            status.resize(1, w)
            status.mvwin(h - 1, 0)

            stdscr.clearok(True)
        elif key is not None:
            handle_key(key, state, mpv, lrc_file, stdscr)

        update_status(status, state)
        draw_editor(editor, state)

        curses.doupdate()


def main():
    logging.debug("main reached")
    parser = argparse.ArgumentParser(
        prog='PyLRCSync',
        description='TUI-based LRC timestamp editor',
        epilog='I use Busybox plus Linux btw.'
    )
    parser.add_argument('lrcfile', type=str)
    parser.add_argument('soundfile', type=str)
    args = parser.parse_args()

    if not os.path.isfile(args.lrcfile):
        parser.error(f"LRC file not found: {args.lrcfile}")

    if not os.path.isfile(args.soundfile):
        parser.error(f"audio file not found: {args.soundfile}")

    with tempfile.TemporaryDirectory(prefix="pylrcedit-") as tmpdir:
        mpv_socket = tmpdir + "/pylrcedit-mpv.sock"
        with subprocess.Popen([
            "mpv",
            "--input-ipc-server=" + mpv_socket,
            "--no-terminal",
            "--idle",
            "--keep-open=yes",
            "--",
            args.soundfile,
        ]) as mpv_proc:
            try:
                logging.debug("app initialising")
                curses.wrapper(app, args.lrcfile, mpv_socket)
                logging.debug("app exited")
            finally:
                mpv_proc.terminate()


if __name__ == "__main__":
    main()
