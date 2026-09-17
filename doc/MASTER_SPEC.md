# FinSight VN — Master Engineering Specification

## 1. Project Mission

FinSight VN is a Financial Intelligence Platform for Vietnamese listed companies.

The platform combines:

1. Structured historical financial data.
2. Historical market data.
3. Financial documents and reports.
4. Near-real-time market data.
5. An AI research agent capable of using SQL, RAG, and realtime tools together.

The primary goal is not automated trading or price prediction.

The goal is to build a trustworthy financial research platform where answers can be traced back to validated structured data or source documents.

Core principle:

> Data reliability comes before AI capability.

Do not introduce AI, streaming infrastructure, distributed processing, or additional databases unless the current phase requires them.

---

# 2. Product Scope

## 2.1 Initial company universe

Development must begin with FPT as the first end-to-end vertical slice.

Only after FPT passes the Phase 1 acceptance criteria should ingestion expand to approximately 10 Vietnamese listed companies.

The company universe must be configurable and must not be hard-coded throughout the codebase.

Example:

```yaml
companies:
  - FPT
  - MWG
  - VNM
  - HPG
  - VCB
```

The final list may change.

---

## 2.2 Historical period

Target historical coverage:

```text
Financial statements:
2023Q1 → latest available quarter

Daily OHLCV:
2023-01-01 → present

Intraday:
maximum trustworthy history available from selected provider

Documents:
2023 → present
```

Historical intraday coverage does not need to match daily coverage.

Never fabricate unavailable historical intraday data.

---

# 3. Non-Goals

The following are explicitly outside the initial scope:

```text
price prediction
automated trading
buy/sell recommendations
portfolio optimization
high-frequency trading
order-book processing
full Vietnamese stock-market coverage
social-media sentiment
tick-level analytics unless justified later
```

Do not add these features unless the project specification is explicitly updated.

---

# 4. Engineering Principles

All implementation decisions must follow these principles.

## 4.1 Raw data must remain replayable

Raw provider responses should be retained whenever practical.

A parser or transformation bug must not require downloading the source again.

---

## 4.2 Missing is not zero

If a financial period is unavailable:

```text
missing ≠ 0
```

Never silently:

* replace missing financial data with zero;
* interpolate financial statements;
* fabricate market observations;
* ask an LLM to guess missing numbers.

Missing data must become an observable data-quality condition.

---

## 4.3 Provider schemas must not leak downstream

Every source must map into a canonical FinSight contract.

Downstream models must not depend directly on CafeF, SSI, DNSE, VCI, or another provider's naming conventions.

Architecture:

```text
Provider
   ↓
Provider Adapter
   ↓
Canonical Contract
   ↓
Downstream Platform
```

---

## 4.4 Provenance is mandatory

Important records must retain enough metadata to answer:

```text
Where did this value come from?
When was it collected?
Which provider supplied it?
Which document/page supplied it if extracted from a PDF?
```

---

## 4.5 Idempotency is mandatory

Running the same ingestion job twice must not create duplicate canonical records.

Backfill and retry behavior must be deterministic.

---

## 4.6 AI must not own deterministic calculations

Metrics such as:

```text
YoY growth
gross margin
net margin
ROE
ROA
debt-to-equity
moving averages
```

must be computed by SQL/dbt/application logic when possible.

Do not ask the LLM to calculate values that deterministic code can calculate.

---

## 4.7 Every phase must be independently testable

Do not build multiple large subsystems before validating the previous one.

Each phase has explicit exit criteria.

Do not proceed to the next phase while critical exit criteria remain broken.

---

# 5. Target Architecture

Long-term architecture:

```text
                           DATA SOURCES

       Financial Web/API     Market Sources      Financial PDFs
               │                   │                   │
               ▼                   ▼                   ▼
         Provider Adapter     Provider Adapter       Docling
               │                   │                   │
               ▼                   ▼             Parsed Document
             RAW DATA            RAW DATA          /          \
               │                   │              /            \
               ▼                   ▼             ▼              ▼
          Validation          Validation     Extraction     RAG chunks
               │                   │             │              │
               ▼                   ▼             │              ▼
          Normalization       Normalization      │          Vector DB
               │                   │             │              │
               └───────────┬───────┴─────────────┘              │
                           ▼                                    │
                       Warehouse                                │
                           │                                    │
                           ▼                                    │
                        SQL Tool                             RAG Tool
                           │                                    │
                           └──────────────┐    ┌────────────────┘
                                          ▼    ▼
                                      FinSight Agent
                                          ▲
                                          │
                                    Realtime Tool
                                          │
                                        Redis
                                          ▲
                                          │
                                 Realtime ingestion
```

