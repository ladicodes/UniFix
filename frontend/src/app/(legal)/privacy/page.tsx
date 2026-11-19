import type { Metadata } from "next";
import { LegalDoc } from "@/components/legal-doc";

export const metadata: Metadata = {
  title: "Privacy policy",
  description: "What UniFix collects, why, who can see it, and what is public on the Stellar network.",
};

export default function PrivacyPage() {
  return (
    <LegalDoc
      title="Privacy policy"
      updated="19 November 2026"
      intro={<p>This policy explains what UniFix collects when you use it, why, who can see it, and the choices you have.</p>}
      sections={[
        {
          id: "collect",
          title: "What we collect",
          body: (
            <ul>
              <li>Account details: name, email, city and role. Your password is stored only as a salted hash.</li>
              <li>Professional profiles: trade, headline, bio, areas covered, skills, prices and portfolio.</li>
              <li>Verification documents professionals upload, such as ID and trade certificates.</li>
              <li>Conversations, quotations, photos, completion evidence, disputes and reviews linked to your bookings.</li>
              <li>Your public Stellar wallet address and a signed message proving you own it. Never your secret key.</li>
            </ul>
          ),
        },
        {
          id: "use",
          title: "Why we use it",
          body: (
            <ul>
              <li>To run bookings: match customers and professionals, lock agreements and prepare escrow transactions.</li>
              <li>To keep the marketplace safe: verify professionals, review reports and resolve disputes.</li>
              <li>To send you notifications about your jobs and payments.</li>
            </ul>
          ),
        },
        {
          id: "who",
          title: "Who can see it",
          body: (
            <ul>
              <li>Your public profile and verified reviews are visible to everyone.</li>
              <li>A conversation and its booking are visible to the customer and professional in it, and to a resolver if a dispute is opened.</li>
              <li>Verification documents are seen only by UniFix operations. Customers see the result, never the document.</li>
              <li>We do not sell personal data.</li>
            </ul>
          ),
        },
        {
          id: "blockchain",
          title: "What is public on Stellar",
          body: (
            <p>
              Escrow funding, release and refund transactions are recorded on the Stellar network. Anyone can see the wallet addresses, amounts
              and times involved. The contract stores a hash of the agreement, not its text, names or messages. Blockchain records cannot be
              deleted.
            </p>
          ),
        },
        {
          id: "retention",
          title: "How long we keep it",
          body: (
            <p>
              We keep booking records, including evidence and disputes, for as long as needed to settle payments and handle disputes, then for
              the period the law requires. You can ask us to delete your account; records tied to open bookings or disputes are kept until they
              close.
            </p>
          ),
        },
        {
          id: "rights",
          title: "Your choices",
          body: (
            <ul>
              <li>Edit your name, city and public profile from your profile page.</li>
              <li>Ask for a copy of your data or for deletion through UniFix support.</li>
              <li>Disconnect your wallet at any time from the wallet page.</li>
            </ul>
          ),
        },
        {
          id: "demo",
          title: "Demo mode",
          body: (
            <p>
              In demo mode, all data stays in your browser&apos;s local storage and nothing is sent to a UniFix server. Clearing your browser
              data removes it.
            </p>
          ),
        },
        {
          id: "contact",
          title: "Changes and contact",
          body: <p>We will update this policy before handling real payments and tell you in the app. Questions go to UniFix support through your account.</p>,
        },
      ]}
    />
  );
}
