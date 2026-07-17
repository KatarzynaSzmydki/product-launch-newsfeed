-- Bridge: one row per corroborating outlet hit, linking sources to fct_launches.
select
    source_id,
    launch_id,
    outlet_name,
    url,
    published_at,
    is_wire
from {{ ref('stg_sources') }}
