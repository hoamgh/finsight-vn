# FinSight VN

FinSight VN is a financial intelligence platform for Vietnamese listed companies. It is being built around two complementary kinds of research: structured financial analysis over canonical facts, and evidence-grounded answers from official financial documents.

The current repository implements the financial-data foundation: replayable ingestion, period-safe normalization, multi-source reconciliation, data-quality checks, official-PDF extraction, and idempotent warehouse loading. The SQL and RAG serving layers are the next stages, not completed features.

## Why FinSight?

Financial research questions do not all belong in the same system:

```text
Structured question                         Document question
"How did FPT revenue change?"               "What risks did management discuss?"
             |                                             |
             v                                             v
      SQL / analytics                               Document retrieval
```

FinSight's goal is to provide one interface over both paths while keeping every answer traceable to validated data or source documents. A trustworthy "data unavailable" result is preferable to a plausible value produced from a missing or mislabeled period.

## Architecture

Solid lines represent code present in this repository. Dotted lines represent the intended serving layer.

```text
 CafeF / VCI-Vietcap / official filings
                    |
                    v
        Replayable raw snapshots
        (HTML, JSON, PDF + metadata)
                    |
                    v
   Parse, normalize, and reconcile
                    |
          +---------+---------+
          |                   |
          v                   v
 Canonical financial      Data-quality issues
 facts with provenance    and accounting checks
          |
          v
 PostgreSQL / JSONL
          :
          v
   dbt analytical marts  [planned]
          |
     +----+----+
     :         :
     v         v
 SQL Agent   RAG Agent    [planned]
     \         /
      \       /
       v     v
     FinSight Agent       [planned]
```

The official-document branch has an implemented first slice: Docling table extraction can identify and preserve an income statement from a PDF, and the resulting structured extraction can participate in reconciliation. Chunking, embeddings, retrieval, and answer generation are not implemented yet.

## What It Can Do Today

- Backfill quarterly Income Statement, Balance Sheet, and Cash Flow metrics from CafeF and VCI-backed Vnstock sources.
- Backfill annual statements through a separate annual contract so annual values cannot silently enter quarterly facts.
- Retain raw provider responses and acquisition metadata for replay and audit.
- Normalize provider-specific fields into canonical financial records with source references and ingestion timestamps.
- Reconcile sources, surface material conflicts, and use an official extraction when one is available.
- Detect missing quarters and validate `Assets = Liabilities + Equity` within an explicit tolerance.
- Upsert canonical facts and quality issues into PostgreSQL without duplicating their natural keys.
- Extract a structured Income Statement candidate from an official PDF with confidence and ambiguity checks.

## Engineering Highlights

### Period-safe financial ingestion

An ingestion investigation exposed a dangerous class of bug: values from a long-to-wide provider response could become detached from their fiscal-quarter labels when positional columns were trusted.

The VCI normalization path now preserves the upstream `(yearReport, lengthReport)` pair beside every value, rejects annual rows from the quarterly pipeline, and keys each fact by:

```text
symbol + fiscal_year + fiscal_quarter + metric
```

Regression tests deliberately shuffle source rows and verify that every value remains attached to its original period.

### Metric-level data quality

For regular companies, the quarterly VCI mapping covers 11 canonical metrics across three statements:

```text
Income Statement: revenue, gross profit, operating profit, net profit
Balance Sheet:    cash, total assets, total liabilities, equity
Cash Flow:        operating, investing, and financing cash flow
```

Quality conditions are stored as data rather than hidden in logs. Implemented checks include missing-period detection, cross-source conflicts, quarterly/annual separation, natural-key uniqueness through warehouse constraints, and the balance-sheet identity.

### Replayability and provenance

Provider responses are saved before downstream use. Canonical records retain `source`, `source_reference`, and `ingested_at`, while raw CafeF snapshots include the request period, source URL, acquisition time, and SHA-256 digest. Parser fixes can therefore be replayed without silently losing the original evidence.

### Official-report fallback

The FPT 2024Q2 path demonstrates the intended fallback:

```text
Structured-source gap or conflict
              |
              v
       Official financial PDF
              |
              v
     Docling table extraction
              |
              v
   Strict structured normalization
              |
              v
        Source reconciliation
```

The extractor preserves raw labels, statement codes, notes, units, reporting columns, extraction method, and timestamp. It fails explicitly when no table clears the confidence threshold or when the best candidate is ambiguous.

### Version-aware financial facts — in progress

Financial statements can be revised after their first publication, and reviewed filings can reclassify line items. The current warehouse keeps one current fact per natural key; immutable fact versions and a separate trusted-current view have not been implemented yet.

The intended model is:

```text
Raw sources -> versioned canonical facts -> trusted current view -> analytical marts
```

## Audited Repository Snapshot

The canonical artifacts in the audited local workspace currently contain:

| Scope | Coverage |
| --- | --- |
| Companies | FPT, MWG, VNM, HPG, VCB |
| Quarterly artifacts | 1,971 canonical metric records |
| Quarterly period range | 2016Q1–2026Q2 |
| Annual artifacts | 509 canonical metric records |
| Annual period range | 2016–2025 |
| Automated tests | 35 passing |

