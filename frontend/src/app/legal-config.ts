/**
 * The operator's details, used by the Terms of Use, Privacy Policy and
 * Accessibility Statement (legal-page.component.ts). ONE place to fill in.
 *
 * Every field marked [להשלמה] MUST be completed before the site goes public:
 * Israeli law requires the operator of a public website to be identifiable and
 * reachable — the Privacy Protection Law (the database owner and how to exercise
 * the right of access), the accessibility regulations (a named accessibility
 * coordinator with a phone number / email), and consumer protection (who the
 * user is contracting with). The texts are a template drafted from those
 * requirements; have them reviewed by an Israeli lawyer before launch.
 */
export const LEGAL = {
  /** Site / service name as shown to users. */
  siteName: 'Micha Stocks Analyzer',
  /** Legal name of the operator (person or company). */
  operatorName: '[להשלמה: שם המפעיל / החברה]',
  /** ח.פ. / ע.מ. / ת.ז. of the operator. */
  operatorId: '[להשלמה: ח.פ. / ע.מ.]',
  /** Postal address for legal notices. */
  address: '[להשלמה: כתובת למשלוח הודעות]',
  /** General contact email — also where privacy requests go. */
  email: '[להשלמה: כתובת דוא"ל ליצירת קשר]',
  /** Contact phone (required for the accessibility coordinator). */
  phone: '[להשלמה: טלפון]',
  /** Accessibility coordinator — required by the Equal Rights for Persons with
   *  Disabilities (Service Accessibility Adjustments) Regulations, 2013. */
  accessibilityCoordinator: '[להשלמה: שם רכז/ת הנגישות]',
  /** Privacy officer — Amendment 13 requires one for certain controllers; if one is
   *  appointed, name them here, otherwise leave as the general contact. */
  privacyContact: '[להשלמה: איש/אשת קשר לענייני פרטיות]',
  /** Hosting / infrastructure providers, disclosed in the privacy policy. */
  hosting: 'Railway Corp. (ארה"ב)',
  /** Date the documents were last updated (shown on each page). */
  lastUpdated: '27.09.2026',
  /** Bump this when the Terms/Privacy change materially: every visitor is asked to
   *  accept again (app.component.ts reads it into the acceptance key). */
  version: 2,
};
