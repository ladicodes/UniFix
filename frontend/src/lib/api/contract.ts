import type {
  AppNotification,
  Booking,
  BookingBundle,
  CategoryId,
  CompletionEvidence,
  Conversation,
  Currency,
  Dispute,
  DisputeOutcome,
  Escrow,
  Message,
  Milestone,
  Professional,
  ProfessionalFilters,
  Quote,
  RatingBreakdown,
  Review,
  Role,
  User,
} from "../types";

export interface SignUpInput {
  name: string;
  email: string;
  password: string;
  role: Exclude<Role, "admin">;
  city: string;
  country: "NG" | "GH";
  professional?: {
    category: CategoryId;
    headline: string;
    bio: string;
    area: string;
    coverage: string[];
    yearsExperience: number;
    startingPrice: number;
    availability: Professional["availability"];
    skills: string[];
  };
}

export interface ConversationSummary {
  conversation: Conversation;
  professional: Professional;
  customer: User;
  unread: boolean;
}

export interface ConversationDetail extends ConversationSummary {
  messages: Message[];
  quotes: Quote[];
}

export interface QuoteInput {
  conversationId: string;
  title: string;
  description: string;
  labour: number;
  materials: number;
  currency: Currency;
  completionDate: string;
  paymentTerms: string;
  milestones: Milestone[];
}

export interface PreparedEscrow {
  escrow: Escrow;
  /** Unsigned Soroban transaction XDR from the backend. Absent in demo mode. */
  unsignedXdr?: string;
}

export interface DisputeBundle {
  dispute: Dispute;
  bundle: BookingBundle;
}

export type ChangeListener = () => void;

export interface UniFixApi {
  mode: "demo" | "live";
  signIn(email: string, password: string): Promise<User>;
  signUp(input: SignUpInput): Promise<User>;
  signOut(): Promise<void>;
  me(): Promise<User | null>;
  updateMe(input: { name: string; city: string }): Promise<User>;
  updateProfessional(
    id: string,
    input: Pick<Professional, "headline" | "bio" | "availability" | "startingPrice" | "skills" | "coverage" | "area">,
  ): Promise<Professional>;

  listProfessionals(filters: ProfessionalFilters): Promise<Professional[]>;
  getProfessional(id: string): Promise<Professional>;
  listReviews(professionalId: string): Promise<Review[]>;

  listConversations(): Promise<ConversationSummary[]>;
  getConversation(id: string): Promise<ConversationDetail>;
  openConversation(professionalId: string): Promise<Conversation>;
  sendMessage(conversationId: string, input: { body: string; attachment?: Message["attachment"] }): Promise<Message>;

  createQuote(input: QuoteInput): Promise<Quote>;
  acceptQuote(quoteId: string): Promise<Booking>;
  rejectQuote(quoteId: string): Promise<Quote>;

  listBookings(): Promise<BookingBundle[]>;
  getBooking(id: string): Promise<BookingBundle>;
  prepareEscrow(bookingId: string, customerWallet: string): Promise<PreparedEscrow>;
  submitFunding(escrowId: string, signedXdr?: string): Promise<Escrow>;
  getEscrow(id: string): Promise<Escrow>;
  startJob(bookingId: string): Promise<Booking>;
  submitCompletion(bookingId: string, evidence: Omit<CompletionEvidence, "submittedAt" | "hash">): Promise<Booking>;
  releaseEscrow(escrowId: string, signedXdr?: string): Promise<PreparedEscrow>;
  openDispute(escrowId: string, input: { reason: string; details: string }): Promise<Dispute>;
  resolveDispute(
    disputeId: string,
    input: { outcome: DisputeOutcome; splitPercentToProfessional?: number; note: string },
  ): Promise<Dispute>;
  listDisputes(): Promise<DisputeBundle[]>;
  submitReview(bookingId: string, input: { ratings: RatingBreakdown; comment: string }): Promise<Review>;

  listNotifications(): Promise<AppNotification[]>;
  markNotificationsRead(): Promise<void>;

  walletChallenge(address: string): Promise<{ message: string }>;
  registerWallet(address: string, message: string, signature: string): Promise<User>;

  startCall(conversationId: string): Promise<{ sessionId: string }>;

  /** Real-time change feed. Demo: in-memory events. Live: conversation WebSocket. */
  subscribe(channel: string, listener: ChangeListener): () => void;
}