Future streaming architecture:

```text
Market Feed
    ↓
Kafka
    ↓
Flink
   /   \
  ▼     ▼
Redis   Historical Sink
  │          │
  │          ▼
  │       Warehouse
  │
  ▼
Realtime Tool
```

Kafka and Flink are future upgrades, not Phase 1 dependencies.

---

# 6. Storage Responsibilities

The system must distinguish storage responsibilities.

## Raw/Object Storage

Purpose:

```text
replay
audit
reprocessing
source preservation
```

Examples:

```text
raw/financial/
raw/market/
raw/documents/
parsed/documents/
```

---

## Analytical Warehouse

Purpose:

```text
validated structured history
financial facts
market history
derived metrics
analytical marts
SQL Agent queries
```

Current project implementation may use PostgreSQL + dbt.

Do not migrate warehouse technology merely for architectural fashion.

A later migration to BigQuery may be evaluated separately.

---

## Redis

Purpose:

```text
latest market state
low-latency realtime lookup
```

Redis is not the historical warehouse.

---

## Vector Database

Purpose:

```text
semantic retrieval of financial documents
```

Embeddings are rebuildable artifacts.

Raw documents are durable source data.

---

# 7. Canonical Data Contracts

## 7.1 Financial record

Canonical financial data must conceptually contain:

```text
symbol
fiscal_year
fiscal_quarter
metric
value
unit
currency
source
source_reference
ingested_at
```

Potential canonical metrics include:

```text
revenue
gross_profit
operating_profit
net_profit

cash
total_assets
total_liabilities
equity

operating_cash_flow
investing_cash_flow
financing_cash_flow
```

Provider-specific labels must be mapped into these canonical names.

---

## 7.2 Daily market record

```text
symbol
trading_date
open
high
low
close
volume
source
ingested_at
```

Natural grain:

```text
symbol × trading_date
```

---

## 7.3 Intraday record

```text
symbol
event_time
interval
open
high
low
close
volume
source
ingested_at
```

Example interval:

```text
1m
```

Natural grain:

```text
symbol × event_time × interval
```

---

# 8. Phase 1 — Historical Data Foundation

## Objective

Create a trustworthy structured historical dataset before introducing AI.

Phase 1 must establish:

```text
source
→ raw
→ validation
→ normalization
→ warehouse
→ dbt
→ tested marts
```

---

## 8.1 Phase 1A — Source discovery

First implement provider probes.

Market candidates may include:

```text
SSI FastConnect
DNSE
Vnstock-supported providers
```

The probe must determine:

```text
provider availability
daily history coverage
intraday coverage
schema
pagination
rate limits if observable
failure behavior
```

Test FPT first.

Example output:

```text
Provider   Daily earliest   1m earliest   Status
SSI        ...              ...           PASS
DNSE       ...              ...           PASS
VCI        ...              ...           ...
```

Do not choose a provider based only on documentation.

Verify with actual requests.

---

## 8.2 Phase 1B — Financial ingestion

Implement FPT financial ingestion first.

Flow:

```text
CafeF / structured source
        ↓
Provider adapter
        ↓
Raw persistence
        ↓
Parse
        ↓
Canonical financial records
```

Do not build special downstream logic tied to CafeF.

CafeF is one provider, not the FinSight schema.

---

## 8.3 Phase 1C — Completeness detection

For every company/year, determine expected reporting periods.

Example:

```text
FPT 2024

Q1 ✓
Q2 ✗
Q3 ✓
Q4 ✓
```

Produce a data-quality issue:

```text
company = FPT
period = 2024Q2
dataset = financial_statement
issue_type = MISSING_PERIOD
source = cafef
status = OPEN
```

The known FPT 2024Q2 CafeF gap should be treated as an important test case.

---

## 8.4 Phase 1D — Data quality framework

Required validation categories:

### Schema

Required fields exist and have valid types.

### Uniqueness

Financial:

```text
symbol + period + metric
```

Market daily:

```text
symbol + trading_date
```

