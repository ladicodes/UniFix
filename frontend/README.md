# UniFix frontend

Next.js 16 (App Router), TypeScript, Tailwind CSS v4, TanStack Query, Motion, Freighter wallet API.

## Run

```bash
npm install
npm run dev        # http://localhost:3000
```

With no environment variables the app runs in **demo mode**: an in-browser backend (`src/lib/api/demo.ts`) stores data in `localStorage`, and every chain transaction is simulated and labelled as such. Use the demo accounts on `/sign-in` and the account menu to switch between customer, professional and admin while walking one booking end to end.

To use the FastAPI backend:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
# optional
NEXT_PUBLIC_HORIZON_URL=https://horizon-testnet.stellar.org
```

## Demo walkthrough

1. Sign in as **Adaeze** (customer). Open Messages and Tunde's chat. Accept the AC quotation.
2. On the booking, connect Freighter (or the demo wallet) and fund the escrow. The booking turns funded once confirmation lands.
3. Switch to **Tunde** (professional). Start the job, then submit photos, checklist and notes.
4. Switch back to Adaeze. Approve and release. The receipt appears, then leave a verified review.
5. Sign in as **UniFix Operations** to resolve the seeded dispute in `/admin`.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Landing page |
| `/sign-in`, `/sign-up` | Auth, customer and professional onboarding |
| `/home` | Overview: what needs you, money in escrow, recent messages |
| `/discover` | Search and filter professionals |
| `/pros/[id]` | Profile, verification, ratings breakdown, reviews |
| `/messages`, `/messages/[id]` | Real-time chat, quotations, voice call UI, reporting |
| `/bookings`, `/bookings/[id]` | Booking list; escrow funding, completion, approval, dispute, receipt, review |
| `/wallet` | Freighter connection, testnet balances, Friendbot, ownership signature |
| `/profile` | Account details, public profile editing for professionals, verification status, wallet |
| `/admin` | Dispute review and settlement |

## API contract (live mode)

`src/lib/api/live.ts` calls the routes from PRD section 10. Response bodies must match the types in `src/lib/types.ts` and `src/lib/api/contract.ts`. State-changing calls send an `Idempotency-Key` header and `Authorization: Bearer <token>`.

| Client call | Request |
| --- | --- |
| signIn / signUp / me | `POST /auth/login`, `POST /auth/register` → `{ access_token, user }`; `GET /auth/me` |
| updateMe / updateProfessional | `PATCH /auth/me { name, city }`, `PATCH /professionals/{id}` |
| listProfessionals | `GET /professionals?category&city&availability&minRating&verifiedOnly&sort&q` |
| getProfessional / listReviews | `GET /professionals/{id}`, `GET /professionals/{id}/reviews` |
| listConversations / getConversation | `GET /conversations`, `GET /conversations/{id}` (with messages and quotes) |
| openConversation | `POST /conversations { professional_id }` |
| sendMessage | `POST /conversations/{id}/messages { body, attachment? }` |
| real-time | `WS /ws/conversations/{id}?token=` (any message triggers a refetch) |
| createQuote / acceptQuote / rejectQuote | `POST /quotes`, `POST /quotes/{id}/accept`, `POST /quotes/{id}/reject` |
| listBookings / getBooking | `GET /bookings`, `GET /bookings/{id}` → `BookingBundle` |
| prepareEscrow | `POST /bookings/{id}/escrow { customer_wallet }` → `{ escrow, unsignedXdr }` |
| submitFunding | `POST /escrows/{id}/funding { signed_xdr }` |
| startJob / submitCompletion | `POST /bookings/{id}/start`, `POST /bookings/{id}/completion` |
| releaseEscrow | `POST /escrows/{id}/release` → `{ escrow, unsignedXdr? }`; then again with `{ signed_xdr }` |
| openDispute / resolveDispute | `POST /escrows/{id}/disputes`, `POST /disputes/{id}/resolve` |
| listDisputes | `GET /admin/disputes` |
| submitReview | `POST /bookings/{id}/reviews` |
| notifications | `GET /notifications`, `POST /notifications/read` |
| wallet | `POST /wallets/challenge { address }` → `{ message }`; `POST /wallets { address, message, signature }` |
| calls | `POST /calls/sessions { conversation_id }` |

The frontend never treats a signature as settlement. After submitting a transaction it polls `GET /bookings/{id}` while `escrow.reconciliation === "PENDING_CONFIRMATION"` and shows the state the backend reconciled from Stellar.

## Design

- Plain white ground. Indigo (`stellar`) is the one action colour; danfo yellow appears only on money that is held in escrow; green means released or verified; red means dispute or error.
- Tokens and rules live at the top of `src/app/globals.css`: Tailwind's type scale only, weights 400/600/700, radii 8/16/full, neutral two-layer shadows, secondary text at 6:1 contrast.
- Archivo variable font; the width axis carries hierarchy (`font-wide` for display, normal width for reading).
- The agreement ticket (`src/components/ticket.tsx`) follows a job from accepted quotation to paid, and shows the yellow band only while funds are held.
