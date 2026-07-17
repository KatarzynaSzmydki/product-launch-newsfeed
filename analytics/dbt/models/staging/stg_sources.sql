with source as (
    select * from {{ source('raw', 'sources') }}
)

select
    source_id,
    launch_id,
    outlet_name,
    url,
    cast(published_at as date) as published_at,
    is_wire
from source
