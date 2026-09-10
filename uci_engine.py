from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import TextIO


@dataclass
class EngineLine:
    multipv: int = 1
    depth: int = 0
    score_cp: int | None = None
    mate: int | None = None
    pv: list[str] = field(default_factory=list)
    nodes: int = 0
    nps: int = 0
    time_ms: int = 0

    @property
    def is_mate(self) -> bool:
        return self.mate is not None


class UCIEngine:
    def __init__(self, engine_path: str, threads: int = 1, multipv: int = 3):
        self.engine_path = engine_path
        self.threads = threads
        self.multipv = multipv
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> "UCIEngine":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        self.process = subprocess.Popen(
            [self.engine_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._wait_for("uciok")
        self._send(f"setoption name Threads value {self.threads}")
        self._send(f"setoption name MultiPV value {self.multipv}")
        self._send("isready")
        self._wait_for("readyok")

    def close(self) -> None:
        if self.process is None:
            return
        try:
            self._send("quit")
            self.process.wait(timeout=2)
        except Exception:
            self.process.kill()
        finally:
            self.process = None

    def _send(self, command: str) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("Engine is not running")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def _readline(self) -> str:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("Engine is not running")
        line = self.process.stdout.readline()
        if line == "":
            raise RuntimeError("Engine process exited unexpectedly")
        return line.rstrip("\r\n")

    def _wait_for(self, expected: str) -> None:
        while True:
            if self._readline().strip() == expected:
                return

    @staticmethod
    def _parse_info(line: str) -> EngineLine | None:
        parts = line.split()
        if not parts or parts[0] != "info":
            return None

        result = EngineLine()
        i = 1
        while i < len(parts):
            key = parts[i]
            if key == "depth" and i + 1 < len(parts):
                result.depth = int(parts[i + 1]); i += 2
            elif key == "multipv" and i + 1 < len(parts):
                result.multipv = int(parts[i + 1]); i += 2
            elif key == "nodes" and i + 1 < len(parts):
                result.nodes = int(parts[i + 1]); i += 2
            elif key == "nps" and i + 1 < len(parts):
                result.nps = int(parts[i + 1]); i += 2
            elif key == "time" and i + 1 < len(parts):
                result.time_ms = int(parts[i + 1]); i += 2
            elif key == "score" and i + 2 < len(parts):
                kind, value = parts[i + 1], parts[i + 2]
                if kind == "cp":
                    result.score_cp = int(value)
                elif kind == "mate":
                    result.mate = int(value)
                i += 3
            elif key == "pv":
                result.pv = parts[i + 1:]
                break
            else:
                i += 1
        return result

    def analyze(self, fen: str, moves: list[str], depth: int) -> dict[int, EngineLine]:
        move_text = " ".join(moves)
        command = f"position fen {fen}"
        if move_text:
            command += f" moves {move_text}"
        self._send(command)
        self._send(f"go depth {depth}")

        lines: dict[int, EngineLine] = {}
        while True:
            line = self._readline()
            if line.startswith("info "):
                parsed = self._parse_info(line)
                if parsed is not None and parsed.pv:
                    old = lines.get(parsed.multipv)
                    if old is None or parsed.depth >= old.depth:
                        lines[parsed.multipv] = parsed
            elif line.startswith("bestmove "):
                break
        return lines
