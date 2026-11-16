import type {
  AppNotification,
  Booking,
  Conversation,
  Dispute,
  Escrow,
  Message,
  Professional,
  Quote,
  RatingBreakdown,
  Review,
  User,
} from "./types";
import { toUsdc, RATES } from "./format";

export interface DB {
  version: number;
  users: User[];
  professionals: Professional[];
  reviews: Review[];
  conversations: Conversation[];
  messages: Message[];
  quotes: Quote[];
  bookings: Booking[];
  escrows: Escrow[];
  disputes: Dispute[];
  notifications: AppNotification[];
}

export const DB_VERSION = 5;

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
const ahead = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString();

export const hex = (len = 64) =>
  Array.from({ length: len }, () => Math.floor(Math.random() * 16).toString(16)).join("");

const DEMO_CONTRACT = "CDHANDIESCROWTESTNETDEMO7QX4M2KJ5ZP6V3WRB2N8LYTFA4HGSU";

const rb = (q: number, p: number, c: number, pr: number, v: number): RatingBreakdown => ({
  quality: q,
  punctuality: p,
  communication: c,
  professionalism: pr,
  value: v,
});

export function createSeed(): DB {
  const users: User[] = [
    { id: "u-adaeze", name: "Adaeze Okafor", email: "adaeze@demo.handi", role: "customer", city: "Lekki, Lagos", country: "NG" },
    { id: "u-kofi", name: "Kofi Asante", email: "kofi@demo.handi", role: "customer", city: "East Legon, Accra", country: "GH" },
    { id: "u-funmi", name: "Funmilayo Adeyemi", email: "funmi@demo.handi", role: "customer", city: "Ikeja, Lagos", country: "NG" },
    { id: "u-tunde", name: "Tunde Bakare", email: "tunde@demo.handi", role: "professional", city: "Yaba, Lagos", country: "NG", professionalId: "p-tunde" },
    { id: "u-chioma", name: "Chioma Eze", email: "chioma@demo.handi", role: "professional", city: "Surulere, Lagos", country: "NG", professionalId: "p-chioma" },
    { id: "u-ops", name: "Handi Operations", email: "ops@demo.handi", role: "admin", city: "Lagos", country: "NG" },
  ];

  const pro = (p: Omit<Professional, "userId" | "rating"> & { userId?: string }): Professional => ({
    ...p,
    userId: p.userId ?? `u-${p.id}`,
    rating:
      Math.round(
        ((p.ratingBreakdown.quality +
          p.ratingBreakdown.punctuality +
          p.ratingBreakdown.communication +
          p.ratingBreakdown.professionalism +
          p.ratingBreakdown.value) /
          5) *
          10,
      ) / 10,
  });

  const professionals: Professional[] = [
    pro({
      id: "p-tunde",
      userId: "u-tunde",
      name: "Tunde Bakare",
      category: "ac-technician",
      headline: "Split and inverter AC repair, gas refill, installation",
      bio: "Eleven years fixing split units, inverter ACs and cold rooms across the mainland and Lekki. I diagnose before I quote, and I bring the gauges so you can see the pressure readings yourself.",
      city: "Lagos",
      area: "Yaba",
      country: "NG",
      distanceKm: 6.2,
      coverage: ["Yaba", "Surulere", "Ikoyi", "Lekki Phase 1", "Victoria Island"],
      reviewCount: 3,
      completedJobs: 214,
      yearsExperience: 11,
      verification: { identity: true, trade: true, phone: true },
      availability: "now",
      responseMinutes: 8,
      startingPrice: 15000,
      currency: "NGN",
      skills: ["Inverter AC", "R410A gas refill", "PCB repair", "Installation", "Cold room"],
      languages: ["English", "Yoruba", "Pidgin"],
      portfolio: [
        { id: "pf1", caption: "2HP inverter split, Lekki", tone: "stellar" },
        { id: "pf2", caption: "Compressor swap, Ikoyi office", tone: "ink" },
        { id: "pf3", caption: "Outdoor unit bracket rework", tone: "danfo" },
        { id: "pf4", caption: "Cold room servicing, Yaba", tone: "lagoon" },
      ],
      ratingBreakdown: rb(4.9, 4.7, 4.9, 4.8, 4.6),
      joinedAt: ago(60 * 24 * 410),
    }),
    pro({
      id: "p-chioma",
      userId: "u-chioma",
      name: "Chioma Eze",
      category: "electrician",
      headline: "House wiring, inverter and solar backup, fault tracing",
      bio: "COREN-registered electrician. Rewiring, distribution boards, inverter and solar backup sizing. I label every circuit I touch.",
      city: "Lagos",
      area: "Surulere",
      country: "NG",
      distanceKm: 9.8,
      coverage: ["Surulere", "Yaba", "Ikeja", "Gbagada"],
      reviewCount: 128,
      completedJobs: 301,
      yearsExperience: 9,
      verification: { identity: true, trade: true, phone: true },
      availability: "today",
      responseMinutes: 15,
      startingPrice: 12000,
      currency: "NGN",
      skills: ["Rewiring", "Distribution boards", "Solar backup", "Fault tracing"],
      languages: ["English", "Igbo"],
      portfolio: [
        { id: "pf1", caption: "DB board replacement", tone: "danfo" },
        { id: "pf2", caption: "3.5kVA solar backup", tone: "lagoon" },
        { id: "pf3", caption: "Duplex rewiring", tone: "ink" },
      ],
      ratingBreakdown: rb(4.9, 4.8, 4.8, 4.9, 4.7),
      joinedAt: ago(60 * 24 * 620),
    }),
    pro({
      id: "p-ibrahim",
      name: "Ibrahim Musa",
      category: "plumber",
      headline: "Leaks, borehole pumps, water heaters, bathroom fit-outs",
      bio: "Plumbing for homes and small hotels. Pressure testing on every new line before I close the wall.",
      city: "Abuja",
      area: "Wuse 2",
      country: "NG",
      distanceKm: 3.1,
      coverage: ["Wuse", "Garki", "Maitama", "Jabi"],
      reviewCount: 76,
      completedJobs: 158,
      yearsExperience: 14,
      verification: { identity: true, trade: false, phone: true },
      availability: "today",
      responseMinutes: 22,
      startingPrice: 8000,
      currency: "NGN",
      skills: ["Leak detection", "Borehole pumps", "Water heaters", "Bathroom fit-out"],
      languages: ["English", "Hausa"],
      portfolio: [
        { id: "pf1", caption: "Shower and heater install", tone: "stellar" },
        { id: "pf2", caption: "Borehole pump replacement", tone: "lagoon" },
      ],
      ratingBreakdown: rb(4.7, 4.5, 4.6, 4.7, 4.8),
      joinedAt: ago(60 * 24 * 300),
    }),
    pro({
      id: "p-ama",
      userId: "u-ama",
      name: "Ama Owusu",
      category: "cleaner",
      headline: "Deep cleaning, post-construction and move-out cleans",
      bio: "Team of four. We bring our own equipment and eco-friendly products, and we send before-and-after photos.",
      city: "Accra",
      area: "Osu",
      country: "GH",
      distanceKm: 4.4,
      coverage: ["Osu", "Labone", "Cantonments", "Airport Residential", "East Legon"],
      reviewCount: 203,
      completedJobs: 540,
      yearsExperience: 7,
      verification: { identity: true, trade: true, phone: true },
      availability: "this-week",
      responseMinutes: 30,
      startingPrice: 450,
      currency: "GHS",
      skills: ["Deep clean", "Post-construction", "Upholstery", "Move-out"],
      languages: ["English", "Twi", "Ga"],
      portfolio: [
        { id: "pf1", caption: "4-bed post-construction", tone: "lagoon" },
        { id: "pf2", caption: "Office deep clean", tone: "ink" },
        { id: "pf3", caption: "Sofa shampoo", tone: "danfo" },
      ],
      ratingBreakdown: rb(4.9, 4.9, 4.8, 4.9, 4.6),
      joinedAt: ago(60 * 24 * 700),
    }),
    pro({
      id: "p-kwame",
      name: "Kwame Boateng",
      category: "mechanic",
      headline: "Mobile mechanic for Toyota, Honda and Hyundai",
      bio: "I come to you. Diagnostics with an OBD scanner, brakes, suspension, servicing. Genuine parts with receipts.",
      city: "Accra",
      area: "Spintex",
      country: "GH",
      distanceKm: 7.9,
      coverage: ["Spintex", "Tema", "East Legon", "Madina"],
      reviewCount: 61,
      completedJobs: 129,
      yearsExperience: 12,
      verification: { identity: true, trade: false, phone: true },
      availability: "now",
      responseMinutes: 12,
      startingPrice: 300,
      currency: "GHS",
      skills: ["OBD diagnostics", "Brakes", "Suspension", "Servicing"],
      languages: ["English", "Twi"],
      portfolio: [
        { id: "pf1", caption: "Corolla brake overhaul", tone: "clay" },
        { id: "pf2", caption: "Elantra suspension", tone: "ink" },
      ],
      ratingBreakdown: rb(4.6, 4.4, 4.7, 4.6, 4.8),
      joinedAt: ago(60 * 24 * 250),
    }),
    pro({
      id: "p-segun",
      name: "Segun Ajayi",
      category: "generator",
      headline: "Generator servicing, rewinding and changeover switches",
      bio: "Petrol and diesel generators from 2.5kVA to 60kVA. Changeover and ATS installation.",
      city: "Lagos",
      area: "Ikeja",
      country: "NG",
      distanceKm: 12.5,
      coverage: ["Ikeja", "Ogba", "Maryland", "Magodo"],
      reviewCount: 44,
      completedJobs: 97,
      yearsExperience: 16,
      verification: { identity: true, trade: true, phone: false },
      availability: "today",
      responseMinutes: 40,
      startingPrice: 10000,
      currency: "NGN",
      skills: ["Diesel gensets", "Rewinding", "ATS", "Servicing"],
      languages: ["English", "Yoruba"],
      portfolio: [{ id: "pf1", caption: "20kVA ATS install", tone: "danfo" }],
      ratingBreakdown: rb(4.5, 4.2, 4.3, 4.5, 4.6),
      joinedAt: ago(60 * 24 * 900),
    }),
    pro({
      id: "p-efua",
      name: "Efua Mensah",
      category: "painter",
      headline: "Interior and exterior painting, POP ceilings, screeding",
      bio: "Clean edges, covered floors, and a colour sample on the wall before we commit.",
      city: "Kumasi",
      area: "Ahodwo",
      country: "GH",
      distanceKm: 2.7,
      coverage: ["Ahodwo", "Nhyiaeso", "Asokwa", "Bantama"],
      reviewCount: 38,
      completedJobs: 72,
      yearsExperience: 6,
      verification: { identity: true, trade: false, phone: true },
      availability: "this-week",
      responseMinutes: 55,
      startingPrice: 600,
      currency: "GHS",
      skills: ["Interior", "Exterior", "POP ceilings", "Screeding"],
      languages: ["English", "Twi"],
      portfolio: [
        { id: "pf1", caption: "Living room repaint", tone: "clay" },
        { id: "pf2", caption: "POP ceiling", tone: "stellar" },
      ],
      ratingBreakdown: rb(4.8, 4.5, 4.6, 4.7, 4.7),
      joinedAt: ago(60 * 24 * 200),
    }),
    pro({
      id: "p-yusuf",
      name: "Yusuf Bello",
      category: "carpenter",
      headline: "Kitchen cabinets, wardrobes, door and window repairs",
      bio: "Custom furniture from my workshop in Ojodu. I send a drawing with measurements before cutting anything.",
      city: "Lagos",
      area: "Ojodu",
      country: "NG",
      distanceKm: 15.3,
      coverage: ["Ojodu", "Berger", "Ikeja", "Omole"],
      reviewCount: 9,
      completedJobs: 14,
      yearsExperience: 4,
      verification: { identity: false, trade: false, phone: true },
      availability: "today",
      responseMinutes: 25,
      startingPrice: 20000,
      currency: "NGN",
      skills: ["Kitchen cabinets", "Wardrobes", "Door repair"],
      languages: ["English", "Hausa", "Yoruba"],
      portfolio: [{ id: "pf1", caption: "Fitted wardrobe", tone: "ink" }],
      ratingBreakdown: rb(4.4, 4.1, 4.5, 4.3, 4.6),
      joinedAt: ago(60 * 24 * 90),
    }),
  ];

  const reviews: Review[] = [
    {
      id: "r-1",
      bookingId: "b-old-1",
      professionalId: "p-tunde",
      customerId: "u-funmi",
      customerName: "Funmilayo A.",
      jobTitle: "1.5HP split AC not cooling",
      ratings: rb(5, 5, 5, 5, 4),
      comment:
        "Showed me the pressure reading before and after the refill. Found a leak at the flare nut that the last technician missed. Arrived 10 minutes early.",
      createdAt: ago(60 * 24 * 12),
      response: { body: "Thank you ma. Check the flare again in 3 months, it should hold.", createdAt: ago(60 * 24 * 11) },
    },
    {
      id: "r-2",
      bookingId: "b-old-2",
      professionalId: "p-tunde",
      customerId: "u-kofi",
      customerName: "Kofi A.",
      jobTitle: "Office AC servicing, 4 units",
      ratings: rb(5, 4, 5, 5, 5),
      comment: "Serviced all four units in one afternoon and left the place clean. Fair price for the work.",
      createdAt: ago(60 * 24 * 40),
    },
    {
      id: "r-3",
      bookingId: "b-old-3",
      professionalId: "p-tunde",
      customerId: "u-adaeze",
      customerName: "Adaeze O.",
      jobTitle: "Inverter AC PCB fault",
      ratings: rb(4.7, 5, 4.7, 4.4, 4.4),
      comment: "Took longer than planned because of the part, but he kept me updated the whole time.",
      createdAt: ago(60 * 24 * 95),
    },
  ];

  // Active demo conversation: Adaeze <-> Tunde with a pending quotation.
  const quoteTotal = 38000 + 9500;
  const quotes: Quote[] = [
    {
      id: "q-ac-1",
      conversationId: "c-tunde",
      professionalId: "p-tunde",
      customerId: "u-adaeze",
      version: 1,
      status: "PENDING",
      title: "Bedroom 1.5HP split AC: diagnose, gas refill, leak fix",
      description:
        "Pressure test the indoor and outdoor unit, locate and repair the leak, flush and refill R410A, clean filters and coil, confirm cooling at 18°C for 30 minutes.",
      labour: 38000,
      materials: 9500,
      total: quoteTotal,
      currency: "NGN",
      completionDate: ahead(2),
      paymentTerms: "Full amount held in Handi escrow. Released when you approve the finished job.",
      milestones: [],
      createdAt: ago(18),
    },
    {
      id: "q-wire-1",
      conversationId: "c-chioma",
      professionalId: "p-chioma",
      customerId: "u-adaeze",
      version: 1,
      status: "ACCEPTED",
      title: "Kitchen circuit fault tracing and new 32A breaker",
      description: "Trace the tripping kitchen circuit, replace the faulty breaker, re-terminate cooker point, label the board.",
      labour: 22000,
      materials: 14000,
      total: 36000,
      currency: "NGN",
      completionDate: ahead(1),
      paymentTerms: "Full amount held in Handi escrow. Released on approval.",
      milestones: [],
      createdAt: ago(60 * 26),
      acceptedAt: ago(60 * 25),
      agreementHash: hex(),
    },
    {
      id: "q-clean-1",
      conversationId: "c-ama",
      professionalId: "p-ama",
      customerId: "u-kofi",
      version: 1,
      status: "ACCEPTED",
      title: "Post-construction clean, 3-bedroom apartment",
      description: "Dust and debris removal, window tracks, kitchen degrease, floor scrub, two bathrooms.",
      labour: 1400,
      materials: 250,
      total: 1650,
      currency: "GHS",
      completionDate: ago(60 * 24 * 2),
      paymentTerms: "Full amount held in Handi escrow.",
      milestones: [],
      createdAt: ago(60 * 24 * 6),
      acceptedAt: ago(60 * 24 * 6 - 30),
      agreementHash: hex(),
    },
  ];

  const conversations: Conversation[] = [
    {
      id: "c-tunde",
      customerId: "u-adaeze",
      professionalId: "p-tunde",
      lastMessageAt: ago(18),
      lastMessagePreview: "Quotation sent",
      unreadFor: ["u-adaeze"],
    },
    {
      id: "c-chioma",
      customerId: "u-adaeze",
      professionalId: "p-chioma",
      bookingId: "b-wire",
      lastMessageAt: ago(60 * 3),
      lastMessagePreview: "I'm at the gate now.",
      unreadFor: [],
    },
    {
      id: "c-ama",
      customerId: "u-kofi",
      professionalId: "p-ama",
      bookingId: "b-clean",
      lastMessageAt: ago(60 * 24),
      lastMessagePreview: "Dispute opened",
      unreadFor: [],
    },
  ];

  const messages: Message[] = [
    { id: "m1", conversationId: "c-tunde", senderId: "u-adaeze", kind: "text", body: "Good afternoon. My bedroom AC is blowing warm air since Sunday. It's a 1.5HP split, about 3 years old.", createdAt: ago(64), readAt: ago(60) },
    { id: "m2", conversationId: "c-tunde", senderId: "u-tunde", kind: "text", body: "Good afternoon. Is the outdoor fan spinning when you switch it on? And any ice on the copper pipes?", createdAt: ago(58), readAt: ago(55) },
    { id: "m3", conversationId: "c-tunde", senderId: "u-adaeze", kind: "text", body: "Fan is spinning. I saw a bit of frost near the valve yesterday morning.", createdAt: ago(52), readAt: ago(50) },
    { id: "m4", conversationId: "c-tunde", senderId: "u-tunde", kind: "text", body: "That sounds like low gas from a slow leak. I can come Thursday morning, find the leak, fix it and refill. Sending a quotation now so you can see the breakdown.", createdAt: ago(20), readAt: ago(19) },
    { id: "m5", conversationId: "c-tunde", senderId: "u-tunde", kind: "quote", body: "Quotation", quoteId: "q-ac-1", createdAt: ago(18) },

    { id: "m6", conversationId: "c-chioma", senderId: "u-adaeze", kind: "text", body: "The kitchen breaker trips whenever the cooker and kettle are on together.", createdAt: ago(60 * 27) },
    { id: "m7", conversationId: "c-chioma", senderId: "u-chioma", kind: "quote", body: "Quotation", quoteId: "q-wire-1", createdAt: ago(60 * 26) },
    { id: "m8", conversationId: "c-chioma", senderId: "system", kind: "system", body: "Quotation accepted. Booking created.", createdAt: ago(60 * 25) },
    { id: "m9", conversationId: "c-chioma", senderId: "system", kind: "system", body: `${toUsdc(36000, "NGN").toFixed(2)} USDC funded to escrow on Stellar testnet.`, createdAt: ago(60 * 24) },
    { id: "m10", conversationId: "c-chioma", senderId: "u-chioma", kind: "text", body: "I'm at the gate now.", createdAt: ago(60 * 3) },

    { id: "m11", conversationId: "c-ama", senderId: "u-ama", kind: "quote", body: "Quotation", quoteId: "q-clean-1", createdAt: ago(60 * 24 * 6) },
    { id: "m12", conversationId: "c-ama", senderId: "system", kind: "system", body: "Dispute opened by customer.", createdAt: ago(60 * 24) },
  ];

  const wireUsdc = toUsdc(36000, "NGN");
  const cleanUsdc = toUsdc(1650, "GHS");

  const escrows: Escrow[] = [
    {
      id: "e-wire",
      bookingId: "b-wire",
      contractId: DEMO_CONTRACT,
      state: "FUNDED",
      asset: "USDC",
      amount: wireUsdc,
      localAmount: 36000,
      currency: "NGN",
      rate: RATES.NGN,
      networkFee: 0.00421,
      customerWallet: "GBADAEZEDEMOWALLETTESTNET4QKX7M2JZP5VRB2N8LYTFA4HGSUXQ",
      professionalWallet: "GCCHIOMADEMOWALLETTESTNET7QKX7M2JZP5VRB2N8LYTFA4HGSUX",
      reconciliation: "CONFIRMED",
      transactions: [{ kind: "FUND", hash: hex(), ledger: 1184203, at: ago(60 * 24), status: "CONFIRMED", simulated: true }],
      createdAt: ago(60 * 25),
    },
    {
      id: "e-clean",
      bookingId: "b-clean",
      contractId: DEMO_CONTRACT,
      state: "DISPUTED",
      asset: "USDC",
      amount: cleanUsdc,
      localAmount: 1650,
      currency: "GHS",
      rate: RATES.GHS,
      networkFee: 0.00421,
      customerWallet: "GBKOFIDEMOWALLETTESTNET2QKX7M2JZP5VRB2N8LYTFA4HGSUXQAB",
      professionalWallet: "GCAMADEMOWALLETTESTNET3QKX7M2JZP5VRB2N8LYTFA4HGSUXQAB",
      reconciliation: "CONFIRMED",
      transactions: [{ kind: "FUND", hash: hex(), ledger: 1179911, at: ago(60 * 24 * 5), status: "CONFIRMED", simulated: true }],
      createdAt: ago(60 * 24 * 6),
    },
  ];

  const bookings: Booking[] = [
    {
      id: "b-wire",
      quoteId: "q-wire-1",
      conversationId: "c-chioma",
      customerId: "u-adaeze",
      professionalId: "p-chioma",
      title: "Kitchen circuit fault tracing and new 32A breaker",
      address: "14 Admiralty Way, Lekki Phase 1",
      status: "IN_PROGRESS",
      createdAt: ago(60 * 25),
      escrowId: "e-wire",
      timeline: [
        { at: ago(60 * 25), label: "Quotation accepted", actor: "customer" },
        { at: ago(60 * 24), label: "Escrow funded and confirmed on-chain", actor: "chain" },
        { at: ago(60 * 3), label: "Job started", actor: "professional" },
      ],
    },
    {
      id: "b-clean",
      quoteId: "q-clean-1",
      conversationId: "c-ama",
      customerId: "u-kofi",
      professionalId: "p-ama",
      title: "Post-construction clean, 3-bedroom apartment",
      address: "7 Lagos Avenue, East Legon",
      status: "DISPUTED",
      createdAt: ago(60 * 24 * 6),
      escrowId: "e-clean",
      disputeId: "d-1",
      completion: {
        notes: "All rooms cleaned. Kitchen degreased, window tracks done. Balcony tiles have cement stains that need acid wash (not in scope).",
        checklist: [
          { label: "Dust and debris removal", done: true },
          { label: "Window tracks", done: true },
          { label: "Kitchen degrease", done: true },
          { label: "Floor scrub", done: true },
          { label: "Two bathrooms", done: true },
        ],
        photos: [
          { id: "ph1", name: "living-room-after.jpg" },
          { id: "ph2", name: "kitchen-after.jpg" },
          { id: "ph3", name: "balcony.jpg" },
        ],
        submittedAt: ago(60 * 24 * 2),
        hash: hex(),
      },
      timeline: [
        { at: ago(60 * 24 * 6), label: "Quotation accepted", actor: "customer" },
        { at: ago(60 * 24 * 5), label: "Escrow funded and confirmed on-chain", actor: "chain" },
        { at: ago(60 * 24 * 3), label: "Job started", actor: "professional" },
        { at: ago(60 * 24 * 2), label: "Completion evidence submitted", actor: "professional" },
        { at: ago(60 * 24), label: "Dispute opened, funds locked", actor: "customer" },
      ],
    },
  ];

  const disputes: Dispute[] = [
    {
      id: "d-1",
      bookingId: "b-clean",
      escrowId: "e-clean",
      openedBy: "u-kofi",
      reason: "Work incomplete",
      details: "Balcony and the boys' quarters were part of 'the apartment'. Cement stains still on balcony tiles. Happy to release most of it.",
      status: "UNDER_REVIEW",
      openedAt: ago(60 * 24),
    },
  ];

  const notifications: AppNotification[] = [
    { id: "n1", userId: "u-adaeze", title: "New quotation from Tunde Bakare", body: "₦47,500 for AC diagnosis, gas refill and leak fix.", href: "/messages/c-tunde", at: ago(18), read: false },
    { id: "n2", userId: "u-adaeze", title: "Chioma started your job", body: "Kitchen circuit fault tracing is in progress.", href: "/bookings/b-wire", at: ago(60 * 3), read: true },
    { id: "n3", userId: "u-tunde", title: "Adaeze Okafor sent a message", body: "Fan is spinning. I saw a bit of frost…", href: "/messages/c-tunde", at: ago(52), read: true },
    { id: "n4", userId: "u-ops", title: "Dispute needs review", body: "Post-construction clean, East Legon.", href: "/admin", at: ago(60 * 24), read: false },
  ];

  // Ama has a user record for chat attribution
  users.push({ id: "u-ama", name: "Ama Owusu", email: "ama@demo.handi", role: "professional", city: "Osu, Accra", country: "GH", professionalId: "p-ama" });

  addMoreSeed({ users, professionals, reviews, conversations, messages, quotes, bookings, escrows, notifications });

  return {
    version: DB_VERSION,
    users,
    professionals,
    reviews,
    conversations,
    messages,
    quotes,
    bookings,
    escrows,
    disputes,
    notifications,
  };
}