FPT, MWG, HPG, and VNM expose the full 11-metric regular-company quarterly mapping in the current artifacts. VCB uses a bank-specific taxonomy and currently exposes a smaller quarterly metric set; broader bank and securities-company taxonomies remain work in progress.

## Data Pipeline

```text
Provider request
      |
      v
Raw snapshot + metadata
      |
      v
Provider-aware parser
      |
      v
Canonical contract
      |
      v
Reconciliation + quality checks
      |
      +------------------+
      v                  v
Canonical JSONL       PostgreSQL
                         |
                         v
                 data_quality_issues
```

Quarterly and annual facts have deliberately different contracts and tables:

- Quarterly grain: `symbol + fiscal_year + fiscal_quarter + metric`
- Annual grain: `symbol + fiscal_year + statement_type + metric`

## Tech Stack

| Area | Implemented |
| --- | --- |
| Data engineering | Python, Pandas, Requests |
| Storage | PostgreSQL, JSON Lines, local raw snapshots |
| Financial sources | CafeF, VCI/Vietcap through Vnstock, official filings |
| Document intelligence | Docling-based table extraction |
| Quality | pytest, reconciliation, completeness checks, accounting invariants |
| Local infrastructure | Docker Compose |

Planned or being explored: dbt, Airflow, LangGraph, a vector database, Redis, Kafka, and Flink. They are not represented here as implemented dependencies.

## Current Status

**Implemented**

- [x] Configurable five-company universe
- [x] Replayable quarterly and annual financial ingestion
- [x] Period-safe VCI normalization
- [x] Income Statement, Balance Sheet, and Cash Flow normalization
- [x] Multi-source reconciliation and official-report fallback
- [x] Completeness and balance-sheet identity checks
- [x] Idempotent PostgreSQL loading
- [x] Initial Docling-based Income Statement extraction
- [x] Unit and integration-style tests for the current ingestion slice

**In progress**

- [ ] Version-aware canonical financial facts
- [ ] Broader bank-specific and securities-company taxonomies
- [ ] Generalized official-document acquisition and parsing

**Planned**

- [ ] dbt analytical marts and deterministic derived metrics
- [ ] Read-only SQL Agent
- [ ] Financial-document chunking, retrieval, and cited RAG answers
- [ ] SQL + RAG routing with LangGraph
- [ ] Market-data ingestion and realtime serving
- [ ] Airflow orchestration, CI/CD, and production deployment

## Repository Structure

```text
finsight_vn/              core contracts, ingestion, normalization, DQ, warehouse
scripts/                  quarterly, annual, and FPT backfill entry points
tests/                    ingestion, normalization, warehouse, and PDF tests
config/companies.yaml     configured company universe and annual date range
data/raw/                 replayable provider snapshots (git-ignored)
data/canonical/           canonical JSONL outputs (git-ignored)
data/extracted/           structured official-PDF extraction (git-ignored)
compose.yaml              local PostgreSQL service
doc/MASTER_SPEC.md        target architecture and phased engineering plan
```

## Getting Started

Requirements: Python 3.10+, Docker, and a Vnstock API key for the VCI-backed path.

### 1. Create the environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt "vnstock>=4.0.6"
```

### 2. Configure local secrets

Copy `.env.example` to `.env` and `.env.postgres`, then replace the placeholder password and add `VNSTOCK_API_KEY` to `.env`. These files are git-ignored; do not commit credentials.

### 3. Start PostgreSQL

```powershell
docker compose up -d postgres
```

The default example configuration exposes PostgreSQL on `localhost:5433`.

### 4. Run the quarterly backfill

```powershell
python -m scripts.backfill_quarterly `
  --symbols FPT MWG VNM HPG VCB `
  --start 2016Q1 `
  --end 2026Q2 `
  --official-fpt-json data\extracted\fpt_2024q2_income_statement_raw.json
```

### 5. Run the annual backfill

```powershell
python -m scripts.backfill_annual `
  --symbols FPT MWG VNM HPG VCB `
  --start-year 2016 `
  --end-year 2025
```

### 6. Run the tests

```powershell
python -m pytest -q
```

Provider availability and report publication dates change over time. Set the requested end period to the latest period you expect the upstream source to provide; missing periods are surfaced as quality issues rather than filled with zeroes.

## Engineering Decisions

- **Reliability before AI:** build a trustworthy historical foundation before adding an agent interface.
- **Missing is not zero:** unavailable periods remain explicit quality conditions.
- **Provider schemas stop at adapters:** downstream consumers use canonical names, not provider-specific fields.
- **Provenance is part of the record:** source and source reference travel with every canonical fact.
- **Deterministic calculations stay deterministic:** growth, margins, and ratios belong in SQL/dbt or application code, not in an LLM prompt.
- **Infrastructure must earn its place:** Kafka, Flink, and Redis remain optional until a measured realtime workload requires them.

## Roadmap

1. Finish version-aware financial facts and sector-specific taxonomies.
2. Add dbt staging, fact, and analytical-mart models with tests.
3. Expose the marts through a constrained, read-only SQL tool.
4. Generalize official-document parsing, chunking, retrieval, and citation evaluation.
5. Route structured, document, and hybrid questions through the FinSight Agent.
6. Add market data and realtime infrastructure only after the historical and AI paths are reliable.

The full phased design and acceptance criteria are documented in [`doc/MASTER_SPEC.md`](doc/MASTER_SPEC.md).
