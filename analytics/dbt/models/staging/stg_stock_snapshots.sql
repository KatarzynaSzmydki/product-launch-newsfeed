with source as (
    select * from {{ source('raw', 'stock_snapshots') }}
)

select
    snapshot_id,
    company_id,
    launch_id,
    cast(snapshot_date as date) as snapshot_date,
    price,
    change_1d,
    change_1y,
    week52_high,
    week52_low
from source
