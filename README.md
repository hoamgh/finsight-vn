# FinSight VN

FinSight VN is a financial intelligence platform for Vietnamese listed companies.

## Phase 1 — Data Foundation

Phase 1 builds a trustworthy historical data layer before the SQL/RAG/realtime agent layers.

### Goals

- Ingest quarterly financial statements from 2023 onward.
- Ingest daily OHLCV market data.
- Retain raw source data for reproducible backfills.
- Detect missing financial periods instead of treating them as zero.
- Normalize provider-specific fields into stable canonical schemas.
- Load validated data into PostgreSQL and transform it with dbt.
- Make ingestion idempotent and testable.

### Phase 1 flow

```text
Financial sources ──┐
                    ├─> Bronze/raw ─> Validation ─> Silver/canonical ─> PostgreSQL ─> dbt/Gold
Market sources ─────┘
```

PDF reports are retained for the later shared Docling layer. SQL fallback extraction, RAG, realtime serving, Kafka, Flink and Redis are intentionally outside Phase 1.

## Initial scope

- Start with FPT as the vertical slice, then expand to the frozen company universe.
- Financial statements: quarterly, 2023–present.
- Market data: daily OHLCV, 2023–present.
- Processing: Python + Pandas.
- Warehouse: PostgreSQL + dbt.
- Orchestration: Airflow after ingestion contracts are stable.

## Repository layout

```text
config/             company universe and project configuration
contracts/          canonical data contracts
src/ingestion/      source adapters and ingestion jobs
src/data_quality/   completeness and validation logic
warehouse/          warehouse DDL/loading assets
dbt/                transformations and tests
tests/              unit/integration tests
docs/               architecture and runbooks
scripts/             source probes and operational utilities
```

## Phase 1 roadmap

- [ ] Freeze company universe and canonical schemas
- [ ] Probe historical market-data providers
- [ ] Ingest FPT financial statements into Bronze/raw
- [ ] Implement expected-period completeness checks
- [ ] Normalize financial metrics into Silver/canonical
- [ ] Ingest daily OHLCV
- [ ] Create PostgreSQL warehouse schema
- [ ] Add dbt staging, facts, marts and tests
- [ ] Backfill remaining companies
- [ ] Run reconciliation and publish Phase 1 validation report

## Data-quality rules

Missing data is never silently converted to zero or interpolated. Every published record must retain source/provenance metadata so values can be traced and reconciled.
