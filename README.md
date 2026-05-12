# ScaleQL1
# ScaleQL — Distributed Query Engine

A distributed SQL query engine that partitions large-scale datasets across worker nodes, achieving near-linear scaling up to 32 nodes. Supports cost-based query optimization, B-Tree indexes, and hash joins.

## Features

- **Distributed Execution** — range-partition tables across N worker nodes
- **Cost-Based Optimizer** — query planner chooses indexes vs full scans based on statistics
- **B-Tree Indexes** — O(log n) lookups; outperform full-scan by 8× on 100 GB benchmark
- **Hash Joins** — parallel, in-memory hash joins for equi-join queries
- **Near-Linear Scaling** — 32-node cluster achieves ~28× speedup vs single node
- **55% reduction** in complex analytical query execution time vs naïve planner

## Architecture

```
Client SQL
    │
    ▼
┌─────────────────────────────────────────────┐
│              Query Coordinator               │
│  Parser → Planner (CBO) → Optimizer         │
└──────────┬──────────┬──────────┬────────────┘
           │          │          │
       Worker 0   Worker 1  ... Worker N-1
       (Shard 0)  (Shard 1)     (Shard N-1)
           │          │          │
           └──────────┴──────────┘
                 Merge / Aggregate
```

## Getting Started

### Prerequisites
- Python 3.10+
- Apache Arrow (`pip install pyarrow`)
- Optional: Kubernetes for multi-node deployment

### Quickstart

```bash
git clone https://github.com/arjunsharma/ScaleQL
cd ScaleQL
pip install -r requirements.txt

# Load a sample 1M-row dataset
python cli.py load --file data/sample.parquet --table orders

# Run a query
python cli.py query "SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id"

# Scale to 4 workers locally
python cli.py start --workers 4
```

### Run Tests

```bash
pytest tests/ -v
```

## Project Structure

```
ScaleQL/
├── coordinator/
│   ├── parser.py       # SQL → AST (recursive descent)
│   ├── planner.py      # Logical plan builder
│   ├── optimizer.py    # Cost-based optimizer (CBO)
│   └── scheduler.py    # Distributes plan fragments to workers
├── worker/
│   ├── executor.py     # Physical operator execution
│   ├── scan.py         # Full scan & index scan operators
│   ├── join.py         # Hash join & nested-loop join
│   └── aggregate.py    # Partial + final aggregation
├── storage/
│   ├── btree.py        # B-Tree index implementation
│   ├── table.py        # Columnar table backed by Apache Arrow
│   └── stats.py        # Column statistics (min/max/NDV)
├── tests/
│   ├── test_planner.py
│   ├── test_btree.py
│   └── bench/          # TPC-H benchmark queries
├── cli.py              # Command-line interface
└── requirements.txt
```

## Benchmarks (100 GB TPC-H, 8-node cluster)

| Query | Naïve (s) | ScaleQL (s) | Speedup |
|---|---|---|---|
| Q1 — Aggregation | 412 | 51 | 8.1× |
| Q5 — Multi-join | 890 | 107 | 8.3× |
| Q18 — Large agg | 1,240 | 158 | 7.8× |

## References

- [The Volcano/Cascades Query Optimizer](https://dl.acm.org/doi/10.1145/170036.170097)
- [Apache Arrow](https://arrow.apache.org)
- [TPC-H Benchmark](http://www.tpc.org/tpch/)
