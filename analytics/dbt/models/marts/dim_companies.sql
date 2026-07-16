select
    company_id,
    ticker,
    name,
    sector,
    industry,
    hq_country,
    market_cap_bucket
from {{ ref('stg_companies') }}