/* ------------------------------------------------------------------ */
/* More demo data so every screen has realistic content in each state. */

type SeedParts = Pick<DB, "users" | "professionals" | "reviews" | "conversations" | "messages" | "quotes" | "bookings" | "escrows" | "notifications">;

function addMoreSeed(d: SeedParts) {
  const P = (p: Omit<Professional, "rating">): Professional => ({
    ...p,
    rating:
      Math.round(
        ((p.ratingBreakdown.quality + p.ratingBreakdown.punctuality + p.ratingBreakdown.communication + p.ratingBreakdown.professionalism + p.ratingBreakdown.value) / 5) *
          10,
      ) / 10,
  });
  const base = { verification: { identity: true, trade: true, phone: true }, languages: ["English"], portfolio: [] as Professional["portfolio"] };

  d.professionals.push(
    P({ ...base, id: "p-bola", userId: "u-bola", name: "Bola Ogunleye", category: "plumber", headline: "Leak repair, pumping machines, bathroom and kitchen plumbing", bio: "Plumber covering Lekki and Ajah. I pressure-test new lines and show you the reading before closing up.", city: "Lagos", area: "Ajah", country: "NG", distanceKm: 8, coverage: ["Ajah", "Lekki Phase 1", "Sangotedo", "Chevron"], reviewCount: 54, completedJobs: 133, yearsExperience: 10, availability: "today", responseMinutes: 18, startingPrice: 9000, currency: "NGN", skills: ["Leak repair", "Pumping machine", "Water heater", "Bathroom fit-out"], languages: ["English", "Yoruba"], ratingBreakdown: rb(4.8, 4.6, 4.7, 4.8, 4.7), joinedAt: ago(60 * 24 * 500) }),
    P({ ...base, id: "p-grace", userId: "u-grace", name: "Grace Nwankwo", category: "cleaner", headline: "Home deep cleaning and post-renovation cleaning in Lekki and VI", bio: "Team of three. We bring our own vacuum, steamer and products, and send before-and-after photos.", city: "Lagos", area: "Lekki", country: "NG", distanceKm: 3, coverage: ["Lekki", "Victoria Island", "Ikoyi", "Oniru"], reviewCount: 88, completedJobs: 241, yearsExperience: 6, availability: "today", responseMinutes: 12, startingPrice: 25000, currency: "NGN", skills: ["Deep clean", "Post-renovation", "Upholstery"], languages: ["English", "Igbo"], ratingBreakdown: rb(4.9, 4.8, 4.9, 4.9, 4.6), joinedAt: ago(60 * 24 * 380) }),
    P({ ...base, id: "p-kunle", userId: "u-kunle", name: "Kunle Adebayo", category: "electrician", headline: "Prepaid meter issues, rewiring, inverter installation", bio: "Electrician on the mainland. Fault finding with a proper tester, not guesswork.", city: "Lagos", area: "Ikeja", country: "NG", distanceKm: 14, coverage: ["Ikeja", "Ogba", "Agege", "Maryland"], reviewCount: 41, completedJobs: 96, yearsExperience: 8, availability: "now", responseMinutes: 10, startingPrice: 10000, currency: "NGN", skills: ["Prepaid meters", "Rewiring", "Inverters"], languages: ["English", "Yoruba"], ratingBreakdown: rb(4.6, 4.7, 4.5, 4.6, 4.8), joinedAt: ago(60 * 24 * 260) }),
    P({ ...base, id: "p-nana", userId: "u-nana", name: "Nana Agyeman", category: "ac-technician", headline: "AC servicing, installation and repair across Accra", bio: "Split and window units. Servicing plans for homes and small offices.", city: "Accra", area: "Dzorwulu", country: "GH", distanceKm: 5, coverage: ["Dzorwulu", "Airport Residential", "East Legon", "Cantonments"], reviewCount: 67, completedJobs: 188, yearsExperience: 9, availability: "today", responseMinutes: 20, startingPrice: 350, currency: "GHS", skills: ["Servicing", "Installation", "Gas refill"], languages: ["English", "Twi"], ratingBreakdown: rb(4.7, 4.6, 4.8, 4.7, 4.6), joinedAt: ago(60 * 24 * 420) }),
    P({ ...base, id: "p-hauwa", userId: "u-hauwa", name: "Hauwa Sani", category: "painter", headline: "Interior painting, wallpaper and screeding in Abuja", bio: "Clean edges and covered furniture. I bring colour samples to try on your wall first.", city: "Abuja", area: "Gwarinpa", country: "NG", distanceKm: 9, coverage: ["Gwarinpa", "Jabi", "Life Camp", "Kubwa"], reviewCount: 29, completedJobs: 61, yearsExperience: 5, availability: "this-week", responseMinutes: 35, startingPrice: 30000, currency: "NGN", skills: ["Interior", "Wallpaper", "Screeding"], languages: ["English", "Hausa"], verification: { identity: true, trade: false, phone: true }, ratingBreakdown: rb(4.7, 4.5, 4.6, 4.7, 4.8), joinedAt: ago(60 * 24 * 180) }),
    P({ ...base, id: "p-kojo", userId: "u-kojo", name: "Kojo Darko", category: "carpenter", headline: "Doors, wardrobes, roofing timber and furniture repair", bio: "Workshop in Kaneshie. Measured drawings before any cutting.", city: "Accra", area: "Kaneshie", country: "GH", distanceKm: 11, coverage: ["Kaneshie", "Dansoman", "Osu", "Adabraka"], reviewCount: 33, completedJobs: 74, yearsExperience: 15, availability: "this-week", responseMinutes: 45, startingPrice: 400, currency: "GHS", skills: ["Doors", "Wardrobes", "Roofing timber"], languages: ["English", "Twi", "Ga"], ratingBreakdown: rb(4.6, 4.3, 4.5, 4.6, 4.7), joinedAt: ago(60 * 24 * 700) }),
  );

  d.users.push(
    { id: "u-bola", name: "Bola Ogunleye", email: "bola@demo.handi", role: "professional", city: "Ajah, Lagos", country: "NG", professionalId: "p-bola" },
    { id: "u-grace", name: "Grace Nwankwo", email: "grace@demo.handi", role: "professional", city: "Lekki, Lagos", country: "NG", professionalId: "p-grace" },
    { id: "u-segun", name: "Segun Ajayi", email: "segun@demo.handi", role: "professional", city: "Ikeja, Lagos", country: "NG", professionalId: "p-segun" },
    { id: "u-emeka", name: "Emeka Obi", email: "emeka@demo.handi", role: "customer", city: "Ikoyi, Lagos", country: "NG" },
  );
  const seg = d.professionals.find((p) => p.id === "p-segun");
  if (seg) seg.userId = "u-segun";

  const more: Review[] = [
    { id: "r-c1", bookingId: "b-old-c1", professionalId: "p-chioma", customerId: "u-funmi", customerName: "Funmilayo A.", jobTitle: "Duplex rewiring, ground floor", ratings: rb(5, 5, 5, 5, 4), comment: "Labelled every breaker and gave me a drawing of the board. The house has not tripped since.", createdAt: ago(60 * 24 * 20) },
    { id: "r-c2", bookingId: "b-old-c2", professionalId: "p-chioma", customerId: "u-emeka", customerName: "Emeka O.", jobTitle: "3.5kVA inverter and solar backup", ratings: rb(4.8, 4.6, 5, 5, 4.6), comment: "Sized the inverter properly instead of upselling. Clean cable work.", createdAt: ago(60 * 24 * 52) },
    { id: "r-b1", bookingId: "b-old-b1", professionalId: "p-bola", customerId: "u-funmi", customerName: "Funmilayo A.", jobTitle: "Kitchen sink leak", ratings: rb(5, 4, 5, 5, 5), comment: "Found the leak behind the cabinet in ten minutes. Fair price.", createdAt: ago(60 * 24 * 33) },
    { id: "r-g1", bookingId: "b-old-g1", professionalId: "p-grace", customerId: "u-emeka", customerName: "Emeka O.", jobTitle: "Post-renovation clean, 4 bedrooms", ratings: rb(5, 5, 5, 5, 4.4), comment: "The paint splashes on the tiles are gone. Sent photos of every room before leaving.", createdAt: ago(60 * 24 * 9) },
    { id: "r-a1", bookingId: "b-old-a1", professionalId: "p-ama", customerId: "u-kofi", customerName: "Kofi A.", jobTitle: "Move-out clean, 2 bedrooms", ratings: rb(5, 5, 4.6, 5, 4.6), comment: "Landlord returned the full deposit. That says enough.", createdAt: ago(60 * 24 * 70) },
    { id: "r-i1", bookingId: "b-old-i1", professionalId: "p-ibrahim", customerId: "u-emeka", customerName: "Emeka O.", jobTitle: "Borehole pump replacement", ratings: rb(4.6, 4.4, 4.6, 4.8, 4.8), comment: "Pump replaced and pressure tested the same day.", createdAt: ago(60 * 24 * 41) },
  ];
  d.reviews.push(...more);

  // Helper: one conversation + accepted quote + booking (+ escrow) in a given state.
  function job(o: {
    id: string; customerId: string; pid: string; title: string; description: string; labour: number; materials: number;
    currency: "NGN" | "GHS"; address: string; status: Booking["status"]; daysAgo: number; lastLine: string; reviewId?: string;
    completion?: Booking["completion"];
  }) {
    const pro = d.professionals.find((p) => p.id === o.pid)!;
    const total = o.labour + o.materials;
    const t0 = 60 * 24 * o.daysAgo;
    d.quotes.push({ id: `q-${o.id}`, conversationId: `c-${o.id}`, professionalId: o.pid, customerId: o.customerId, version: 1, status: "ACCEPTED", title: o.title, description: o.description, labour: o.labour, materials: o.materials, total, currency: o.currency, completionDate: ago(t0 - 60 * 24 * 2), paymentTerms: "Full amount held in Handi escrow. Released on approval.", milestones: [], createdAt: ago(t0 + 60), acceptedAt: ago(t0), agreementHash: hex() });
    d.conversations.push({ id: `c-${o.id}`, customerId: o.customerId, professionalId: o.pid, bookingId: `b-${o.id}`, lastMessageAt: ago(Math.max(5, t0 - 60 * 24 * o.daysAgo * 0.7)), lastMessagePreview: o.lastLine, unreadFor: [] });
    d.messages.push(
      { id: `m-${o.id}-1`, conversationId: `c-${o.id}`, senderId: o.customerId, kind: "text", body: `Hello, I need help with this: ${o.title.toLowerCase()}.`, createdAt: ago(t0 + 120), readAt: ago(t0 + 110) },
      { id: `m-${o.id}-2`, conversationId: `c-${o.id}`, senderId: pro.userId, kind: "quote", body: "Quotation", quoteId: `q-${o.id}`, createdAt: ago(t0 + 60) },
      { id: `m-${o.id}-3`, conversationId: `c-${o.id}`, senderId: "system", kind: "system", body: "Quotation accepted. Agreement locked and booking created.", createdAt: ago(t0) },
      { id: `m-${o.id}-4`, conversationId: `c-${o.id}`, senderId: pro.userId, kind: "text", body: o.lastLine, createdAt: ago(Math.max(5, t0 - 60 * 24 * o.daysAgo * 0.7)) },
    );
    const timeline: Booking["timeline"] = [{ at: ago(t0), label: "Quotation v1 accepted and locked", actor: "customer" }];
    const funded = o.status !== "PENDING_PAYMENT" && o.status !== "CANCELLED";
    let escrowId: string | undefined;
    if (funded) {
      escrowId = `e-${o.id}`;
      const amount = toUsdc(total, o.currency);
      const released = o.status === "COMPLETED";
      d.escrows.push({
        id: escrowId, bookingId: `b-${o.id}`, contractId: "CDHANDIESCROWTESTNETDEMO7QX4M2KJ5ZP6V3WRB2N8LYTFA4HGSU",
        state: released ? "RELEASED" : "FUNDED", asset: "USDC", amount, localAmount: total, currency: o.currency, rate: RATES[o.currency], networkFee: 0.00421,
        customerWallet: "GBHANDIDEMOCUSTOMERWALLETQ7XKJ5ZP6V3WRB2N8LYTFA4HGSUQM", professionalWallet: `GC${o.pid.replace("p-", "").toUpperCase()}DEMOWALLETTESTNET7QKX7M2JZP5VRB2N8LYTFA4HGSUXQ`.slice(0, 56),
        reconciliation: "CONFIRMED",
        transactions: [
          { kind: "FUND", hash: hex(), ledger: 1_170_000 + o.daysAgo * 100, at: ago(t0 - 30), status: "CONFIRMED", simulated: true },
          ...(released ? [{ kind: "RELEASE" as const, hash: hex(), ledger: 1_175_000 + o.daysAgo * 100, at: ago(t0 - 60 * 24 * 2), status: "CONFIRMED" as const, simulated: true }] : []),
        ],
        createdAt: ago(t0),
      });
      timeline.push({ at: ago(t0 - 30), label: "Escrow funded and confirmed on-chain", actor: "chain" });
      if (["IN_PROGRESS", "COMPLETION_SUBMITTED", "COMPLETED"].includes(o.status)) timeline.push({ at: ago(t0 - 60 * 24), label: "Job started", actor: "professional" });
      if (["COMPLETION_SUBMITTED", "COMPLETED"].includes(o.status)) timeline.push({ at: ago(t0 - 60 * 30), label: "Completion evidence submitted", actor: "professional" });
      if (released) timeline.push({ at: ago(t0 - 60 * 24 * 2), label: "Payment released to professional", actor: "chain" });
    }
    d.bookings.push({ id: `b-${o.id}`, quoteId: `q-${o.id}`, conversationId: `c-${o.id}`, customerId: o.customerId, professionalId: o.pid, title: o.title, address: o.address, status: o.status, createdAt: ago(t0), escrowId, completion: o.completion, reviewId: o.reviewId, timeline });
  }

  const evidence = (notes: string, items: string[], photos: string[]): Booking["completion"] => ({
    notes, checklist: items.map((label) => ({ label, done: true })), photos: photos.map((name, i) => ({ id: `ph-${i}-${name}`, name })), submittedAt: ago(90), hash: hex(),
  });

  // Adaeze (customer): one to fund, one to approve, one finished and reviewed.
  job({ id: "gen", customerId: "u-adaeze", pid: "p-segun", title: "Service 7.5kVA generator and replace changeover switch", description: "Full service, oil and filters, replace burnt changeover with a 63A unit, test under load.", labour: 18000, materials: 26000, currency: "NGN", address: "14 Admiralty Way, Lekki Phase 1", status: "PENDING_PAYMENT", daysAgo: 0.05, lastLine: "Once you fund it I'll buy the changeover on my way." });
  job({ id: "deep", customerId: "u-adaeze", pid: "p-grace", title: "Deep clean after kitchen renovation", description: "Remove dust and paint splashes, degrease cabinets, clean windows and tracks, mop and polish floors.", labour: 35000, materials: 7000, currency: "NGN", address: "14 Admiralty Way, Lekki Phase 1", status: "COMPLETION_SUBMITTED", daysAgo: 2, lastLine: "All done. Photos are in the booking.", completion: evidence("Kitchen and living room deep cleaned. Paint splashes removed from tiles and window frames. Cabinets degreased inside and out.", ["Dust and debris removed", "Paint splashes removed", "Cabinets degreased", "Windows and tracks cleaned", "Floors mopped and polished"], ["kitchen-after.jpg", "living-room-after.jpg", "windows.jpg"]) });
  job({ id: "sink", customerId: "u-adaeze", pid: "p-bola", title: "Fix leaking kitchen sink and replace waste pipe", description: "Replace cracked waste pipe and trap, reseal sink, test for leaks.", labour: 12000, materials: 6500, currency: "NGN", address: "14 Admiralty Way, Lekki Phase 1", status: "COMPLETED", daysAgo: 12, lastLine: "Thank you ma. Call me if it drips again.", reviewId: "r-b2" });
  d.reviews.push({ id: "r-b2", bookingId: "b-sink", professionalId: "p-bola", customerId: "u-adaeze", customerName: "Adaeze O.", jobTitle: "Fix leaking kitchen sink and replace waste pipe", ratings: rb(5, 5, 4.8, 5, 5), comment: "Came the same afternoon, replaced the pipe and showed me it was dry after running the tap for ten minutes.", createdAt: ago(60 * 24 * 9) });

  // Tunde (professional): one to start, one in progress, two paid.
  job({ id: "ac-emeka", customerId: "u-emeka", pid: "p-tunde", title: "Install 1.5HP split AC in study", description: "Mount indoor and outdoor units, run copper and drain, vacuum and commission.", labour: 45000, materials: 22000, currency: "NGN", address: "3 Bourdillon Road, Ikoyi", status: "FUNDED", daysAgo: 0.3, lastLine: "Funds are in. See you tomorrow at 9." });
  job({ id: "ac-funmi", customerId: "u-funmi", pid: "p-tunde", title: "Service 3 split units and clean drains", description: "Wash filters and coils, flush drains, check gas pressure on all units.", labour: 30000, materials: 0, currency: "NGN", address: "21 Allen Avenue, Ikeja", status: "IN_PROGRESS", daysAgo: 1, lastLine: "Two done, starting the third now." });
  job({ id: "ac-old1", customerId: "u-emeka", pid: "p-tunde", title: "Replace capacitor on outdoor unit", description: "Diagnose, replace run capacitor, test.", labour: 15000, materials: 8000, currency: "NGN", address: "3 Bourdillon Road, Ikoyi", status: "COMPLETED", daysAgo: 18, lastLine: "Working well now. Thanks for the quick payment." });
  job({ id: "ac-old2", customerId: "u-funmi", pid: "p-tunde", title: "Gas refill, 1HP bedroom unit", description: "Leak test, refill R22, confirm cooling.", labour: 18000, materials: 7000, currency: "NGN", address: "21 Allen Avenue, Ikeja", status: "COMPLETED", daysAgo: 30, lastLine: "All sorted." });

  d.notifications.unshift(
    { id: "n-x1", userId: "u-adaeze", title: "Grace marked the job complete", body: "Review the photos and approve or raise a dispute.", href: "/bookings/b-deep", at: ago(90), read: false },
    { id: "n-x2", userId: "u-adaeze", title: "Fund your generator booking", body: "Segun is waiting for the escrow before buying parts.", href: "/bookings/b-gen", at: ago(60), read: false },
    { id: "n-x3", userId: "u-tunde", title: "Payment secured", body: "Install 1.5HP split AC in study: funds are held. You can start.", href: "/bookings/b-ac-emeka", at: ago(60 * 7), read: false },
  );
}
