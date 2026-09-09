/**
 * `/(field)/households` — the division's register, offline, with its limits stated.
 *
 * Two things this screen does that a plain search box would not, and both come from the
 * register's design rather than from taste.
 *
 * **It says when a name search matched nothing *because of how the index works*.** The
 * register stores keyed hashes of whole name tokens, so `Per` cannot find `Perera`. An
 * empty list reads as "there is no such household" and would send an officer to create a
 * duplicate. `matchedBy: 'none'` is what lets the screen say the real thing instead.
 *
 * **It offers "add a household" as a first-class action, not a fallback.** The register has
 * gaps, and the households missing from it are disproportionately the ones with nothing. An
 * officer who cannot record an unregistered household will simply not record them.
 */

import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable } from 'react-native';

import { Button, Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { TextField } from '../../../src/components/TextField.js';
import { useLocale, useOffline, useSession } from '../../../src/providers/index.js';
import { useHouseholdRegister } from '../../../src/field/useFieldStore.js';
import type { Household } from '../../../src/field/household-register.js';

export default function HouseholdList() {
  const { t } = useLocale();
  const { db } = useOffline();
  const { session } = useSession();
  const router = useRouter();
  const register = useHouseholdRegister(db);

  const division = session?.gnDivisionCode ?? '';
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Household[]>([]);
  const [matchedBy, setMatchedBy] = useState<'reference' | 'name' | 'none'>('none');
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (!register) return;
    let cancelled = false;

    void (async () => {
      try {
        const found = await register.search(division, query);
        if (cancelled) return;
        setResults([...found.households]);
        setMatchedBy(found.matchedBy);
        setFailure(null);
      } catch (error) {
        // The register refuses rather than storing plaintext when no device key exists.
        // A visibly broken register is recoverable; an invisibly leaking one is not.
        if (!cancelled) setFailure(error instanceof Error ? error.message : String(error));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [register, division, query]);

  return (
    <Screen>
      <Heading>{t('field.household.title')}</Heading>

      <TextField
        label={t('field.household.search')}
        value={query}
        onChange={setQuery}
        autoCapitalize="none"
      />

      {failure ? (
        <Card>
          <Text>{failure}</Text>
        </Card>
      ) : null}

      {results.length === 0 && query.trim().length > 0 ? (
        <Card>
          <Text>{t('field.household.noResults')}</Text>
          {/* The honest explanation, not an empty list. */}
          {matchedBy === 'none' ? (
            <Text muted size="sm">{t('field.household.searchLimit')}</Text>
          ) : null}
        </Card>
      ) : null}

      {results.map((household) => (
        <Pressable
          key={household.localId}
          accessibilityRole="button"
          onPress={() =>
            router.push({
              pathname: '/(field)/assessments/new',
              params: { household: household.localId, reference: household.referenceCode },
            })
          }
        >
          <Card>
            <Text weight="medium">{household.name ?? household.referenceCode}</Text>
            <Text muted size="xs">
              {t('field.household.reference', { code: household.referenceCode })}
            </Text>
            {household.memberCount !== null ? (
              <Text muted size="xs">
                {t('field.household.members', { count: household.memberCount })}
              </Text>
            ) : null}
            {household.isProvisional ? (
              <Text size="xs">{t('field.household.provisionalBadge')}</Text>
            ) : null}
          </Card>
        </Pressable>
      ))}

      {/* A first-class action, at the bottom where it does not compete with the search but
          always visible. The register's gaps are the point of it. */}
      <Card>
        <Text weight="semibold">{t('field.household.createTitle')}</Text>
        <Text muted size="sm">{t('field.household.createBody')}</Text>
        <Button
          label={t('field.household.create')}
          variant="secondary"
          onPress={() => router.push('/(field)/households/new')}
        />
      </Card>
    </Screen>
  );
}
