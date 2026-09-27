import { Component } from '@angular/core';
import { LEGAL } from './legal-config';

// Versioned: bumping LEGAL.version asks every visitor to accept the updated Terms
// and Privacy Policy again (v1 was the disclaimer alone, before the documents existed).
const LEGAL_KEY = `micha_legal_ack_v${LEGAL.version}`;

/** The shell. Both pages own their own header/chrome, so this stays a bare outlet
 *  rather than a persistent top-nav bar — every extra fixed row here is a row taken
 *  from the chart on a phone, which is the thing this app spent a whole session
 *  clawing space back for. The legal footer below is the one deliberate exception:
 *  a compliance requirement, not a UI preference, so it overrides that principle —
 *  but stays in normal document flow (not `position:fixed`) rather than fighting
 *  the pages' own viewport-height layouts for it. */
@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css'],
})
export class AppComponent {
  readonly L = LEGAL;
  agreeChecked = false;

  // Per-browser, not per-account — there is no login in this app. Read once at
  // construction; `localStorage` can throw in a locked-down browser context
  // (private mode in some browsers, embedded webviews) — treat that as
  // "not yet accepted" rather than crashing the whole shell over a compliance
  // banner.
  legalAccepted = (() => {
    try {
      return localStorage.getItem(LEGAL_KEY) === '1';
    } catch {
      return false;
    }
  })();

  acceptLegal(): void {
    if (!this.agreeChecked) return;
    this.legalAccepted = true;
    try {
      localStorage.setItem(LEGAL_KEY, '1');
    } catch {
      // Best-effort. If storage is unavailable the modal will simply
      // reappear next visit — that fails toward showing the disclaimer
      // again, not toward silently skipping it.
    }
  }
}
