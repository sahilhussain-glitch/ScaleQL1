"""
optimizer.py — Cost-Based Optimizer (CBO) for ScaleQL.

Transforms a logical plan into the cheapest physical plan by comparing
estimated I/O costs for index scans vs full scans, and choosing the
optimal join algorithm (hash join vs nested-loop join).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
import math


# ── Statistics ────────────────────────────────────────────────────────────────

@dataclass
class ColumnStats:
    min_val: float
    max_val: float
    ndv: int          # number of distinct values
    null_frac: float  # fraction of NULLs


@dataclass
class TableStats:
    row_count: int
    page_count: int
    columns: Dict[str, ColumnStats]


# ── Logical plan nodes ────────────────────────────────────────────────────────

@dataclass
class Predicate:
    column: str
    op: str           # "=", "<", ">", "<=", ">="
    value: object


@dataclass
class LogicalScan:
    table: str
    predicates: List[Predicate]


@dataclass
class LogicalJoin:
    left: object
    right: object
    condition: Predicate   # equi-join only for hash join


@dataclass
class LogicalAggregate:
    child: object
    group_by: List[str]
    aggregates: List[str]  # e.g. ["SUM(amount)", "COUNT(*)"]


# ── Physical plan nodes ───────────────────────────────────────────────────────

@dataclass
class PhysicalIndexScan:
    table: str
    index_column: str
    predicate: Predicate
    estimated_rows: int
    estimated_cost: float


@dataclass
class PhysicalSeqScan:
    table: str
    predicates: List[Predicate]
    estimated_rows: int
    estimated_cost: float


@dataclass
class PhysicalHashJoin:
    build_side: object
    probe_side: object
    condition: Predicate
    estimated_cost: float


@dataclass
class PhysicalNestedLoopJoin:
    outer: object
    inner: object
    condition: Predicate
    estimated_cost: float


@dataclass
class PhysicalAggregate:
    child: object
    group_by: List[str]
    aggregates: List[str]
    estimated_cost: float


# ── Optimizer ─────────────────────────────────────────────────────────────────

RANDOM_IO_COST = 4.0   # cost per random page read (index hop)
SEQ_IO_COST = 1.0      # cost per sequential page read
CPU_COST = 0.01        # cost per tuple processed


class CostBasedOptimizer:
    """
    Walks a logical plan tree bottom-up and replaces each node with the
    lowest-cost physical alternative based on table statistics.
    """

    def __init__(self, stats: Dict[str, TableStats], indexes: Dict[str, List[str]]):
        """
        stats   — map of table_name -> TableStats
        indexes — map of table_name -> list of indexed column names
        """
        self.stats = stats
        self.indexes = indexes

    def optimize(self, plan: object) -> object:
        if isinstance(plan, LogicalScan):
            return self._optimize_scan(plan)
        if isinstance(plan, LogicalJoin):
            left = self.optimize(plan.left)
            right = self.optimize(plan.right)
            return self._optimize_join(left, right, plan.condition)
        if isinstance(plan, LogicalAggregate):
            child = self.optimize(plan.child)
            return self._optimize_aggregate(child, plan)
        raise ValueError(f"Unknown plan node: {type(plan)}")

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _optimize_scan(self, scan: LogicalScan) -> object:
        tbl_stats = self.stats.get(scan.table)
        if tbl_stats is None:
            return PhysicalSeqScan(scan.table, scan.predicates, 10_000, 10_000.0)

        seq_cost = tbl_stats.page_count * SEQ_IO_COST
        seq_rows = self._estimate_scan_rows(tbl_stats, scan.predicates)

        best_plan: object = PhysicalSeqScan(
            scan.table, scan.predicates, seq_rows, seq_cost
        )
        best_cost = seq_cost

        indexed_cols = self.indexes.get(scan.table, [])
        for pred in scan.predicates:
            if pred.column not in indexed_cols:
                continue
            idx_rows = self._estimate_index_rows(tbl_stats, pred)
            # Index scan: random I/O per matching leaf page
            idx_pages = max(1, int(idx_rows / (tbl_stats.row_count / tbl_stats.page_count)))
            idx_cost = idx_pages * RANDOM_IO_COST + idx_rows * CPU_COST
            if idx_cost < best_cost:
                best_cost = idx_cost
                best_plan = PhysicalIndexScan(
                    scan.table, pred.column, pred, idx_rows, idx_cost
                )

        return best_plan

    # ── Join ──────────────────────────────────────────────────────────────────

    def _optimize_join(self, left: object, right: object, cond: Predicate) -> object:
        left_rows = self._plan_rows(left)
        right_rows = self._plan_rows(right)

        # Hash join: build a hash table on the smaller side
        build, probe = (left, right) if left_rows <= right_rows else (right, left)
        build_rows = min(left_rows, right_rows)
        probe_rows = max(left_rows, right_rows)
        hash_cost = build_rows * CPU_COST + probe_rows * CPU_COST
        hash_join = PhysicalHashJoin(build, probe, cond, hash_cost)

        # Nested-loop join: O(N*M) — only preferred for tiny outer tables
        nl_cost = left_rows * right_rows * CPU_COST
        if nl_cost < hash_cost:
            return PhysicalNestedLoopJoin(left, right, cond, nl_cost)

        return hash_join

    # ── Aggregate ─────────────────────────────────────────────────────────────

    def _optimize_aggregate(
        self, child: object, agg: LogicalAggregate
    ) -> PhysicalAggregate:
        child_rows = self._plan_rows(child)
        cost = child_rows * CPU_COST * len(agg.aggregates)
        return PhysicalAggregate(child, agg.group_by, agg.aggregates, cost)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _estimate_scan_rows(
        self, stats: TableStats, predicates: List[Predicate]
    ) -> int:
        selectivity = 1.0
        for pred in predicates:
            col = stats.columns.get(pred.column)
            if col is None:
                selectivity *= 0.1
                continue
            if pred.op == "=":
                selectivity *= 1.0 / col.ndv if col.ndv > 0 else 0.01
            elif pred.op in ("<", "<=", ">", ">="):
                # Assume uniform distribution
                try:
                    span = float(col.max_val) - float(col.min_val)
                    val_span = abs(float(pred.value) - float(col.min_val))
                    ratio = val_span / span if span > 0 else 0.5
                    selectivity *= ratio if pred.op in (">", ">=") else (1 - ratio)
                except (TypeError, ValueError):
                    selectivity *= 0.33
        return max(1, int(stats.row_count * selectivity))

    def _estimate_index_rows(self, stats: TableStats, pred: Predicate) -> int:
        return self._estimate_scan_rows(stats, [pred])

    @staticmethod
    def _plan_rows(plan: object) -> int:
        return getattr(plan, "estimated_rows", 1000)
