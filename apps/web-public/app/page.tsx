import { MockDataBadge } from '@sarana/ui';

/**
 * The public transparency dashboard shell.
 *
 * Non-negotiable #3: no personal data on any public surface. Everything published here
 * is aggregate, with a minimum cell size, and anomaly flags never appear at all.
 *
 * The aid-ledger figures, the daily Merkle root feed and the grievance statistics are
 * built in a later step.
 */
export default function Home() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-10">
      <header className="flex items-baseline gap-3">
        <h1 className="text-2xl font-semibold">SARANA Transparency Dashboard</h1>
        <MockDataBadge />
      </header>

      <p className="text-sm leading-relaxed">
        Disaster aid in Sri Lanka, published so that anyone can check it. Figures here are
        aggregate only: no household, no individual and no officer is identifiable on this
        page.
      </p>

      <section className="text-sm">
        <h2 className="mb-2 font-medium">How this is verifiable</h2>
        <p className="leading-relaxed">
          Every ledger entry is hash-chained, and a Merkle root over each day is written to
          storage that cannot be altered afterwards, including by us. That root is
          published here and in a public feed. The <code>sarana-verify</code> tool checks
          the published figures against those roots using nothing but this public API, so
          the claim does not rest on trusting the operator.
        </p>
      </section>
    </main>
  );
}
