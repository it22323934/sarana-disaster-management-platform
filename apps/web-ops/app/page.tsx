import { MockDataBadge } from '@sarana/ui';

/**
 * The console shell.
 *
 * The common operating picture, the incident queue, the two human-gate dialogs and the
 * approval chain are built in a later step. This page exists so the app boots, proves
 * the workspace wiring end to end, and states plainly what the platform is.
 */
export default function Home() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-10">
      <header className="flex items-baseline gap-3">
        <h1 className="text-2xl font-semibold">SARANA Operations Console</h1>
        <MockDataBadge source="all government feeds" />
      </header>

      <p className="text-sm leading-relaxed">
        Multi-hazard disaster response and resilience for Sri Lanka. Every government and
        telco system behind this console is a mock. No live integration exists with the
        Department of Meteorology, NBRO, the DMC, the household registry, NIC
        verification, any bank disbursement rail, or any telco gateway.
      </p>

      <section className="text-sm">
        <h2 className="mb-2 font-medium">Two mandatory human gates</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>Committing a life-safety dispatch action</li>
          <li>Releasing a financial disbursement</li>
        </ul>
        <p className="mt-2 text-xs opacity-75">
          Everything else runs autonomously. There is no flag that bypasses either gate.
        </p>
      </section>
    </main>
  );
}
