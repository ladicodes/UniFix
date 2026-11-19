// Domain types for UniFix. These mirror the PRD entities and are the shape the
// frontend expects from the FastAPI backend (see README "API contract").

export type Role = "customer" | "professional" | "admin";
export type Country = "NG" | "GH";
export type Currency = "NGN" | "GHS";

export type CategoryId =
  | "electrician"
  | "plumber"
  | "ac-technician"
  | "mechanic"
  | "cleaner"
  | "carpenter"
  | "painter"
  | "generator";

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  city: string;
  country: Country;
  professionalId?: string;
  walletAddress?: string;
  walletVerified?: boolean;
}

export type Availability = "now" | "today" | "this-week" | "unavailable";

export interface RatingBreakdown {
  quality: number;
  punctuality: number;
  communication: number;
  professionalism: number;
  value: number;
}

export type RatingKey = keyof RatingBreakdown;

export interface PortfolioItem {
  id: string;
  caption: string;
  tone: "ink" | "danfo" | "lagoon" | "clay" | "stellar";
}

export interface Professional {
  id: string;
  userId: string;
  name: string;
  category: CategoryId;
  headline: string;
  bio: string;
  city: string;
  area: string;
  country: Country;
  distanceKm: number;
  coverage: string[];
  rating: number;
  reviewCount: number;
  completedJobs: number;
  yearsExperience: number;
  verification: { identity: boolean; trade: boolean; phone: boolean };
  availability: Availability;
  responseMinutes: number;
  startingPrice: number;
  currency: Currency;
  skills: string[];
  languages: string[];
  portfolio: PortfolioItem[];
  ratingBreakdown: RatingBreakdown;
  joinedAt: string;
  /** True while the professional has a job in progress. Derived, read-only. */
  onJob?: boolean;
}

export interface Review {
  id: string;
  bookingId: string;
  professionalId: string;
  customerId: string;
  customerName: string;
  jobTitle: string;
  ratings: RatingBreakdown;
  comment: string;
  createdAt: string;
  response?: { body: string; createdAt: string };
}

export interface Conversation {
  id: string;
  customerId: string;
  professionalId: string;
  bookingId?: string;
  lastMessageAt: string;
  lastMessagePreview: string;
  unreadFor: string[];
}

export type MessageKind = "text" | "image" | "quote" | "system";

export interface Message {
  id: string;
  conversationId: string;
  senderId: string;
  kind: MessageKind;
  body: string;
  quoteId?: string;
  attachment?: { name: string; dataUrl: string };
  createdAt: string;
  readAt?: string;
}

export type QuoteStatus = "PENDING" | "ACCEPTED" | "REJECTED" | "SUPERSEDED";

export interface Milestone {
  title: string;
  percent: number;
}

export interface Quote {
  id: string;
  conversationId: string;
  professionalId: string;
  customerId: string;
  version: number;
  status: QuoteStatus;
  title: string;
  description: string;
  labour: number;
  materials: number;
  total: number;
  currency: Currency;
  completionDate: string;
  paymentTerms: string;
  milestones: Milestone[];
  createdAt: string;
  acceptedAt?: string;
  /** Hash of the accepted, immutable agreement. Set by backend on accept. */
  agreementHash?: string;
}

export type BookingStatus =
  | "PENDING_PAYMENT"
  | "FUNDED"
  | "IN_PROGRESS"
  | "COMPLETION_SUBMITTED"
  | "COMPLETED"
  | "DISPUTED"
  | "CANCELLED";

export type EscrowState = "CREATED" | "FUNDED" | "RELEASED" | "REFUNDED" | "DISPUTED";

export type Reconciliation =
  | "AWAITING_SIGNATURE"
  | "PENDING_CONFIRMATION"
  | "CONFIRMED"
  | "FAILED";

export interface TimelineEvent {
  at: string;
  label: string;
  actor: "customer" | "professional" | "system" | "chain" | "admin";
}

export interface CompletionEvidence {
  notes: string;
  checklist: { label: string; done: boolean }[];
  photos: { id: string; name: string; dataUrl?: string }[];
  submittedAt: string;
  hash: string;
}

export interface Booking {
  id: string;
  quoteId: string;
  conversationId: string;
  customerId: string;
  professionalId: string;
  title: string;
  address: string;
  status: BookingStatus;
  createdAt: string;
  escrowId?: string;
  completion?: CompletionEvidence;
  disputeId?: string;
  reviewId?: string;
  timeline: TimelineEvent[];
}

export interface EscrowTransaction {
  kind: "FUND" | "RELEASE" | "REFUND";
  hash: string;
  ledger?: number;
  at: string;
  status: "PENDING" | "CONFIRMED" | "FAILED";
  simulated?: boolean;
}

export interface Escrow {
  id: string;
  bookingId: string;
  contractId: string;
  state: EscrowState;
  asset: string;
  assetIssuer?: string;
  amount: number;
  localAmount: number;
  currency: Currency;
  rate: number;
  networkFee: number;
  customerWallet?: string;
  professionalWallet?: string;
  reconciliation: Reconciliation;
  transactions: EscrowTransaction[];
  createdAt: string;
}

export type DisputeStatus = "OPEN" | "UNDER_REVIEW" | "RESOLVED" | "CLOSED";
export type DisputeOutcome = "RELEASE" | "REFUND" | "SPLIT";

export interface Dispute {
  id: string;
  bookingId: string;
  escrowId: string;
  openedBy: string;
  reason: string;
  details: string;
  status: DisputeStatus;
  openedAt: string;
  outcome?: DisputeOutcome;
  splitPercentToProfessional?: number;
  resolutionNote?: string;
  resolvedAt?: string;
}

export interface AppNotification {
  id: string;
  userId: string;
  title: string;
  body: string;
  href: string;
  at: string;
  read: boolean;
}

export interface BookingBundle {
  booking: Booking;
  quote: Quote;
  escrow?: Escrow;
  professional: Professional;
  customer: User;
  dispute?: Dispute;
  review?: Review;
}

export interface ProfessionalFilters {
  q?: string;
  category?: CategoryId | "all";
  city?: string;
  availability?: "any" | "now" | "today";
  minRating?: number;
  verifiedOnly?: boolean;
  sort?: "best" | "nearest" | "most-jobs" | "experience";
}
