select symbol, fiscal_year, fiscal_quarter, metric, count(*) as copies
from {{ ref('stg_financial_statement') }}
group by symbol, fiscal_year, fiscal_quarter, metric
having count(*) > 1
