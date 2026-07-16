-- Grain: one stock snapshot per launch, captured at brief time.
select
    snapshot_id,
    company_id,
    launch_id,
    snapshot_date,
    price,
    change_1d,
    change_1y,
    week52_high,
    week52_low
from {{ ref('stg_stock_snapshots') }}
