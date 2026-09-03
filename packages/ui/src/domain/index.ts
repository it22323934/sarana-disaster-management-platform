/**
 * The components that know what SARANA is.
 *
 * Everything here encodes a rule from the platform rather than a visual preference: the
 * trilingual invariant, the reserved severity ramp, the two human gates, the fact that
 * every government feed is a mock, and the convention that a code is the identity while
 * a name is only a label.
 */

export {
  LanguageSwitcher,
  LocalisedText,
  TranslationCompleteness,
  type LanguageSwitcherProps,
  type LocalisedTextProps,
  type TranslationCompletenessProps,
} from './localised-text.js';
export {
  ImpactClassBadge,
  SeverityDot,
  SeverityPill,
  SeverityShapeMark,
  type ImpactClassBadgeProps,
  type SeverityDotProps,
  type SeverityPillProps,
  type SeverityShapeMarkProps,
} from './severity-pill.js';
export {
  HashDisplay,
  LKRAmount,
  ReferenceCode,
  RelativeTime,
  groupHash,
  type HashDisplayProps,
  type LKRAmountProps,
  type ReferenceCodeProps,
  type RelativeTimeProps,
} from './datum.js';
export {
  SpineNavButton,
  TimeSpine,
  type SpineMilestone,
  type SpineNavButtonProps,
  type TimeSpineProps,
} from './time-spine.js';
export {
  AuditTrail,
  ConfidenceMeter,
  MockDataBadge,
  OfflineIndicator,
  type AuditEntry,
  type AuditTrailProps,
  type ConfidenceBand,
  type ConfidenceMeterProps,
  type MockDataBadgeProps,
  type OfflineIndicatorProps,
} from './trust.js';
export {
  GATE_PERSISTENT_AFTER_SECONDS,
  GATE_PROMINENT_AFTER_SECONDS,
  PendingGateBanner,
  urgencyFor,
  type GateKind,
  type GateUrgency,
  type PendingGateBannerProps,
} from './pending-gate-banner.js';
export {
  GNDivisionPicker,
  type GNDivision,
  type GNDivisionPickerProps,
} from './gn-division-picker.js';
