-- Tiered inviter rewards + badge catalogue + earned badges (M2M via user_badges)

CREATE TYPE badge_type AS ENUM ('REFERRAL', 'STREAK', 'ENGAGEMENT');

CREATE TABLE badges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    badge_type badge_type NOT NULL,
    badge_name VARCHAR(128) NOT NULL,
    description VARCHAR(512) NOT NULL,
    threshold INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_badges_type_threshold UNIQUE (badge_type, threshold)
);

CREATE TABLE user_badges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_id UUID NOT NULL REFERENCES badges(id) ON DELETE CASCADE,
    earned_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_badges_user_badge UNIQUE (user_id, badge_id)
);

CREATE INDEX idx_user_badges_user ON user_badges(user_id);
CREATE INDEX idx_badges_type ON badges(badge_type);

-- Referral milestone badges (STREAK / ENGAGEMENT rows can be added later with same schema)
INSERT INTO badges (badge_type, badge_name, description, threshold) VALUES
    ('STREAK', 'Rising Star', 'Posted 5 times in a row', 5),
    ('REFERRAL', 'Super Referrer', 'Converted 10 referrals', 10),
    ('REFERRAL', 'Flik Pro', 'Converted 20 referrals', 20),
    ('REFERRAL', 'Flik Master', 'Converted 30 referrals', 30)
ON CONFLICT (badge_type, threshold) DO NOTHING;
