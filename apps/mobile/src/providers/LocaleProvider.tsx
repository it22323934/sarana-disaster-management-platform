/**
 * Language, above everything else in the tree.
 *
 * Above the session provider, not below it: the language is chosen before login, because
 * the sign-in screen is itself a citizen-facing string. An app that asks for a phone
 * number in a language the user does not read has already failed.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { DEFAULT_LOCALE, initialLocale, translator, type Locale, type Translator } from '../i18n/index.js';

const STORAGE_KEY = 'sarana.locale';

interface LocaleContextValue {
  readonly locale: Locale;
  readonly t: Translator['t'];
  readonly setLocale: (locale: Locale) => void;
  /** True on a first launch where the device locale is not one SARANA speaks. */
  readonly promptForLocale: boolean;
  readonly dismissPrompt: () => void;
  /** False until the stored choice has been read. Nothing renders text before then. */
  readonly ready: boolean;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
  const [promptForLocale, setPrompt] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const stored = await AsyncStorage.getItem(STORAGE_KEY);
      if (cancelled) return;
      const choice = initialLocale({ stored });
      setLocaleState(choice.locale);
      setPrompt(choice.promptImmediately);
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    setPrompt(false);
    // Fire and forget. The choice is applied to the UI immediately; persisting it is not
    // something the user should wait on, and a failed write costs one tap next launch.
    void AsyncStorage.setItem(STORAGE_KEY, next);
  }, []);

  const value = useMemo<LocaleContextValue>(() => {
    const active = translator(locale);
    return {
      locale,
      t: active.t,
      setLocale,
      promptForLocale,
      dismissPrompt: () => setPrompt(false),
      ready,
    };
  }, [locale, promptForLocale, ready, setLocale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const value = useContext(LocaleContext);
  if (!value) throw new Error('useLocale must be used inside a LocaleProvider');
  return value;
}

/** The translator on its own, which is what most components want. */
export function useT(): Translator['t'] {
  return useLocale().t;
}
