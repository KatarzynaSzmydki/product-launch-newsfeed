with source as (
    select * from {{ source('raw', 'companies') }}
)

select
    company_id,
    ticker,
    name,
    sector,
    industry,
    hq_country,
    market_cap_bucket
from source
