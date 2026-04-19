# Flik Referral & Invite System

**Option A — Referral & Invite System**

Built with FastAPI, PostgreSQL, Redis, and RQ.

---

## Quick Start

```bash
git clone https://github.com/Prach1810/Referral-and-Invite-System.git
cd Referral-and-Invite-System 
cp .env
docker-compose up --build
```

API docs available at: http://localhost:8000/docs

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  FastAPI    │────▶│ PostgreSQL  │     │    Redis    │
│  (web)      │     │  (primary   │     │  - JWT BL   │
│             │────▶│   store)    │     │  - Rate Lim │
│             │────▶│             │     │  - LB Cache │
└─────────────┘     └─────────────┘     └─────────────┘
       │                                       │
       │ enqueue jobs                          │
       ▼                                       ▼
┌─────────────┐                       ┌─────────────┐
│  RQ Worker  │◀──────────────────────│  RQ Queue   │
│ (container) │     dequeue jobs      │  (Redis)    │
└─────────────┘                       └─────────────┘
```

**4 Docker containers:** `web`, `worker`, `db`, `redis`

---

## Key Design Decisions

### 1. Referral and Invitation are separate entities

Not all referrals originate from explicit invites. When a user shares their link passively (WhatsApp, Twitter), there is no invite record until someone actually signs up. Fabricating an invitation row for passive link signups would misrepresent the data.

- **Invitation** = explicit email invite with expiry and PENDING state
- **Referral** = relationship created at signup, regardless of origin
- `source = INVITE` if an invitation was found, `source = LINK` otherwise

### 2. Pending referrals are only trackable via explicit invites

Share sheet (WhatsApp, iMessage, etc.) is an OS-level feature — the backend never receives recipient information. "Pending" only has meaning when you sent a specific email and they haven't acted yet. "Total invites sent" in the dashboard counts all referral signups, which is honest and more useful.

### 3. Lazy expiration over cron jobs

Invitation expiry is checked at the moment of redemption or when the inviter fetches their list — not by a background scheduler. This is the same pattern Redis uses internally. No cron container needed, no clock drift issues, no distributed coordination.

```python
# at signup
if invitation.expired_at < datetime.utcnow():
    invitation.status = EXPIRED
    return 410

# at GET /invitations/me
UPDATE invitations SET status = EXPIRED
WHERE inviter_id = :user_id AND status = PENDING AND expired_at < NOW()
```

### 4. Invitation expiry derived from referral code type

```python
if referral_code.expires_at is None:          # DEFAULT code
    expired_at = invited_at + 30 days
else:                                          # PROMO code
    expired_at = min(invited_at + 30 days, referral_code.expires_at)
```

PROMO code campaign deadline always takes precedence.

### 5. Idempotent conversion via processed flag

The `conversion_events.processed` flag is flipped atomically inside the same DB transaction as the credit inserts. If the RQ worker crashes mid-job and retries, the second run sees `processed = True` and exits immediately. Same event can never reward twice.

```python
with session.begin():
    event = session.execute(...).with_for_update()
    if event.processed:
        return          # idempotency guard
    event.processed = True
    # ... insert credits, update balances