### Nullability

Critical identifiers must not be null.

### Accepted values

Examples:

```text
quarter ∈ {1,2,3,4}
interval ∈ supported intervals
```

### Business rules

Examples:

```text
high >= low
high >= open
high >= close

volume >= 0
```

### Completeness

Expected periods must be compared with actual periods.

### Freshness

Datasets should expose their latest available observation.

---

## 8.5 Phase 1E — Warehouse

Minimum conceptual warehouse:

```text
dim_company
dim_date

fct_financial_statement
fct_market_daily
fct_market_intraday

data_quality_issues
```

Market intraday may remain empty until a provider is selected.

Do not force fake data into it.

---

## 8.6 Phase 1F — dbt

Use dbt for transformations and analytical serving models.

Recommended layers:

```text
staging
    ↓
intermediate
    ↓
facts/dimensions
    ↓
marts
```

Example:

```text
stg_financial
      ↓
int_financial_normalized
      ↓
fct_financial_statement
      ↓
mart_company_quarterly
```

Tests must accompany models.

---

## 8.7 Phase 1G — Backfill

The ingestion system must support historical backfill without one-off scripts.

Conceptually:

```text
backfill(
    symbol,
    start,
    end
)
```

Requirements:

```text
retry-safe
idempotent
observable
provider-aware
```

---

## Phase 1 Exit Criteria

Phase 1 is complete when:

```text
[ ] FPT works end-to-end.
[ ] Company universe is configurable.
[ ] Raw financial data is replayable.
[ ] Raw market data is replayable.
[ ] Canonical contracts are enforced.
[ ] Daily OHLCV historical data is loaded.
[ ] Financial history is loaded.
[ ] Missing quarters are automatically detected.
[ ] FPT 2024Q2 is correctly represented as missing if unresolved.
[ ] Duplicate ingestion does not create duplicate canonical rows.
[ ] dbt models build successfully.
[ ] dbt/data-quality tests pass.
[ ] Provenance exists on canonical records.
[ ] Backfill can be rerun safely.
```

Only then expand from FPT to the full company universe.

---

# 9. Phase 2 — SQL Intelligence

## Objective

Expose trustworthy structured financial and market information through a controlled SQL tool.

---

## 9.1 Derived metrics

Build deterministic analytical metrics such as:

```text
revenue_growth_yoy
net_profit_growth_yoy
gross_margin
net_margin
ROA
ROE
debt_to_equity
```

These should live in dbt/SQL marts.

---

## 9.2 SQL Tool

The SQL Tool must answer structured questions such as:

```text
Doanh thu FPT Q2/2025 là bao nhiêu?

Lợi nhuận FPT tăng bao nhiêu YoY?

Biên lợi nhuận MWG thay đổi thế nào?

Giá FPT tăng bao nhiêu trong năm 2025?
```

---

## 9.3 Security

The SQL tool must operate using read-only credentials.

Block destructive statements:

```text
INSERT
UPDATE
DELETE
DROP
ALTER
CREATE
TRUNCATE
```

Allow analytical reads.

Implement:

```text
query timeout
row/result limit
validation
logging
```

---

## 9.4 SQL evaluation

Create a deterministic evaluation dataset.

Example:

```json
{
  "question": "Doanh thu FPT Q2/2025 là bao nhiêu?",
  "expected_metric": "revenue",
  "expected_period": "2025Q2",
  "expected_symbol": "FPT"
}
```

Evaluate:

```text
tool selection
argument correctness
query correctness
answer correctness
```

---

## Phase 2 Exit Criteria

```text
[ ] Financial marts exist.
[ ] Derived metrics are deterministic.
[ ] SQL Tool is read-only.
[ ] SQL Tool returns provenance/context.
[ ] SQL evaluation suite exists.
[ ] Core SQL questions pass evaluation.
```

---

# 10. Phase 3 — Document Intelligence

## Objective

Turn official financial PDFs into reusable structured document representations.

---

## 10.1 Document acquisition

Collect:

```text
annual reports
quarterly financial reports
management/business reports
important official disclosures
```

Prefer official company/investor-relations sources.

---

## 10.2 Shared Docling parser

Parse every PDF once.

Architecture:

```text
PDF
 ↓
Docling
 ↓
Canonical Parsed Document
       /            \
      ▼              ▼
Extraction         RAG
```

