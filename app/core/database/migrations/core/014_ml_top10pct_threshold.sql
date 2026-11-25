-- T-4b: add top_10pct_per_period threshold setting.
-- Also records the missing audit entry for migration 013's bulk delete.

-- Extend threshold_setting constraint
ALTER TABLE ml_prediction DROP CONSTRAINT IF EXISTS ml_prediction_threshold_setting_check;
ALTER TABLE ml_prediction ADD CONSTRAINT ml_prediction_threshold_setting_check
    CHECK (threshold_setting IN ('operating_point_f2', 'r0_breach', 'top_10pct_per_period'));

-- Backfill audit entry for migration 013 bulk delete (count not captured at the time)
INSERT INTO audit_log(action, entity, entity_id, detail)
VALUES ('migration_013_delete', 'ml_prediction', '0',
        '{"note": "migration 013 deleted all T5 ml_prediction rows; count not captured (pre-audit)"}');
