#!/usr/bin/env python
from time import sleep
import json
import socket


type JSONValue = (
    str
    | int
    | float
    | bool
    | None
    | list["JSONValue"]
    | dict[str, "JSONValue"]
)


class Mpv:
    def __init__(self, socket_path: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.buffer = b""

        while True:
            try:
                self.sock.connect(socket_path)
                break
            except FileNotFoundError:
                sleep(0.01)

        self.sock.setblocking(False)

    # yes this lets you send nearly arbitrary weird data, that's a feature,
    # this function is deliberately extremely low level.
    def send(self, command: JSONValue) -> None:
        data = json.dumps({"command": command}) + "\n"
        self.sock.sendall(data.encode())

    def observe(self, request_id: int, property: str) -> None:
        self.send(["observe_property", request_id, property])

    def poll(self) -> list[dict[str, JSONValue]]:
        try:
            self.buffer += self.sock.recv(4096)
        except BlockingIOError:
            return []

        messages = []

        while b"\n" in self.buffer:
            raw, self.buffer = self.buffer.split(b"\n", 1)
            if raw:
                messages.append(json.loads(raw))

        return messages

    def set_property(self, property: str, value: JSONValue) -> None:
        self.send(["set_property", property, value])

    def set(self, name: str, value: JSONValue) -> None:
        self.send(["set", name, value])

    def pause(self) -> None:
        self.set_property("pause", True)

    def play(self) -> None:
        self.set_property("pause", False)

    def toggle_pause(self) -> None:
        self.send(["cycle", "pause"])

    def seek(self, ts: int, *flags: str) -> None:
        self.send(["seek", ts, "+".join(flags)])