Do not independently parse the same document for SQL fallback and RAG.

---

## 10.3 Canonical document metadata

Retain:

```text
document_id
company
document_type
report_period
published_at
source
source_url
page
section
table metadata
parser_version
ingested_at
```

---

## 10.4 Structured fallback extraction

Structured extraction exists primarily to resolve missing structured financial periods.

Example:

```text
CafeF missing FPT 2024Q2
        ↓
Official PDF
        ↓
Docling
        ↓
Structured extraction
        ↓
Schema validation
        ↓
Reconciliation
        ↓
Warehouse
```

LLM output must pass a strict schema.

Unexpected fields must not silently enter the warehouse.

---

## Phase 3 Exit Criteria

```text
[ ] Documents are acquired reproducibly.
[ ] Raw PDFs are durable.
[ ] Docling parsing works.
[ ] Parsed output is reusable.
[ ] Provenance includes page/document.
[ ] Structured extraction uses strict schemas.
[ ] Missing-period fallback can be demonstrated.
```

---

# 11. Phase 4 — RAG

## Objective

Answer qualitative questions grounded in official documents.

Flow:

```text
Parsed document
      ↓
hierarchical/structure-aware chunking
      ↓
embedding
      ↓
Vector DB
      ↓
retrieval
      ↓
LLM
      ↓
answer + citation
```

---

## 11.1 RAG citations

Answers should expose:

```text
document
page
section when available
```

An answer without evidence should not be presented as strongly grounded.

---

## 11.2 RAG evaluation

Create gold questions.

Example:

```json
{
  "question": "Ban lãnh đạo FPT giải thích tăng trưởng năm 2025 như thế nào?",
  "expected_document": "FPT_AR_2025",
  "expected_pages": [74, 75]
}
```

Evaluate retrieval separately from generation.

Retrieval metrics may include:

```text
Hit@K
Recall@K
```

Generation evaluation should consider:

```text
answer correctness
groundedness
citation correctness
```

---

## Phase 4 Exit Criteria

```text
[ ] Documents are chunked reproducibly.
[ ] Embeddings are versioned.
[ ] Retrieval works.
[ ] Answers contain citations.
[ ] Retrieval evaluation exists.
[ ] Generation evaluation exists.
```

---

# 12. Phase 5 — SQL + RAG Agent

## Objective

Build the first FinSight Research Agent.

Available tools:

```text
SQL Tool
RAG Tool
```

The agent must decide which tools are required.

---

## Example routing

```text
"Doanh thu FPT Q2/2025?"
→ SQL
```

```text
"Ban lãnh đạo giải thích tăng trưởng như thế nào?"
→ RAG
```

```text
"Doanh thu FPT tăng bao nhiêu và ban lãnh đạo giải thích nguyên nhân gì?"
→ SQL + RAG
```

Hybrid tool use is a core capability.

---

## Agent evaluation

Test:

```text
routing correctness
tool argument correctness
multi-tool completeness
answer correctness
citation completeness
```

Do not judge the agent only through manual demos.

---

## Phase 5 Exit Criteria

```text
[ ] SQL routing works.
[ ] RAG routing works.
[ ] Hybrid questions work.
[ ] Agent evaluation exists.
[ ] Tool calls are traceable.
```

---

# 13. Phase 6 — Realtime Market Intelligence

## Objective

Add near-real-time market state without introducing Kafka/Flink prematurely.

Initial architecture:

```text
Market API
    ↓
Polling
    ↓
Normalization
   /       \
  ▼         ▼
Redis     Historical persistence
  │              │
  ▼              ▼
Realtime Tool  Warehouse
```

Target polling interval:

```text
approximately 1–5 minutes
```

depending on provider limitations.

---

## Redis responsibility

Redis should serve hot/latest state such as:

```text
latest_price
change_pct
current_volume
recent VWAP
latest update timestamp
```

Redis must not become the historical source of truth.

---

## Historical persistence

Realtime data should become historical data where useful.

Prefer meaningful grains such as:

```text
1-minute OHLCV
daily OHLCV
```

Raw tick retention is optional and must have a justified use case.

---

## Realtime Tool contract

Stable interface examples:

```text
get_latest_price(symbol)

get_market_snapshot(symbol)

get_intraday_volume(symbol)

get_top_movers()
```

