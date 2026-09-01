-- Governance UDFs: column mask + row filter.
-- {catalog} / {schema} are substituted by governance/apply.sh at apply time.
-- {member_fn} is the group-membership function (is_account_group_member or is_member),
-- resolved by apply.sh depending on whether account groups are available.

-- Column mask for guest-origin / booking-intermediary identifiers (country, agent,
-- company). Everyone except hotel_engineer sees a redacted value.
CREATE OR REPLACE FUNCTION {catalog}.{schema}.mask_pii(v STRING)
RETURNS STRING
COMMENT 'Redacts PII-ish identifiers (country/agent/company) for non-engineer principals.'
RETURN CASE WHEN {member_fn}('hotel_engineer') THEN v ELSE '***' END;

-- Row filter over the hotel dimension. Engineers and analysts (corporate) see every
-- property; each property manager group is scoped to its own hotel.
CREATE OR REPLACE FUNCTION {catalog}.{schema}.hotel_row_filter(h STRING)
RETURNS BOOLEAN
COMMENT 'Per-property row-level security on the hotel column.'
RETURN
       {member_fn}('hotel_engineer')
    OR {member_fn}('hotel_analyst')
    OR ({member_fn}('hotel_mgr_city')   AND h = 'City Hotel')
    OR ({member_fn}('hotel_mgr_resort') AND h = 'Resort Hotel');
