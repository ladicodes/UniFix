# UniFix Backend — Frontend Integration Guide (Batch 1)

Audience: Victor (frontend).

This guide covers what is **implemented and tested** after Batch 1 (Issues #1, #2, #4, #3) and how to connect `frontend/` to it.

- Field-level detail: [API_CONTRACT.md](API_CONTRACT.md).
- Authoritative schema: the live OpenAPI at `/api/v1/openapi.json` (or `backend/openapi.json`).

## 1. Running against the real backend

```bash
cd backend && uv sync && cp .env.example .env        # set DATABASE_URL, TEST_DATABASE_URL, JWT_SECRET
uv run alembic upgrade head && uv run python -m app.cli seed
uv run uvicorn --factory app.main:app_factory --reload --port 8000
cd ../frontend && NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev
```

Keep `CORS_ORIGINS=http://localhost:3000` and `COOKIE_SECURE=false` locally. `localhost:3000` and `localhost:8000` are same-site, so the refresh cookie works.

## 2. Conventions you must follow

| Topic | Rule |
|---|---|
| Field names | **snake_case** everywhere. Unknown or camelCase fields are rejected with `422`, and camelCase query params are ignored |
| Enum values | `UPPER_SNAKE_CASE` (`CUSTOMER`, `THIS_WEEK`, `PENDING_PAYMENT`, `TEXT`) |
| Money | Fiat amounts are **integers in minor units** plus `currency` (`3500000` + `NGN` = ₦35,000.00). Never floats |
| Errors | `{detail, code, request_id, errors?}`. Show `detail`; branch on `code` |
| Pagination | JSON array plus `X-Total-Count` / `X-Next-Offset` headers; `limit` ≤ 100, `offset` |
| Not visible | Resources you may not see return **404**, the same as non-existent ones |
| Timestamps | RFC 3339 with `+00:00` |

## 3. Sessions (cookie + in-memory access token)

1. **Sign up / sign in:**
   - Call `POST /auth/register` or `POST /auth/login` with `credentials: "include"` and the header `X-CSRF-Protection: 1`.
   - The response body is `{access_token, token_type, expires_in, user}`. Keep `access_token` **in memory only**.
   - The browser stores the HttpOnly refresh cookie automatically. JavaScript cannot and should not read it.
2. **App load:** call `POST /auth/refresh` (same `credentials` and header) to restore the session. A `401` means signed out.
3. **Every API call:** send `Authorization: Bearer <access_token>`.
   - On `401`, refresh once (single-flight across tabs, e.g. `navigator.locks.request("unifix-refresh", …)`), then retry.
   - On `409 REFRESH_RACE`, wait about 300 ms and refresh again.
4. **Sign out:** `POST /auth/logout` (with `credentials` and the CSRF header).
5. **Other session routes:**
   - `GET /auth/sessions` lists the user's logins; `DELETE /auth/sessions/{id}` revokes one.
   - `POST /auth/logout-all` ends all sessions.
6. **Email links:**
   - Verification links open `${FRONTEND_BASE_URL}/verify-email?token=…`; your page posts `{token}` to `/auth/verify-email/confirm`.
   - Reset links open `/reset-password?token=…` and post to `/auth/password-reset/confirm`.

The four cookie routes (`register`, `login`, `refresh`, `logout`) reject requests without an allowed `Origin` or without `X-CSRF-Protection: 1` (`403 CSRF_REJECTED`).

## 4. Uploads

1. `POST /uploads` (multipart: `file`, `purpose`) returns a `FileRef` `{id, url, signed_url, …}`.
2. Send the `id` wherever a file is referenced: `avatar_file_id`, `image_file_id`, `file_ids`, `attachment_file_id`, `media_file_ids`.
3. To display a private file, use `signed_url` (valid 5 minutes). Public files (avatars, portfolio) use `url`.

The type is detected from the file's bytes, and images are re-encoded with EXIF/GPS stripped.

## 5. Discovery and profiles

- `GET /categories` and `GET /campuses`: load categories from the API instead of the hardcoded `CategoryId` union.
- `GET /professionals?q&category&campus&city&availability&min_rating&verified_only&sort&lat&lng&limit&offset`
  - `sort` is one of `BEST | NEAREST | MOST_JOBS | EXPERIENCE`.
  - `distance_km` may be `null`.
- `GET /professionals/{id}` is public.
- For a professional's own profile: `GET/POST /professionals/me`, `PATCH /professionals/{id}`, `/professionals/me/portfolio`, `/professionals/me/verifications`.
- **Professional sign-up:** send the `professional` object in `register`. The account and profile are created together, or neither is.

## 6. Conversations and real-time

1. `POST /conversations {professional_id}` (customers only) returns the thread (`201` new, `200` existing).
2. Send messages over REST: `POST /conversations/{id}/messages {body, attachment_file_id?, client_message_id?}`. Include a `client_message_id` (uuid) so retries never duplicate.
3. Real-time:
   - Call `POST /ws/tickets {conversation_id}`, then **immediately** open `ws(s)://…{ws_path}?ticket=<ticket>`.
   - A ticket lasts 30 s and works **once**. Get a new ticket for every reconnect.
   - Never put the access token in the URL.
4. On `MESSAGE_CREATED` either apply `data` or refetch. After any reconnect, fetch `GET /conversations/{id}/messages?after=<last id>`.
5. **Close codes:**
   - `4000` and `4401`: get a new ticket (refresh first if needed).
   - `4403` and `4404`: stop retrying.
   - `1013`: you were too slow; reconnect and catch up.
6. Read receipts: `POST /conversations/{id}/read {last_read_message_id}`, or send `{"type": "READ", …}` over the socket.
7. Calls:
   - `POST /calls/sessions {conversation_id}`, then exchange `CALL_OFFER` / `CALL_ANSWER` / `CALL_ICE` / `CALL_END` over the socket.
   - End with `POST /calls/sessions/{id}/end`.
   - Media is peer-to-peer. Only STUN is provided (no TURN).

## 7. Requests, quotes and bookings

| Step | Call |
|---|---|
| Customer posts a job | `POST /service-requests` |
| Professional's feed | `GET /service-requests/feed` |
| Professional responds (opens a conversation) | `POST /service-requests/{id}/respond {message}` |
| Professional quotes (verified email required) | `POST /quotes {conversation_id, title, description, labour_minor, materials_minor, currency, completion_date, …}` |
| Customer accepts | `POST /quotes/{id}/accept {service_address?}` with `Idempotency-Key` (one key per click, reused on retry) |
| Booking | `GET /bookings`, `GET /bookings/{id}` → `BookingBundle` with `allowed_actions` |
| Proof of terms | `GET /bookings/{id}/agreement` → `{agreement_json, agreement_hash}` (SHA-256 of the exact bytes) |
| Cancel before payment | `POST /bookings/{id}/cancel {reason}` |

Bookings stay in `PENDING_PAYMENT` until the Batch 2 Stellar escrow is funded. Render action buttons from `allowed_actions` (`CANCEL`, `START` in Batch 1).

## 8. Remaining incompatibilities with the current `frontend/` (commit `41f07f4`)

Every difference is listed in [API_CONTRACT.md §13](API_CONTRACT.md#13-frontend-integration-changes) with file:line references.

| Status | Items |
|---|---|
| Must change to work with Batch 1 | F1 base URL, F2 sessions, F3 idempotency keys, F4 categories, F5 campus, F6 portfolio, F7 `distance_km`, F8 uploads, F9 system messages, F10 `allowed_actions`, F11 statuses, F17 milestones, F18 email screens, F19 snake_case, F20 enum casing, F21 WebSocket tickets, F22 money fields |
| Batch 2 (not callable yet) | F12–F16, F23–F26: escrow, completion, release, refund, disputes, reviews, deadlines, demo-rate label |

Batch 1 behaviour that differs from what `live.ts` assumes today:

- `POST /conversations` is **customer-only**.
- `listProfessionals` must send `min_rating` / `verified_only`; `minRating` / `verifiedOnly` are ignored.
- `submitCompletion`, `prepareEscrow`, `submitFunding`, `releaseEscrow`, `openDispute`, `resolveDispute`, `listDisputes`, `submitReview`, notifications and wallets have **no backend routes yet** (Batch 2). Calling them returns `404`.