The agent must not depend on the implementation behind these methods.

---

## Phase 6 Exit Criteria

```text
[ ] Market polling works reliably.
[ ] Latest state is available through Redis.
[ ] Freshness is exposed.
[ ] Historical observations are persisted.
[ ] Realtime Tool contract is stable.
[ ] Agent can combine realtime + SQL + RAG.
```

---

# 14. Phase 7 — Platform Engineering

Engineering quality is developed throughout all phases, but this phase makes the platform deployable and operational.

Required areas:

```text
Docker
CI/CD
deployment
secrets
IAM
logging
metrics
tracing
health checks
load testing
failure testing
runbooks
```

---

## 14.1 Testing pyramid

### Unit

Test deterministic functions.

Examples:

```text
period normalization
financial metric mapping
OHLCV validation
completeness detection
```

### Integration

Examples:

```text
provider → raw
warehouse loader → database
SQL Tool → warehouse
Docling → parsed document
RAG → vector database
Realtime Tool → Redis
```

### End-to-end

Example:

```text
question
→ agent
→ tool
→ data system
→ final answer
```

---

## 14.2 CI

Every pull request should eventually run:

```text
format/lint
type checking
unit tests
data-contract tests
dbt tests
selected integration tests
agent smoke tests
Docker build
```

Failed required checks should prevent release.

---

## 14.3 Deployment

Services should be containerized where appropriate.

Potential deployable components:

```text
Agent API
Realtime service
Document parser
Ingestion jobs
```

Do not containerize purely for appearance; use it where reproducibility/deployment benefits.

---

## 14.4 Health endpoints

Application services should expose:

```text
/health
/ready
```

`health` means the process is alive.

`ready` means required dependencies are available enough to serve traffic.

---

## 14.5 Observability

Capture:

```text
logs
metrics
traces
```

Useful agent fields:

```text
request_id
tool_calls
latency
status
error
token usage/cost
```

Useful data metrics:

```text
row_count
missing_period_count
duplicate_count
freshness
ingestion failures
```

---

## 14.6 Secrets and IAM

Never commit credentials.

Use least privilege.

Examples:

```text
SQL Agent → read-only warehouse access

Crawler → write access only to required raw path

Application → only required secrets
```

---

## Phase 7 Exit Criteria

```text
[ ] CI pipeline exists.
[ ] Services can be reproduced from clean environments.
[ ] Deployment is documented.
[ ] Secrets are externalized.
[ ] Logs are useful for debugging.
[ ] Critical metrics exist.
[ ] Agent/tool traces exist.
[ ] Basic load tests pass.
[ ] Failure scenarios are tested.
[ ] Runbooks exist.
```

---

# 15. Phase 8 — Streaming Upgrade

This phase is optional and must be justified by working realtime requirements.

Target architecture:

```text
Market Feed
    ↓
Kafka
    ↓
Flink
   /   \
  ▼     ▼
Redis   Historical Sink
```

Kafka responsibility:

```text
event transport
buffering
replay
consumer decoupling
```

Flink responsibility:

```text
window aggregation
stateful processing
event-time processing
late-event handling
stream calculations
```

Redis responsibility remains:

```text
latest serving state
```

Warehouse responsibility remains:

```text
historical analytics
```

---

## Potential Flink calculations

Only implement if useful:

```text
1m/5m OHLCV
5-minute VWAP
rolling volume
volume spike detection
price-change windows
```

Do not add Kafka/Flink merely to increase the technology count on the CV.

---

# 16. Error Handling Strategy

External operations should distinguish retryable and non-retryable failures.

Examples:

```text
HTTP 500
→ retry with bounded exponential backoff

HTTP 429
→ respect rate limit / backoff

HTTP 401
→ fail, do not repeatedly retry

schema validation failure
→ quarantine / DQ issue

missing source data
→ missing-data issue, not zero
```

Retries must be bounded.

---

# 17. Data Quality Issue Model

Conceptual schema:

```text
issue_id
company
period
dataset
issue_type
source
expected_value
actual_value
detected_at
resolved_at
status
```

Possible issue types:

```text
MISSING_PERIOD
DUPLICATE_RECORD
SCHEMA_MISMATCH
INVALID_VALUE
SOURCE_DISAGREEMENT
STALE_DATA
```

---

# 18. Reconciliation

When multiple sources provide equivalent data, reconciliation should be possible.

