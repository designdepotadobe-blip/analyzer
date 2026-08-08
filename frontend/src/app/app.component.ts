import { Component } from '@angular/core';

/** The shell. Both pages own their own header/chrome, so this stays a bare outlet
 *  rather than a persistent top-nav bar — every extra fixed row here is a row taken
 *  from the chart on a phone, which is the thing this app spent a whole session
 *  clawing space back for. */
@Component({
  selector: 'app-root',
  template: `<router-outlet></router-outlet>`,
})
export class AppComponent {}
