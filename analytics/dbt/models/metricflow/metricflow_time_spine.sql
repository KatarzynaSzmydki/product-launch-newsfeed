-- Daily date spine MetricFlow requires for any time-based query (grouping by
-- metric_time, quarter/year roll-ups, gap filling). Range brackets the real
-- launch history with headroom; regenerable, so a wide window costs nothing.
{{ config(materialized='table') }}
select cast(ts as date) as date_day
from (
    select unnest(
        generate_series(timestamp '2020-01-01', timestamp '2027-12-31', interval 1 day)
    ) as ts
)
