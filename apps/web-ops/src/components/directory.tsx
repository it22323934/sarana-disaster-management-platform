'use client';

/**
 * `/admin` — the user directory and the role catalogue.
 *
 * The half of `/admin` the brief names that could not be built: core-api exposed no user
 * or role endpoint. `GET /admin/users` and `GET /admin/roles` closed it.
 *
 * Four decisions here, and three of them are about not making role administration feel
 * routine.
 *
 * **`mfa_enrolled` is on the row, not behind a detail view.** It is the question this
 * screen exists to answer during an incident: an approver with no second factor cannot
 * pass a gate, and finding that out when the gate refuses them is finding out too late.
 * It is rendered as a warning rather than a tick, because the absence is the actionable
 * state.
 *
 * **A role that carries a human gate is marked, everywhere it appears.** Granting
 * `DISTRICT_APPROVER` is granting `disbursement:release` and `dispatch:commit`. It is the
 * quietest privilege escalation on this platform and the screen refuses to let it look
 * like any other row.
 *
 * **Scopes are shown from the platform's own table, not from a description.** `GET /admin/roles`
 * derives them from `ROLE_SCOPES` - the same mapping `require()` authorises against - so a
 * government reviewer reading this screen is reading what is enforced rather than what
 * somebody wrote down about it.
 *
 * **Granting needs a reason and a second factor, and the console collects both.** The
 * server refuses without them; making the button unreachable means the refusal never
 * happens, which is the same pattern as the anomaly disposition note.
 */

import {
  Badge,
  Button,
  DataTable,
  DialogContent,
  DialogRoot,
  DialogTrigger,
  EmptyState,
  Input,
  RelativeTime,
  Select,
  Skeleton,
  Textarea,
  cn,
} from '@sarana/ui';
import { localised, type Locale } from '@sarana/ts-shared/i18n';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { gatewayFetch } from '../lib/gateway-client';
import { useDirectoryUsers, useRoles } from '../lib/queries';
import { SCOPE_TYPES, type DirectoryUser, type RoleDefinition, type ScopeType } from '../lib/schemas';
import { stepUp } from '../lib/auth-actions';
import { ErrorPanel } from './degraded';

const TOTP_LENGTH = 6;

/** The code shape each scope level requires, mirrored from the database CHECK. */
const SCOPE_PATTERNS: Record<ScopeType, RegExp> = {
  NATIONAL: /^LK$/,
  DISTRICT: /^LK-\d{2}$/,
  DS: /^LK-\d{2}-\d{2}$/,
  GN: /^LK-\d{2}-\d{2}-\d{3}$/,
};

/**
 * Whether this code is the right shape for this level.
 *
 * Checked here only so the operator is told before the request. The database CHECK is the
 * authority - `scope_code_matches_type` - and it refuses a mismatch whatever this says.
 */
export function scopeCodeValid(scopeType: ScopeType, code: string): boolean {
  return SCOPE_PATTERNS[scopeType].test(code.trim());
}

export function UserDirectory() {
  const t = useTranslations('admin');
  const locale = useLocale() as Locale;

  const [roleFilter, setRoleFilter] = useState('');
  const [query, setQuery] = useState('');
  const users = useDirectoryUsers(roleFilter || undefined, query || undefined);
  const roles = useRoles();

  if (users.isError) {
    return <ErrorPanel error={users.error} />;
  }

  const gateRoles = new Set(
    (roles.data ?? []).filter((role) => role.grants_human_gate).map((role) => role.code),
  );

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-[var(--text-muted)]">{t('usersHint')}</p>

      <div className="flex flex-wrap items-end gap-4">
        <Input
          label={t('searchUsers')}
          description={t('searchUsersHint')}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Select
          label={t('filterByRole')}
          placeholder={t('allRoles')}
          value={roleFilter}
          onValueChange={setRoleFilter}
          options={(roles.data ?? []).map((role) => ({
            value: role.code,
            label: `${localised(role.name, locale)} (${role.code})`,
          }))}
        />
      </div>

      {users.isPending ? (
        <Skeleton className="h-64" />
      ) : (
        <DataTable<DirectoryUser>
          caption={t('users')}
          rows={users.data ?? []}
          rowKey={(user) => user.id}
          height="calc(100vh - 26rem)"
          empty={<EmptyState title={t('noUsers')} description={t('noUsersHint')} />}
          columns={[
            {
              key: 'name',
              header: t('userName'),
              width: '16rem',
              cell: (user) => (
                <span className="flex flex-col">
                  <span className="text-sm">{user.full_name ?? '—'}</span>
                  <span className="text-2xs text-[var(--text-muted)]">{user.email ?? '—'}</span>
                </span>
              ),
            },
            {
              key: 'status',
              header: t('userStatus'),
              width: '9rem',
              cell: (user) => (
                <Badge tone={user.status === 'ACTIVE' ? 'verified' : 'neutral'}>
                  {user.status}
                </Badge>
              ),
            },
            {
              key: 'mfa',
              header: t('secondFactor'),
              width: '13rem',
              // The absence is the actionable state, so it is the one that is marked.
              cell: (user) =>
                user.mfa_enrolled ? (
                  <span className="text-2xs text-[var(--verified)]">{t('mfaEnrolled')}</span>
                ) : (
                  <Badge tone="pending">{t('mfaMissing')}</Badge>
                ),
            },
            {
              key: 'grants',
              header: t('grants'),
              cell: (user) => (
                <span className="flex flex-wrap gap-1">
                  {user.grants.length === 0 ? (
                    <span className="text-2xs text-[var(--text-muted)]">{t('noGrants')}</span>
                  ) : (
                    user.grants.map((grant) => (
                      <Badge
                        key={grant.grant_id}
                        tone={gateRoles.has(grant.role_code) ? 'pending' : 'neutral'}
                      >
                        {grant.role_code}
                        {' · '}
                        <span className="font-mono">{grant.scope_code}</span>
                      </Badge>
                    ))
                  )}
                </span>
              ),
            },
            {
              key: 'lastLogin',
              header: t('lastLogin'),
              width: '11rem',
              cell: (user) =>
                user.last_login_at ? (
                  <RelativeTime value={user.last_login_at} />
                ) : (
                  <span className="text-2xs text-[var(--text-muted)]">{t('neverSignedIn')}</span>
                ),
            },
            {
              key: 'manage',
              header: t('manage'),
              width: '10rem',
              cell: (user) => (
                <GrantDialog
                  user={user}
                  roles={roles.data ?? []}
                  onChanged={() => void users.refetch()}
                />
              ),
            },
          ]}
        />
      )}
    </div>
  );
}