Example:

```text
stream-derived daily OHLCV
           ↕
provider official daily OHLCV
```

Differences above defined thresholds should become data-quality issues.

Do not silently choose values when material source disagreements exist.

---

# 19. Versioning

AI/document artifacts should retain versions where relevant:

```text
parser_version
schema_version
embedding_model
prompt_version
LLM_model
```

This is required for reproducible evaluation.

---

# 20. Repository Structure

Target structure:

```text
finsight-vn/

config/
    companies.yaml
    sources.yaml

contracts/
    financial.py
    market.py
    document.py

src/
    ingestion/
        financial/
        market/
        documents/

    normalization/

    data_quality/

    warehouse/

    tools/
        sql/
        rag/
        realtime/

    agent/

scripts/
    probe_market_sources.py
    backfill.py

dbt/
    models/
        staging/
        intermediate/
        marts/
    tests/

tests/
    unit/
    integration/
    e2e/
    evaluation/

docs/
    MASTER_SPEC.md
    ARCHITECTURE.md
    DATA_MODEL.md
    RUNBOOK.md

docker/

.github/
    workflows/
```

Do not create empty architecture folders far ahead of the current implementation unless they provide immediate organizational value.

---

# 21. Codex Working Rules

When implementing a task, Codex must:

1. Read this specification first.
2. Inspect the existing repository before modifying code.
3. Reuse working components where appropriate.
4. Do not rewrite unrelated working code.
5. Keep changes scoped to the requested phase/task.
6. Do not add technologies not required by the specification.
7. Do not silently change architectural decisions.
8. Add or update tests for changed behavior.
9. Preserve idempotency.
10. Preserve provenance.
11. Never convert missing financial data to zero.
12. Never fabricate data to make tests pass.
13. Never commit credentials or secrets.
14. Do not trigger expensive cloud jobs unless explicitly requested.
15. Do not perform production full-refreshes unless explicitly requested.
16. Do not push, merge, deploy, or mutate production resources unless explicitly requested.
17. Report assumptions and unresolved questions.
18. Report files changed.
19. Report tests executed and their results.
20. Report anything not tested.

---

# 22. Codex Task Workflow

For every implementation request:

```text
1. Inspect
2. Plan
3. Implement
4. Test
5. Review diff
6. Report
```

Before implementation, identify:

```text
current behavior
desired behavior
affected files
data contract impact
migration impact
test strategy
```

After implementation, report:

```text
Summary
Files changed
Tests run
Test results
Known limitations
Next recommended task
```

---

# 23. Architecture Decision Rule

When choosing technology, ask:

```text
What workload requires this?
What problem does it solve?
What simpler alternative exists?
What is the operational cost?
Can it be added later without redesign?
```

If a simpler technology satisfies current requirements, prefer it.

Example:

```text
10 companies + quarterly statements
```

does not justify distributed Spark processing by volume alone.

Similarly:

```text
1–5 minute market polling
```

does not automatically justify Kafka/Flink.

---

# 24. Final Product Definition

FinSight V1 is considered successful when a user can ask:

```text
"FPT hôm nay biến động thế nào,
kết quả kinh doanh quý gần nhất ra sao,
và ban lãnh đạo giải thích triển vọng như thế nào?"
```

and FinSight can:

```text
Realtime Tool
      ↓
current market state

SQL Tool
      ↓
validated financial history

RAG Tool
      ↓
official document evidence

        ↓

FinSight Agent
        ↓
grounded synthesized answer
        ↓
sources + freshness + citations
```

The system must know when information is unavailable.

A trustworthy:

```text
"Data unavailable for this period."
```

is preferable to a plausible but fabricated answer.

---

# 25. Implementation Order

Unless explicitly changed, follow this order:

```text
PHASE 1
Historical Data Foundation
        ↓
PHASE 2
SQL Intelligence
        ↓
PHASE 3
Document Intelligence
        ↓
PHASE 4
RAG
        ↓
PHASE 5
SQL + RAG Agent
        ↓
PHASE 6
Realtime Intelligence
        ↓
PHASE 7
Production Hardening
        ↓
PHASE 8
Kafka/Flink Streaming Upgrade
```

Testing, documentation, security, data quality, and observability are cross-cutting concerns and must be developed continuously rather than postponed entirely until Phase 7.
