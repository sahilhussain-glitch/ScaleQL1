"""
btree.py — In-memory B-Tree index for ScaleQL.

Supports O(log n) point lookups and range scans used by the query planner
when the optimizer estimates an index scan is cheaper than a full table scan.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple


@dataclass
class _BTreeNode:
    keys: List[Any] = field(default_factory=list)
    values: List[Any] = field(default_factory=list)   # only in leaf nodes
    children: List["_BTreeNode"] = field(default_factory=list)
    is_leaf: bool = True


class BTree:
    """B-Tree with configurable order (minimum degree t).

    A node can hold between t-1 and 2t-1 keys.
    All data records are stored in leaf nodes (B+ tree variant).
    """

    def __init__(self, t: int = 64):
        self.t = t          # minimum degree
        self.root = _BTreeNode(is_leaf=True)
        self._size = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def insert(self, key: Any, value: Any) -> None:
        """Insert key/value pair into the tree."""
        root = self.root
        if len(root.keys) == 2 * self.t - 1:
            # Root is full — split it and grow the tree height by 1
            new_root = _BTreeNode(is_leaf=False)
            new_root.children.append(self.root)
            self._split_child(new_root, 0)
            self.root = new_root
        self._insert_non_full(self.root, key, value)
        self._size += 1

    def search(self, key: Any) -> Optional[Any]:
        """Return the value for *key*, or None if not found."""
        node, idx = self._search_node(self.root, key)
        if node is not None:
            return node.values[idx]
        return None

    def range_scan(self, lo: Any, hi: Any) -> List[Tuple[Any, Any]]:
        """Return all (key, value) pairs where lo <= key <= hi."""
        results: List[Tuple[Any, Any]] = []
        self._range(self.root, lo, hi, results)
        return results

    def __len__(self) -> int:
        return self._size

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _insert_non_full(self, node: _BTreeNode, key: Any, value: Any) -> None:
        i = len(node.keys) - 1
        if node.is_leaf:
            # Find insertion position (keep keys sorted)
            node.keys.append(None)
            node.values.append(None)
            while i >= 0 and key < node.keys[i]:
                node.keys[i + 1] = node.keys[i]
                node.values[i + 1] = node.values[i]
                i -= 1
            node.keys[i + 1] = key
            node.values[i + 1] = value
        else:
            while i >= 0 and key < node.keys[i]:
                i -= 1
            i += 1
            if len(node.children[i].keys) == 2 * self.t - 1:
                self._split_child(node, i)
                if key > node.keys[i]:
                    i += 1
            self._insert_non_full(node.children[i], key, value)

    def _split_child(self, parent: _BTreeNode, i: int) -> None:
        t = self.t
        full = parent.children[i]
        new_node = _BTreeNode(is_leaf=full.is_leaf)

        # Promote middle key to parent
        mid = t - 1
        parent.keys.insert(i, full.keys[mid])
        parent.children.insert(i + 1, new_node)

        # Move upper half to new_node
        new_node.keys = full.keys[mid + 1:]
        full.keys = full.keys[:mid]
        if full.is_leaf:
            new_node.values = full.values[mid + 1:]
            full.values = full.values[:mid]
        else:
            new_node.children = full.children[mid + 1:]
            full.children = full.children[:mid + 1]

    def _search_node(
        self, node: _BTreeNode, key: Any
    ) -> Tuple[Optional[_BTreeNode], int]:
        i = 0
        while i < len(node.keys) and key > node.keys[i]:
            i += 1
        if i < len(node.keys) and key == node.keys[i]:
            if node.is_leaf:
                return node, i
            # Internal node hit — go right child for B+ tree semantics
            return self._search_node(node.children[i + 1], key)
        if node.is_leaf:
            return None, -1
        return self._search_node(node.children[i], key)

    def _range(
        self,
        node: _BTreeNode,
        lo: Any,
        hi: Any,
        results: List[Tuple[Any, Any]],
    ) -> None:
        i = 0
        while i < len(node.keys) and node.keys[i] < lo:
            i += 1
        if node.is_leaf:
            while i < len(node.keys) and node.keys[i] <= hi:
                results.append((node.keys[i], node.values[i]))
                i += 1
        else:
            while i < len(node.keys) and node.keys[i] <= hi:
                self._range(node.children[i], lo, hi, results)
                results.append((node.keys[i], node.values[i]))
                i += 1
            self._range(node.children[i], lo, hi, results)