/**
 * Grant or revoke a role.
 *
 * A dialogue rather than an inline control. Role administration is not a thing to do by
 * accident while scanning a table, and the second factor collected inside it is the same
 * one the two gates ask for — because a role grant is the path to both.
 */
function GrantDialog({
  user,
  roles,
  onChanged,
}: {
  readonly user: DirectoryUser;
  readonly roles: readonly RoleDefinition[];
  readonly onChanged: () => void;
}) {
  const t = useTranslations('admin');
  const errors = useTranslations('errors');
  const locale = useLocale() as Locale;

  const [roleCode, setRoleCode] = useState('');
  const [scopeType, setScopeType] = useState<ScopeType>('DISTRICT');
  const [scopeCode, setScopeCode] = useState('');
  const [reason, setReason] = useState('');
  const [totp, setTotp] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<unknown>(null);

  const chosen = roles.find((role) => role.code === roleCode) ?? null;
  const codeValid = scopeCodeValid(scopeType, scopeCode);
  const totpComplete = /^\d{6}$/.test(totp);
  const canGrant =
    roleCode !== '' && codeValid && reason.trim().length >= 3 && totpComplete && busy === null;

  async function withStepUp(action: () => Promise<unknown>, label: string): Promise<void> {
    setBusy(label);
    setFailure(null);
    try {
      const stepped = await stepUp(totp);
      if (!stepped.ok) {
        setFailure(new Error(stepped.message ?? errors('stepUpRequired')));
        return;
      }
      await action();
      setTotp('');
      setReason('');
      onChanged();
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(null);
    }
  }

  return (
    <DialogRoot>
      <DialogTrigger asChild>
        <Button variant="secondary" size="sm">
          {t('manage')}
        </Button>
      </DialogTrigger>
      <DialogContent
        title={t('manageTitle', { name: user.full_name ?? user.email ?? user.id.slice(0, 8) })}
        description={t('manageHint')}
      >
        <div className="flex flex-col gap-4">
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">{t('currentGrants')}</h3>
            {user.grants.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">{t('noGrants')}</p>
            ) : (
              <ul className="flex flex-col gap-1">
                {user.grants.map((grant) => (
                  <li key={grant.grant_id} className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge tone="neutral">{grant.role_code}</Badge>
                    <span data-sarana-datum="" className="font-mono">
                      {grant.scope_type} {grant.scope_code}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      busy={busy === grant.grant_id}
                      busyLabel={t('revoke')}
                      disabled={!totpComplete || busy !== null}
                      onClick={() =>
                        withStepUp(
                          () =>
                            gatewayFetch(`admin/users/${user.id}/roles/${grant.grant_id}`, {
                              method: 'DELETE',
                            }),
                          grant.grant_id,
                        )
                      }
                    >
                      {t('revoke')}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="flex flex-col gap-3 border-t border-[var(--divider)] pt-4">
            <h3 className="text-sm font-medium">{t('grantRole')}</h3>

            <Select
              label={t('roleCode')}
              placeholder={t('allRoles')}
              value={roleCode}
              onValueChange={setRoleCode}
              options={roles.map((role) => ({
                value: role.code,
                label: `${localised(role.name, locale)} (${role.code})`,
              }))}
            />

            {/* What this grant actually confers, before it is made. A role code is a name;
                the scopes are the thing. */}
            {chosen ? (
              <div
                className={cn(
                  'flex flex-col gap-1 rounded-[var(--radius-default)] border px-3 py-2 text-2xs',
                  chosen.grants_human_gate
                    ? 'border-[var(--sev-3-border)] bg-[var(--sev-3-bg)] text-[var(--sev-3-fg)]'
                    : 'border-[var(--divider)] text-[var(--text-muted)]',
                )}
              >
                {chosen.grants_human_gate ? (
                  <p className="font-semibold">{t('humanGateWarning')}</p>
                ) : null}
                <p data-sarana-datum="" className="font-mono">
                  {chosen.scopes.join(' · ')}
                </p>
              </div>
            ) : null}

            <Select
              label={t('grantLevel')}
              value={scopeType}
              onValueChange={(value) => setScopeType(value as ScopeType)}
              options={SCOPE_TYPES.map((value) => ({ value, label: value }))}
            />

            <Input
              label={t('grantArea')}
              description={t('grantAreaHint')}
              datum
              value={scopeCode}
              onChange={(event) => setScopeCode(event.target.value.toUpperCase())}
              error={scopeCode.length > 0 && !codeValid ? t('grantAreaInvalid') : undefined}
            />

            {/* A reason, stored with the grant. A permission change nobody can explain
                afterwards is one nobody can review. */}
            <Textarea
              label={t('grantReason')}
              description={t('grantReasonHint')}
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={500}
            />

            <Input
              label={t('totpLabel')}
              description={t('totpHint')}
              inputMode="numeric"
              autoComplete="one-time-code"
              datum
              maxLength={TOTP_LENGTH}
              value={totp}
              onChange={(event) =>
                setTotp(event.target.value.replace(/\D/g, '').slice(0, TOTP_LENGTH))
              }
            />

            {failure ? <ErrorPanel error={failure} /> : null}

            <Button
              variant="primary"
              disabled={!canGrant}
              busy={busy === 'grant'}
              busyLabel={t('grantSubmit')}
              onClick={() =>
                withStepUp(
                  () =>
                    gatewayFetch(`admin/users/${user.id}/roles`, {
                      method: 'POST',
                      body: {
                        role_code: roleCode,
                        scope_type: scopeType,
                        scope_code: scopeCode.trim(),
                        reason: reason.trim(),
                      },
                      idempotencyKey: `grant-${user.id}-${roleCode}-${scopeCode.trim()}`,
                    }),
                  'grant',
                )
              }
            >
              {t('grantSubmit')}
            </Button>
          </section>
        </div>
      </DialogContent>
    </DialogRoot>
  );
}

/**
 * The role catalogue.
 *
 * Read-only, and it has to be: a role is a bundle of scopes defined in
 * `sarana_shared.auth.scopes` and enforced from there. A console that could edit one would
 * be editing the authorisation model at run time, and the flat explicit mapping exists
 * precisely so a government IT reviewer can read what each role does without following
 * inheritance. This screen is that reading, rendered.
 */
export function RoleCatalogue() {
  const t = useTranslations('admin');
  const locale = useLocale() as Locale;
  const roles = useRoles();

  if (roles.isPending) return <Skeleton className="h-64" />;
  if (roles.isError) return <ErrorPanel error={roles.error} />;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-[var(--text-muted)]">{t('rolesHint')}</p>
      <ul className="flex flex-col gap-3">
        {(roles.data ?? []).map((role) => (
          <li
            key={role.id}
            data-role-code={role.code}
            className={cn(
              'flex flex-col gap-2 rounded-[var(--radius-default)] border p-4',
              role.grants_human_gate
                ? 'border-[var(--pending)] bg-[var(--surface-card)]'
                : 'border-[var(--divider)] bg-[var(--surface-card)]',
            )}
          >
            <header className="flex flex-wrap items-baseline gap-3">
              <h3 className="text-sm font-medium">{localised(role.name, locale)}</h3>
              <span data-sarana-datum="" className="font-mono text-2xs text-[var(--text-muted)]">
                {role.code}
              </span>
              {role.grants_human_gate ? (
                <Badge tone="pending">{t('humanGate')}</Badge>
              ) : null}
              <span className="ml-auto text-2xs text-[var(--text-muted)]">
                {t('scopeCount', { count: role.scopes.length })}
              </span>
            </header>
            <p data-sarana-datum="" className="font-mono text-2xs text-[var(--text-muted)]">
              {role.scopes.join(' · ')}
            </p>
          </li>
        ))}
      </ul>
      <p className="text-2xs text-[var(--text-muted)]">{t('rolesReadOnly')}</p>
    </div>
  );
}
