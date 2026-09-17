select
    upper(symbol) as symbol,
    fiscal_year,
    fiscal_quarter,
    metric,
    value::numeric(30, 4) as value,
    unit,
    currency,
    source,
    source_reference,
    ingested_at
from {{ source('finsight', 'fct_financial_statement') }}
where symbol in ('FPT', 'HPG', 'MWG', 'VNM')
  and fiscal_year >= 2020
  and fiscal_quarter between 1 and 4
