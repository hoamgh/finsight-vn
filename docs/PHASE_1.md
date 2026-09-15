# Phase 1 — Data Foundation

## Objective

Build the smallest trustworthy historical data platform that can later serve FinSight's SQL research tool. The milestone is complete only when the same pipeline can be rerun/backfilled without duplicate published records and missing periods are observable.

## Vertical-slice strategy

FPT is implemented first from source to warehouse. We do not immediately crawl all companies because source assumptions, field mappings and data-quality rules should be proven on one company before scaling horizontally.

## Target architecture

```text
                  ┌─ financial source adapter ─┐
Sources ──────────┤                            ├─> Bronze/raw
                  └─ market source adapter ────┘       │
                                                       ▼
                                             validation/completeness
                                                       │
                                                       ▼
                                                Silver/canonical
                                                       │
                                                       ▼
                                                  PostgreSQL
                                                       │
                                                       ▼
                                                     dbt
                                                       │
                                                       ▼
                                                 Gold marts
```

## Storage semantics

### Bronze/raw

Immutable source-oriented records. Preserve original field names/payload, source, retrieval timestamp and source identifiers. Raw data exists so parser/mapping changes can be replayed without downloading everything again.

### Silver/canonical

Validated records conforming to contracts in `contracts/`. Provider-specific names and units are standardized here. Invalid records do not silently enter serving tables.

### Gold

Analytics-ready dbt models. Ratios and growth metrics are computed deterministically in SQL rather than by an LLM.

## Financial completeness

For each enabled company and year in scope, the expected quarterly set is Q1, Q2, Q3 and Q4, subject to reporting availability for the current year. The pipeline compares expected periods with observed periods and records every gap.

A missing value is not zero. A missing quarter must trigger a data-quality issue and later fallback-source resolution rather than synthetic data.

## Provenance

Canonical financial records must retain at least:

- symbol
- fiscal year / quarter
- statement type
- canonical metric
- value/unit/currency
- source
- source URL or stable source identifier
- ingestion timestamp

## Phase 1 exit criteria

1. FPT quarterly financial data from 2023 onward can be ingested and normalized.
2. FPT daily OHLCV from 2023 onward can be ingested and normalized.
3. Duplicate canonical primary keys are rejected/detected.
4. Missing financial quarters are reported explicitly.
5. A rerun does not create duplicate warehouse records.
6. dbt tests pass for the serving models.
7. The process can then be expanded to the remaining company universe without changing canonical contracts.

## Deferred work

The following belong to later phases: Docling/PDF fallback extraction, embeddings/vector database, RAG, agent routing, near-real-time prices, Redis, Kafka and Flink.
