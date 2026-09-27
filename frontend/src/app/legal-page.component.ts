import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subscription } from 'rxjs';
import { LEGAL } from './legal-config';

/** The three documents a public Israeli website is expected to carry — Terms of
 *  Use, Privacy Policy (Privacy Protection Law incl. Amendment 13) and the
 *  Accessibility Statement (Equal Rights for Persons with Disabilities regulations,
 *  IS 5568). One component, `/legal/:doc`, so every document shares the same
 *  header, navigation between them and the operator details from legal-config. */
@Component({
  selector: 'app-legal-page',
  templateUrl: './legal-page.component.html',
  styleUrls: ['./legal-page.component.css'],
})
export class LegalPageComponent implements OnInit, OnDestroy {
  readonly L = LEGAL;
  doc: 'terms' | 'privacy' | 'accessibility' = 'terms';
  private sub?: Subscription;

  readonly titles: { [k: string]: string } = {
    terms: 'תנאי שימוש',
    privacy: 'מדיניות פרטיות',
    accessibility: 'הצהרת נגישות',
  };

  constructor(private route: ActivatedRoute) {}

  ngOnInit(): void {
    this.sub = this.route.paramMap.subscribe((p) => {
      const d = p.get('doc');
      this.doc = d === 'privacy' || d === 'accessibility' ? d : 'terms';
      document.title = `${this.titles[this.doc]} — ${LEGAL.siteName}`;
    });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
    document.title = LEGAL.siteName;
  }
}
