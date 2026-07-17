with source as (
    select * from {{ source('raw', 'feedback') }}
)

select
    feedback_id,
    submitted_at,
    feedback_type,
    status,
    launch_id
from source
