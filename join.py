"""
join.py — Parallel hash-join operator for ScaleQL workers.

The build phase constructs an in-memory hash table on the smaller (build) side.
The probe phase streams tuples from the larger (probe) side and looks them up.
Both phases run in parallel across partitions using Python's concurrent.futures.
"""

from __future__ import annotations
import concurrent.futures
from collections import defaultdict
from typing import Any, Dict, Iterable, Iterator, List, Tuple

Record = Dict[str, Any]


class HashJoin:
    """
    Parallel equi-join on a single join key.

    Usage:
        join = HashJoin(join_key="customer_id", workers=8)
        results = list(join.execute(build_relation, probe_relation))
    """

    def __init__(self, join_key: str, workers: int = 4):
        self.join_key = join_key
        self.workers = workers

    def execute(
        self, build: Iterable[Record], probe: Iterable[Record]
    ) -> Iterator[Record]:
        # ── Build phase: partition build side by hash(key) ──────────────────
        partitions: Dict[int, List[Record]] = defaultdict(list)
        for row in build:
            bucket = hash(row[self.join_key]) % self.workers
            partitions[bucket].append(row)

        # ── Probe phase: run each partition in parallel ──────────────────────
        probe_partitions: Dict[int, List[Record]] = defaultdict(list)
        for row in probe:
            bucket = hash(row[self.join_key]) % self.workers
            probe_partitions[bucket].append(row)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [
                pool.submit(
                    self._join_partition,
                    partitions.get(b, []),
                    probe_partitions.get(b, []),
                )
                for b in range(self.workers)
            ]
            for f in concurrent.futures.as_completed(futures):
                yield from f.result()

    def _join_partition(
        self, build_part: List[Record], probe_part: List[Record]
    ) -> List[Record]:
        # Build a local hash table for this partition
        ht: Dict[Any, List[Record]] = defaultdict(list)
        for row in build_part:
            ht[row[self.join_key]].append(row)

        results: List[Record] = []
        for probe_row in probe_part:
            for build_row in ht.get(probe_row[self.join_key], []):
                # Merge the two records (probe fields overwrite on collision)
                merged = {**build_row, **probe_row}
                results.append(merged)
        return results
