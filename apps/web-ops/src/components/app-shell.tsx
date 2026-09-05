'use client';

/**
 * The console shell: header, navigation, gate banner.
 *
 * Navigation is filtered by scope, and that filtering is a convenience, not a control. A
 * user who types a URL for an area they do not hold reaches the page and every panel on
 * it returns 403 from the service, which is the answer that counts. Hiding the link keeps
 * the console honest about what this person can do; it is not what stops them.
 */

import { LanguageSwitcher, OfflineIndicator, cn } from '@sarana/ui';
import type { Locale } from '@sarana/ts-shared/i18n';
import { useTranslations } from 'next-intl';
import { useEffect, useState, type ReactNode } from 'react';

import { Link, usePathname, useRouter } from '../i18n/routing';
import type { PrincipalSummary } from '../lib/session';
import { DisasterSpine } from './disaster-spine';
import { PendingGates } from './pending-gates';

/**
 * A navigation entry and the scopes that make it useful.
 *
 * `scopes` is **any-of**, not all-of. An approver holds `entitlement:approve_ds` or
 * `entitlement:approve_district` and rarely both, and a link that demanded both would hide
 * from most of the people it is for.
 *
 * Every string here has to be a scope the platform actually issues, and getting that wrong
 * fails silently: `includes()` is simply false for everybody, the link never renders, and
 * a finished screen becomes unreachable from the navigation while working fine at its URL.
 * Two entries were wrong in exactly that way - `/approvals` named `entitlement:approve` and
 * `/admin` named `admin:write`, neither of which exists - so
 * `tests/auth/test_console_scopes.py` now parses this table and checks it against the
 * Python `Scope` enum. TypeScript cannot import that enum, so the check runs from the side
 * that owns the vocabulary.
 */
interface NavItem {
  readonly href: string;
  readonly labelKey: string;
  /** Empty means everyone signed in sees it. Any one of these is enough. */
  readonly scopes?: readonly string[];
}

const NAV: readonly NavItem[] = [
  { href: '/ops', labelKey: 'operations', scopes: ['incident:read'] },
  { href: '/ops/incidents', labelKey: 'incidents', scopes: ['incident:read'] },
  { href: '/ops/dispatch', labelKey: 'dispatch', scopes: ['dispatch:commit'] },
  { href: '/ops/alerts', labelKey: 'alerts', scopes: ['alert:read'] },
  { href: '/ops/forecast', labelKey: 'forecast', scopes: ['forecast:read'] },
  { href: '/ops/review', labelKey: 'reviewQueue', scopes: ['incident:verify'] },
  { href: '/field/assessments', labelKey: 'assessments', scopes: ['assessment:read'] },
  {
    href: '/approvals',
    labelKey: 'approvals',
    scopes: ['entitlement:approve_ds', 'entitlement:approve_district'],
  },
  { href: '/disbursements', labelKey: 'disbursements', scopes: ['disbursement:release'] },
  { href: '/grievances', labelKey: 'grievances', scopes: ['grievance:read'] },
  { href: '/audit', labelKey: 'audit', scopes: ['ledger:read'] },
  { href: '/admin', labelKey: 'admin', scopes: ['system:admin'] },
];

export interface AppShellProps {
  readonly locale: Locale;
  readonly principal: PrincipalSummary | null;
  readonly suppressGateBanner?: boolean;
  readonly children: ReactNode;
}

export function AppShell({
  locale,
  principal,
  suppressGateBanner = false,
  children,
}: AppShellProps) {
  const t = useTranslations();
  const nav = useTranslations('nav');
  const pathname = usePathname();
  const router = useRouter();
  const [online, setOnline] = useState(true);

  useEffect(() => {
    // `navigator.onLine` is read after mount, never during render: it differs between
    // server and client and would hydrate mismatched.
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, []);

  const held = new Set(principal?.scopes ?? []);
  const visible = NAV.filter(
    (item) => !item.scopes?.length || item.scopes.some((scope) => held.has(scope)),
  );

  return (
    <div className="flex min-h-screen flex-col bg-[var(--surface-base)] text-[var(--text-primary)]">
      {/* First focusable thing on the page. A dispatcher working keyboard-only should not
          have to tab through twelve navigation links to reach the queue. */}
      <a
        href="#console-main"
        className={cn(
          'sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[var(--z-toast)]',
          'focus:rounded-[var(--radius-default)] focus:bg-[var(--signal-500)] focus:px-4 focus:py-2',
          'focus:text-[var(--on-signal)]',
        )}
      >
        {t('app.skipToContent')}
      </a>

      <header className="border-b border-[var(--divider)]">
        <div className="flex flex-wrap items-center gap-3 px-4 py-2">
          <Link href="/ops" className="text-sm font-semibold">
            {t('app.name')}
          </Link>

          <div className="ml-auto flex items-center gap-3">
            <OfflineIndicator
              online={online}
              onlineLabel={t('common.online')}
              offlineLabel={t('common.offline')}
            />
            <LanguageSwitcher
              locale={locale}
              label={t('common.language')}
              onChange={(next) => {
                // `replace`, not `push`: switching language is not a place in history to
                // go back to, and a back button that toggles language is disorienting.
                router.replace(pathname, { locale: next });
              }}
            />
            {principal ? (
              <span className="text-2xs text-[var(--text-muted)]">{principal.displayName}</span>
            ) : null}
          </div>
        </div>

        <nav aria-label={nav('operations')} className="px-2">
          <ul className="flex flex-wrap items-center gap-1 pb-1">
            {visible.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'inline-flex min-h-[var(--touch-target-min)] items-center rounded-[var(--radius-default)]',
                      'px-3 text-sm transition-colors duration-[var(--motion-state)]',
                      // The rule under the label is the primary signal; the colour and
                      // weight reinforce it. Colour alone would not survive greyscale.
                      active
                        ? 'border-b-2 border-[var(--text-accent)] font-medium text-[var(--text-primary)]'
                        : 'border-b-2 border-transparent text-[var(--text-muted)] hover:bg-[var(--surface-raised)]',
                    )}
                  >
                    {nav(item.labelKey)}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>

      {/* The spine sits above the gate banner: the banner is about what is waiting now,
          the spine about where "now" sits in the event. It renders nothing between
          events, which is most of the time. */}
      <DisasterSpine locale={locale} compact />

      <PendingGates suppress={suppressGateBanner} />

      <main id="console-main" className="flex-1">
        {children}
      </main>
    </div>
  );
}