```

### 6. credits_balance is a denormalized cache

The `users.credits_balance` field is a running total for fast reads (used in dashboard, profile). The `credits_ledger` table is always the source of truth. Every credit change is an immutable append — never a mutation.

Negative credits are not implemented in this scope, but the ledger pattern is forward-compatible for a future "spend credits on generation" feature.

### 7. RQ over Kafka/SQS

RQ (Redis Queue) correctly demonstrates the decoupled async worker pattern at this scale. The conversion endpoint returns immediately, the reward logic runs in a separate worker container. In production, this graduates to SQS or Kafka with dead letter queues and better observability. RQ was chosen because Redis is already in the stack — no additional infrastructure.

### 8. Isolation Forest for anomaly detection

Anomaly detection on structured numerical data (event count, unique IPs, time variance) is not an appropriate use case for LLMs. Isolation Forest (scikit-learn) is an unsupervised algorithm specifically designed for this — it identifies outliers in feature space without needing labeled training data.

Rule-based fallback is used when sample size is too small for the model (< 10 data points). This mirrors how real fraud systems work: heuristics first, ML when data density justifies it.

### 9. Admin role for PROMO codes

PROMO codes are platform-level marketing campaigns. Individual users cannot create them. Only ADMIN role users can, and each admin owns only their own codes. `GET /referral-codes/me` returns codes owned by the authenticated user — admins see their promos, users see only their default code.

### 10. Leaderboard Redis caching

```
Current month → TTL 1 hour, invalidated on each new conversion
Past months   → TTL 30 days (data never changes)
```

Cache key: `leaderboard:{YYYY-MM}`

---

## API Reference

Full interactive docs at http://localhost:8000/docs

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /auth/register | No | Sign up, optionally with referral code |
| POST | /auth/login | No | Login, get JWT |
| POST | /auth/logout | Yes | Blacklist JWT in Redis |
| GET | /users/me | Yes | Get profile + default referral code |
| PUT | /users/me | Yes | Update name/phone |
| GET | /referral-codes/me | Yes | Get owned referral codes |
| POST | /invitations | Yes | Send explicit email invite |
| GET | /invitations/me | Yes | List sent invitations |
| GET | /referrals/me | Yes | Referral breakdown by source/status |
| POST | /posts | Yes | Create post (triggers conversion internally) |
| GET | /credits/me | Yes | Credits ledger history |
| GET | /dashboard/me | Yes | Summary stats |
| GET | /leaderboard | No | Monthly top referrers |
| POST | /admin/referral-codes | Admin | Create PROMO campaign code |
| GET | /admin/anomalies | Admin | Flagged suspicious accounts |

---

## Redis Usage

| Key pattern | Purpose | TTL |
|-------------|---------|-----|
| `blacklist:{jti}` | JWT logout blacklist | Remaining token lifetime |
| `rate_limit:signup:{ip}` | Signup rate limit per IP | 1 hour |
| `rate_limit:code_redemption:{ip}:{code}` | Redemption rate limit | 1 hour |
| `leaderboard:{YYYY-MM}` | Cached leaderboard | 1hr (current), 30d (past) |

---

## Schema Overview

```
users
  └── referral_codes (owner_id)
  └── invitations (inviter_id)
  └── referrals (inviter_id, invitee_id)
  └── posts (author_id)
  └── credits_ledger (user_id)

referrals
  └── conversion_events (referral_id)

rate_limit_events (audit trail for anomaly detection)
```

---

## Fraud & Abuse Prevention

**Implemented:**
- Self-referral blocked at signup
- Rate limiting via Redis: 5 signups/IP/hour, 10 redemptions/code+IP/hour
- Persistent audit log in `rate_limit_events` for pattern analysis
- Anomaly detection: Isolation Forest on (event_count, time_variance) features with rule-based fallback

**Described (not fully implemented):**
- **Multi-account gaming:** Graph analysis on referral chains to detect star patterns (one account referring dozens of new accounts). Device fingerprinting via user-agent + browser fingerprint. IP subnet clustering — accounts from the same /24 subnet treated as related.
- **Credit farming:** Detect accounts that convert quickly (create post immediately after signup) with no organic usage pattern.

---

## What I Would Add With More Time

- Email provider integration (SendGrid/SES) for actual invite delivery
- Tiered rewards: bonus multiplier after 5 conversions, Flik Pro badge after 10
- Separate `PUT /auth/change-password` and `PUT /auth/change-email` flows with re-authentication
- Pre-generated referral code pool to handle high-concurrency signup bursts
- Pagination on `/invitations/me`, `/referrals/me`, `/credits/me`
- Credit expiration via scheduled task
- WebSocket or SSE for real-time conversion notifications
- Structured logging (JSON) + distributed tracing

---

## AI Tools Used

Claude (Anthropic) was used throughout:
- Architecture design and schema decisions (extensive back-and-forth reasoning)
- Identifying edge cases: lazy expiration pattern, idempotency via processed flag, leaderboard caching strategy
- Code generation for boilerplate (models, schemas, route handlers)
- All architectural decisions were reasoned through before code was written — Claude helped surface tradeoffs, not just generate code

---

## Running Tests

```bash
docker-compose exec web pytest tests/ -v
```

Unit tests cover: reward logic idempotency, rate limiting, fraud detection heuristics, JWT security, code generation, invitation expiry logic.