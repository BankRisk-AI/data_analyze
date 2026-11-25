-- T-4: replace matched_far/max_ur_0_9 threshold scheme with operating_point_f2 and r0_breach.
-- Clears stale predictions from the old scheme before tightening the constraint.

DELETE FROM ml_prediction;

ALTER TABLE ml_prediction DROP CONSTRAINT IF EXISTS ml_prediction_threshold_setting_check;
ALTER TABLE ml_prediction ADD CONSTRAINT ml_prediction_threshold_setting_check
    CHECK (threshold_setting IN ('operating_point_f2', 'r0_breach'));
