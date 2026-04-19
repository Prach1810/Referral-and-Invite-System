-- migrations/001_initial.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE user_role AS ENUM ('USER', 'ADMIN');
CREATE TYPE campaign_type AS ENUM ('DEFAULT', 'PROMO');
CREATE TYPE invitation_status AS ENUM ('PENDING', 'SIGNED_UP', 'EXPIRED');
CREATE TYPE referral_status AS ENUM ('CONVERTED', 'NOT_CONVERTED');
CREATE TYPE referral_source AS ENUM ('INVITE', 'LINK');
CREATE TYPE signup_source AS ENUM ('WEB', 'MOBILE', 'API');
CREATE TYPE credit_reason AS ENUM ('REFERRAL_INVITER', 'REFERRAL_INVITEE', 'BONUS_TIER', 'ADJUSTMENT');
CREATE TYPE rate_limit_action AS ENUM ('SIGNUP', 'CODE_REDEMPTION');

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR UNIQUE NOT NULL,
    first_name VARCHAR NOT NULL,
    last_name VARCHAR NOT NULL,
    phone VARCHAR,
    password_hash VARCHAR NOT NULL,
    role user_role NOT NULL DEFAULT 'USER',
    referred_by UUID REFERENCES users(id),
    credits_balance INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE referral_codes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code VARCHAR UNIQUE NOT NULL,
    owner_id UUID NOT NULL REFERENCES users(id),
    expires_at TIMESTAMP,
    max_uses INTEGER,
    uses_count INTEGER NOT NULL DEFAULT 0,
    campaign_type campaign_type NOT NULL DEFAULT 'DEFAULT',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE invitations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    referral_code_id UUID NOT NULL REFERENCES referral_codes(id),
    inviter_id UUID NOT NULL REFERENCES users(id),
    invitee_email VARCHAR NOT NULL,
    invitee_id UUID REFERENCES users(id),
    status invitation_status NOT NULL DEFAULT 'PENDING',
    signup_source signup_source,
    expired_at TIMESTAMP NOT NULL,
    invited_at TIMESTAMP NOT NULL DEFAULT NOW(),
    signed_up_at TIMESTAMP
);

CREATE TABLE referrals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    referral_code_id UUID NOT NULL REFERENCES referral_codes(id),
    inviter_id UUID NOT NULL REFERENCES users(id),
    invitee_id UUID NOT NULL UNIQUE REFERENCES users(id),
    invitation_id UUID REFERENCES invitations(id),
    source referral_source NOT NULL,
    status referral_status NOT NULL DEFAULT 'NOT_CONVERTED',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE conversion_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    referral_id UUID NOT NULL REFERENCES referrals(id),
    invitee_id UUID NOT NULL REFERENCES users(id),
    event_type VARCHAR NOT NULL DEFAULT 'FIRST_CONTENT_GENERATED',
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE credits_ledger (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    amount INTEGER NOT NULL,
    reason credit_reason NOT NULL,
    reference_id UUID NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE rate_limit_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    ip_address VARCHAR NOT NULL,
    action rate_limit_action NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    author_id UUID NOT NULL REFERENCES users(id),
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_referral_codes_owner ON referral_codes(owner_id);
CREATE INDEX idx_invitations_inviter ON invitations(inviter_id);
CREATE INDEX idx_invitations_invitee_email ON invitations(invitee_email);
CREATE INDEX idx_referrals_inviter ON referrals(inviter_id);
CREATE INDEX idx_referrals_invitee ON referrals(invitee_id);
CREATE INDEX idx_conversion_events_referral ON conversion_events(referral_id);
CREATE INDEX idx_credits_ledger_user ON credits_ledger(user_id);
CREATE INDEX idx_rate_limit_events_ip ON rate_limit_events(ip_address);
CREATE INDEX idx_posts_author ON posts(author_id);