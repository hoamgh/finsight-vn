select symbol, period, total_assets, total_liabilities, equity
from {{ ref('mart_regular_company_quarterly') }}
where total_assets is not null
  and total_liabilities is not null
  and equity is not null
  and abs(total_assets - total_liabilities - equity) > 1
