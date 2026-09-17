with pivoted as (
    select
        symbol,
        fiscal_year,
        fiscal_quarter,
        max(value) filter (where metric = 'revenue') as revenue,
        max(value) filter (where metric = 'gross_profit') as gross_profit,
        max(value) filter (where metric = 'operating_profit') as operating_profit,
        max(value) filter (where metric = 'net_profit') as net_profit,
        max(value) filter (where metric = 'cash') as cash,
        max(value) filter (where metric = 'total_assets') as total_assets,
        max(value) filter (where metric = 'total_liabilities') as total_liabilities,
        max(value) filter (where metric = 'equity') as equity,
        max(value) filter (where metric = 'operating_cash_flow') as operating_cash_flow,
        max(value) filter (where metric = 'investing_cash_flow') as investing_cash_flow,
        max(value) filter (where metric = 'financing_cash_flow') as financing_cash_flow
    from {{ ref('stg_financial_statement') }}
    group by symbol, fiscal_year, fiscal_quarter
),
with_prior_year as (
    select
        current_period.*,
        prior_year.revenue as revenue_prior_year,
        prior_year.net_profit as net_profit_prior_year
    from pivoted current_period
    left join pivoted prior_year
      on current_period.symbol = prior_year.symbol
     and current_period.fiscal_year = prior_year.fiscal_year + 1
     and current_period.fiscal_quarter = prior_year.fiscal_quarter
)
select
    symbol,
    fiscal_year::text || 'Q' || fiscal_quarter::text as period,
    fiscal_year,
    fiscal_quarter,
    revenue,
    gross_profit,
    operating_profit,
    net_profit,
    cash,
    total_assets,
    total_liabilities,
    equity,
    operating_cash_flow,
    investing_cash_flow,
    financing_cash_flow,
    gross_profit / nullif(revenue, 0) as gross_margin,
    net_profit / nullif(revenue, 0) as net_margin,
    (revenue - revenue_prior_year) / nullif(abs(revenue_prior_year), 0) as revenue_yoy_growth,
    (net_profit - net_profit_prior_year) / nullif(abs(net_profit_prior_year), 0) as net_profit_yoy_growth
from with_prior_year
