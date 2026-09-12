/**
 * `/(field)/division` — my division: boundaries, forecast, active alerts.
 *
 * Everything here reads from the device. An officer standing in a cut-off division needs to
 * know what was forecast for it and what warnings went out, and the moment they most need
 * that is the moment the tower is congested.
 *
 * **The map is honest about what it has.** Tiles are cached for one division and the screen
 * says so, because a map that silently renders nothing outside a boundary looks broken, and
 * an officer who thinks the app is broken stops using it.
 */

import { useEffect, useState } from 'react';

import { Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { useLocale, useOffline, useSession } from '../../src/providers/index.js';
import { loadFieldContext, type FieldContext } from '../../src/field/useFieldStore.js';

interface CachedAlert {
  readonly id: string;
  readonly headline_si: string;
  readonly headline_ta: string;
  readonly headline_en: string;
  readonly severity: number;
  readonly effective_from: string;
  readonly effective_to: string | null;
}

export default function Division() {
  const { t, locale } = useLocale();
  const { db } = useOffline();
  const { session } = useSession();

  const [context, setContext] = useState<FieldContext | null>(null);
  const [alerts, setAlerts] = useState<CachedAlert[]>([]);

  useEffect(() => {
    if (!db) return;
    let cancelled = false;

    void (async () => {
      const [loaded, cached] = await Promise.all([
        loadFieldContext(db),
        db.select<CachedAlert>(
          'SELECT id, headline_si, headline_ta, headline_en, severity, effective_from, ' +
            'effective_to FROM alert_cache ORDER BY effective_from DESC LIMIT 20',
        ),
      ]);
      if (cancelled) return;
      setContext(loaded);
      // Active means inside its window right now, computed here rather than filtered in
      // SQL so the comparison uses the device clock the officer is reading.
      const now = Date.now();
      setAlerts(
        cached.filter(
          (alert) =>
            Date.parse(alert.effective_from) <= now &&
            (alert.effective_to === null || Date.parse(alert.effective_to) > now),
        ),
      );
    })();

    return () => {
      cancelled = true;
    };
  }, [db]);

  const headline = (alert: CachedAlert) =>
    locale === 'si' ? alert.headline_si : locale === 'ta' ? alert.headline_ta : alert.headline_en;

  return (
    <Screen>
      <Heading>{t('field.division.title')}</Heading>
      <Text muted size="sm">
        {t('field.home.division', {
          code: context?.gn_division_code ?? session?.gnDivisionCode ?? '',
        })}
      </Text>

      <Card>
        <Text weight="semibold">{t('field.division.boundaries')}</Text>
        {/* Stated, because a map that silently renders nothing outside its cache looks
            broken rather than bounded. */}
        <Text muted size="sm">{t('field.division.offlineMap')}</Text>
      </Card>

      <Card>
        <Text weight="semibold">{t('field.division.forecast')}</Text>
        {context?.hazard_event_name ? (
          <Text size="sm">{context.hazard_event_name}</Text>
        ) : (
          <Text muted size="sm">{t('field.division.noAlerts')}</Text>
        )}
      </Card>

      <Card>
        <Text weight="semibold">{t('field.division.alerts')}</Text>
        {alerts.length === 0 ? (
          <Text muted size="sm">{t('field.division.noAlerts')}</Text>
        ) : (
          alerts.map((alert) => (
            <Text key={alert.id} size="sm">
              {headline(alert)}
            </Text>
          ))
        )}
      </Card>
    </Screen>
  );
}
