with source as (
    select * from {{ source('raw', 'launches') }}
)

select
    launch_id,
    company_id,
    cast(launch_date as date) as launch_date,
    keyword,
    product_name,
    category,
    confidence_score,
    num_sources,
    source_type,
    summary,
    is_synthetic
from source
