# FinSight VN

FinSight VN is a financial intelligence data platform for Vietnamese listed companies.

## Goal

Build a data pipeline that collects, cleans, standardizes, and serves financial data for analytics and an AI research agent.

## Initial Scope

- Companies: FPT first, then expand to more listed companies
- Financial statements: quarterly
- Market data: daily OHLCV
- Official reports: used later for RAG
- Processing: Python + Pandas
- Warehouse: PostgreSQL + dbt
- Orchestration: Airflow
- AI: SQL tool + RAG + calculator

## Project Status

Current milestone: Financial data ingestion

## Architecture

```text
Structured Financial Data
        ↓
Python Ingestion
        ↓
Bronze
        ↓
Cleaning & Standardization
        ↓
Silver
        ↓
dbt
        ↓
PostgreSQL / Gold
        ↓
Research Agent
```

## Roadmap

- [ ] Ingest FPT financial statements
- [ ] Build Bronze layer
- [ ] Normalize financial metrics
- [ ] Build Silver layer
- [ ] Add dbt models
- [ ] Add PostgreSQL warehouse
- [ ] Add Airflow
- [ ] Add RAG
- [ ] Add Research Agent
