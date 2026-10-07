#!/usr/bin/env python
from collections.abc import Iterable
from dataclasses import dataclass
import logging
import re


_LINE_RE = re.compile(r"^(\[[^]]*\]) *(.*)$")
_STAMP_RE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\]")
_BLANK_TIMESTAMP = '[--:--.---]'


@dataclass
class Line:
    text: str
    timestamp: int | None = None
    raw_ts: str | None = None

    def set_time(self, ts: int) -> None:
        self.timestamp = ts
        self.raw_ts = None

    def adj_time(self, millis: int) -> int | None:
        if self.timestamp is None:
            return None
        self.set_time(self.timestamp + millis)
        return self.timestamp


def parse_lrc_line(text_line: str) -> Line:
    match = _LINE_RE.match(text_line)
    if match is None:
        return Line(text_line)

    text = match.group(2)
    raw_ts = match.group(1)

    match = _STAMP_RE.match(raw_ts)
    if match is None:
        return Line(text, raw_ts=raw_ts)

    ts = int(match.group(1)) * 60 * 1000
    ts += round(float(match.group(2)) * 1000)
    return Line(text, ts, raw_ts)


def format_timestamp(ts: int) -> str:
    if ts is None:
        return _BLANK_TIMESTAMP
    sec, ms = divmod(ts, 1000)
    minute, sec = divmod(sec, 60)
    return f"[{minute:02}:{sec:02}.{ms:03}]"


def format_line(line: Line) -> str:
    if line.timestamp is not None:
        stamp = format_timestamp(line.timestamp)
    elif line.raw_ts is not None:
        stamp = line.raw_ts
    else:
        stamp = ""

    return stamp + (" " if stamp else "") + line.text


def serialize(lyrics: list[Line]) -> str:
    return "\n".join(format_line(line) for line in lyrics) + "\n"


def parse_lrc_file(lrc_file: Iterable[str]) -> list[Line]:
    logging.debug("parsing lrc")
    lines = []

    for raw_line in lrc_file:
        lines.append(parse_lrc_line(raw_line.rstrip("\n")))
    return lines
