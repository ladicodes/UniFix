import type { Metadata } from "next";
import { LegalDoc } from "@/components/legal-doc";

export const metadata: Metadata = {
  title: "Terms and conditions",
  description: "The rules for hiring and working through UniFix, including escrow payments, disputes and reviews.",
};

export default function TermsPage() {
  return (
    <LegalDoc
      title="Terms and conditions"
      updated="19 November 2026"
      intro={
        <p>
          These terms cover your use of UniFix as a customer who hires professionals or as a professional who offers services. By creating an
          account you agree to them.
        </p>
      }
      sections={[
        {
          id: "service",
          title: "What UniFix does",
          body: (
            <>
              <p>
                UniFix is a marketplace. It helps customers find professionals, agree on a quotation and pay through an escrow contract on the
                Stellar network. UniFix is not the employer of any professional and does not perform the work.
              </p>
              <p>The contract for the job is between the customer and the professional, on the terms of the accepted quotation.</p>
            </>
          ),
        },
        {
          id: "accounts",
          title: "Accounts",
          body: (
            <ul>
              <li>You must give accurate details and keep your sign-in credentials private.</li>
              <li>One person per account. Professionals must offer only services they are qualified and allowed to perform.</li>
              <li>We may suspend an account that breaks these terms, for example by asking to be paid outside UniFix.</li>
            </ul>
          ),
        },
        {
          id: "quotations",
          title: "Quotations and bookings",
          body: (
            <ul>
              <li>A quotation states the scope, labour, materials, completion date and payment terms.</li>
              <li>When a customer accepts a quotation, that version is locked and becomes the agreement. A price change needs a new quotation.</li>
              <li>Either side can cancel a booking before it is funded.</li>
            </ul>
          ),
        },
        {
          id: "escrow",
          title: "Escrow payments",
          body: (
            <>
              <p>
                The customer funds the agreed amount into a Soroban smart contract from their own Stellar wallet. UniFix never holds your secret
                keys and cannot move escrowed funds for itself.
              </p>
              <ul>
                <li>Funds are released to the professional when the customer approves the work.</li>
                <li>A professional can cancel a funded job and refund the customer in full.</li>
                <li>If a dispute is open, funds stay locked until it is resolved.</li>
                <li>Every transaction needs your signature in your wallet. Blockchain transactions cannot be reversed once confirmed.</li>
                <li>UniFix charges no fee during the pilot. Stellar network fees are paid by the person signing.</li>
              </ul>
            </>
          ),
        },
        {
          id: "disputes",
          title: "Disputes",
          body: (
            <>
              <p>
                Either party can raise a dispute while funds are held. A UniFix resolver reviews the locked agreement, the conversation and the
                completion evidence, then authorises a release, a refund or a split. The contract carries out the decision.
              </p>
              <p>Give honest evidence. Fabricated photos or messages lead to account suspension.</p>
            </>
          ),
        },
        {
          id: "reviews",
          title: "Reviews",
          body: (
            <ul>
              <li>Only a customer with a completed, paid booking can review that booking, once.</li>
              <li>Professionals can reply publicly. We may hide reviews that are abusive or not about the job.</li>
            </ul>
          ),
        },
        {
          id: "conduct",
          title: "Conduct",
          body: (
            <ul>
              <li>No harassment, discrimination or unsafe work.</li>
              <li>No arranging payment outside UniFix for jobs found on UniFix.</li>
              <li>Report problems from any conversation. We review every report.</li>
            </ul>
          ),
        },
        {
          id: "liability",
          title: "Liability",
          body: (
            <p>
              Professionals are responsible for the quality and safety of their work. UniFix provides the platform and the escrow process as is
              during the pilot and is not liable for losses caused by the work itself, by your wallet, or by the Stellar network.
            </p>
          ),
        },
        {
          id: "changes",
          title: "Changes and contact",
          body: (
            <p>
              We will update these terms before UniFix moves from testnet to real payments, and tell you in the app. Questions go to UniFix
              support through your account.
            </p>
          ),
        },
      ]}
    />
  );
}
