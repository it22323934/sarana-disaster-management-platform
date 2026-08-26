// Mirrors packages/py-shared/sarana_shared/domain/localised.py::LocalisedText exactly.
// All three locales required and non-empty — no nullable variant, no single-string
// fallback, per docs/build-prompts/00-master-context.md's trilingual invariant.

import { z } from "zod";

export const localisedTextSchema = z.object({
  si: z.string().min(1),
  ta: z.string().min(1),
  en: z.string().min(1),
});

export type LocalisedText = z.infer<typeof localisedTextSchema>;
