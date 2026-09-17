select symbol, fiscal_year, fiscal_quarter, count(*) as copies
from {{ ref('mart_regular_company_quarterly') }}
group by symbol, fiscal_year, fiscal_quarter
having count(*) > 1
