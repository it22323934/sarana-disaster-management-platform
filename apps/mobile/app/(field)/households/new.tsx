/**
 * Adding a household the register does not have.
 *
 * The escape hatch for the register's gaps, and it exists because of what happens without
 * it: an officer who cannot record an unregistered household records nothing, and the
 * households missing from the registry are disproportionately the ones with nothing.
 *
 * The record is marked provisional and given a visibly different reference (`PROV-...`), so
 * nobody downstream mistakes it for a registry code. It reconciles server-side on sync.
 */

import { useRouter } from 'expo-router';
import { useState } from 'react';

import { Button, Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { TextField } from '../../../src/components/TextField.js';
import { useLocale, useOffline, useSession } from '../../../src/providers/index.js';
import { useHouseholdRegister } from '../../../src/field/useFieldStore.js';

export default function NewHousehold() {
  const { t } = useLocale();
  const { db } = useOffline();
  const { session } = useSession();
  const router = useRouter();
  const register = useHouseholdRegister(db);

  const [name, setName] = useState('');
  const [contact, setContact] = useState('');
  const [members, setMembers] = useState('');
  const [failure, setFailure] = useState<string | null>(null);

  async function create() {
    if (!register || !db) return;
    try {
      const [context] = await db.select<{ gn_division_id: string; gn_division_code: string }>(
        "SELECT gn_division_id, gn_division_code FROM field_context WHERE id = 'this'",
      );

      const created = await register.createProvisional({
        gnDivisionId: context?.gn_division_id ?? '',
        gnDivisionCode: context?.gn_division_code ?? session?.gnDivisionCode ?? '',
        name: name.trim() || null,
        contact: contact.trim() || null,
        memberCount: members.trim() ? Number.parseInt(members, 10) : null,
      });

      // Straight into the assessment, because that is why the officer is creating it.
      router.replace({
        pathname: '/(field)/assessments/new',
        params: { household: created.localId, reference: created.referenceCode },
      });
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <Screen>
      <Heading>{t('field.household.createTitle')}</Heading>
      <Text muted size="sm">{t('field.household.createBody')}</Text>

      <TextField label={t('field.household.name')} value={name} onChange={setName} />
      <TextField
        label={t('field.household.contact')}
        value={contact}
        onChange={setContact}
        keyboardType="phone-pad"
      />
      {/* Said on the screen where the number is typed, not buried in a privacy page. */}
      <Text muted size="xs">{t('field.household.contactPrivate')}</Text>

      <TextField
        label={t('field.household.members')}
        value={members}
        onChange={setMembers}
        keyboardType="number-pad"
      />

      {failure ? (
        <Card>
          <Text>{failure}</Text>
        </Card>
      ) : null}

      <Card>
        <Text muted size="sm">{t('field.household.provisionalNote')}</Text>
      </Card>

      <Button label={t('field.household.create')} onPress={create} />
    </Screen>
  );
}
