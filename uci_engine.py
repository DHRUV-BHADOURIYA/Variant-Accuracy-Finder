from __future__ import annotations

import subprocess
from dataclasses import dataclass, field


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
    bound: str | None = None

    @property
    def is_mate(self) -> bool:
        return self.mate is not None

    @property
    def is_exact(self) -> bool:
        return self.bound is None


@dataclass
class SearchResult:
    lines: dict[int, EngineLine] = field(default_factory=dict)
    bestmove: str | None = None


class UCIEngine:
    def __init__(self, engine_path: str, threads: int = 1, multipv: int = 1):
        self.engine_path = engine_path
        self.threads = threads
        self.multipv = multipv
        self.multipv_supported = False
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
        self._wait_for_uci()

        self._send(f"setoption name Threads value {self.threads}")
        if self.multipv_supported and self.multipv > 1:
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

    def _wait_for_uci(self) -> None:
        """Consume UCI initialization output and detect advertised capabilities."""
        self.multipv_supported = False
        while True:
            line = self._readline().strip()
            if line.lower().startswith("option name multipv "):
                self.multipv_supported = True
            if line == "uciok":
                return

    def clear_hash(self) -> None:
        """Clear the engine transposition table before an independent search."""
        self._send("setoption name Clear Hash")
        self._send("isready")
        self._wait_for("readyok")

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
                try:
                    result.depth = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif key == "multipv" and i + 1 < len(parts):
                try:
                    result.multipv = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif key == "nodes" and i + 1 < len(parts):
                try:
                    result.nodes = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif key == "nps" and i + 1 < len(parts):
                try:
                    result.nps = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif key == "time" and i + 1 < len(parts):
                try:
                    result.time_ms = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif key == "score" and i + 2 < len(parts):
                kind, value = parts[i + 1], parts[i + 2]
                try:
                    if kind == "cp":
                        result.score_cp = int(value)
                    elif kind == "mate":
                        result.mate = int(value)
                except ValueError:
                    pass
                i += 3
                if i < len(parts) and parts[i] in {"lowerbound", "upperbound"}:
                    result.bound = parts[i]
                    i += 1
            elif key == "pv":
                result.pv = parts[i + 1:]
                break
            else:
                i += 1
        return result

    @staticmethod
    def _should_replace(old: EngineLine | None, new: EngineLine) -> bool:
        if old is None:
            return True
        if new.depth > old.depth:
            return True
        if new.depth < old.depth:
            return False
        if old.bound is not None and new.bound is None:
            return True
        if new.pv and not old.pv:
            return True
        if (new.score_cp is not None or new.mate is not None) and old.score_cp is None and old.mate is None:
            return True
        return False

    def analyze(
        self,
        fen: str,
        moves: list[str],
        depth: int,
        searchmoves: list[str] | None = None,
    ) -> SearchResult:
        """Analyze a position, optionally restricting the root to searchmoves."""
        move_text = " ".join(moves)
        command = f"position fen {fen}"
        if move_text:
            command += f" moves {move_text}"
        self._send(command)

        go_command = f"go depth {depth}"
        if searchmoves:
            go_command += " searchmoves " + " ".join(searchmoves)
        self._send(go_command)

        result = SearchResult()
        while True:
            line = self._readline()
            if line.startswith("info "):
                parsed = self._parse_info(line)
                # A valid UCI engine may report score/depth without a PV.
                # Keep score-only lines because V2 accuracy needs the position
                # evaluation; MultiPV agreement separately requires PV moves.
                if parsed is not None and (parsed.pv or parsed.score_cp is not None or parsed.mate is not None):
                    old = result.lines.get(parsed.multipv)
                    if self._should_replace(old, parsed):
                        result.lines[parsed.multipv] = parsed
            elif line.startswith("bestmove "):
                parts = line.split()
                result.bestmove = parts[1] if len(parts) > 1 else None
                break

        # Be defensive: an engine may advertise MultiPV but fail to return
        # multiple usable root lines. Candidate ranking is only enabled when
        # genuine multiple PVs are available.
        if self.multipv > 1 and len(result.lines) < 2:
            self.multipv_supported = False

        return result
