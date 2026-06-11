# Latency bookkeeping for the real-time generate loop.
#
# Real-time audio lives or dies on one comparison: does the model generate a
# chunk faster than that chunk takes to play? ChunkBudgetTracker is the pure
# accounting core — the engine times each generate_chunk() call and records it
# here against the chunk's own playback duration (its real-time budget). No
# clocks, no I/O: the caller supplies both measurements, so the math is
# exhaustively unit-testable. The end-of-session summary() is the number that
# says whether a given model size is viable live on a given machine.

from dataclasses import dataclass


@dataclass
class ChunkBudgetTracker:
    """Accumulate per-chunk generation times against the real-time budget."""

    chunks: int = 0
    over_budget: int = 0
    total_gen_seconds: float = 0.0
    worst_gen_seconds: float = 0.0
    last_gen_seconds: float = 0.0
    last_budget_seconds: float = 0.0

    def record(self, gen_seconds: float, budget_seconds: float) -> bool:
        """Record one chunk; return True if it blew its real-time budget."""
        self.chunks += 1
        self.total_gen_seconds += gen_seconds
        self.worst_gen_seconds = max(self.worst_gen_seconds, gen_seconds)
        self.last_gen_seconds = gen_seconds
        self.last_budget_seconds = budget_seconds
        blew_budget = gen_seconds > budget_seconds
        if blew_budget:
            self.over_budget += 1
        return blew_budget

    @property
    def mean_gen_seconds(self) -> float:
        return self.total_gen_seconds / self.chunks if self.chunks else 0.0

    def summary(self) -> str:
        """One-line human summary for end-of-session logging."""
        if not self.chunks:
            return "latency: no chunks generated"
        utilization = (
            self.mean_gen_seconds / self.last_budget_seconds * 100.0
            if self.last_budget_seconds
            else 0.0
        )
        return (
            f"latency: {self.chunks} chunks, "
            f"mean {self.mean_gen_seconds:.2f}s / {self.last_budget_seconds:.2f}s "
            f"budget ({utilization:.0f}%), "
            f"worst {self.worst_gen_seconds:.2f}s, "
            f"{self.over_budget} over budget"
        )
