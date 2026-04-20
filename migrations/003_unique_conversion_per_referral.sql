-- Guarantee at most one conversion event per referral at the database layer.
-- Prevents duplicate events under concurrent "first post" requests from the
-- same user (the app-side post count check is racy).

-- Delete any accidental duplicates that may exist from pre-constraint runs,
-- keeping the earliest row per referral.
DELETE FROM conversion_events a
USING conversion_events b
WHERE a.referral_id = b.referral_id
  AND a.created_at > b.created_at;

ALTER TABLE conversion_events
    ADD CONSTRAINT uq_conversion_events_referral UNIQUE (referral_id);
