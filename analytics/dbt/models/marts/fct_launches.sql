-- Grain: one row per confirmed launch. Foreign key to dim_companies.
select
    launch_id,
    company_id,
    launch_date,
    keyword,
    product_name,
    category,
    confidence_score,
    num_sources,
    source_type,
    summary,
    is_synthetic
from {{ ref('stg_launches') }}
