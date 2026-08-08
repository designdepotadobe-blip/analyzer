import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { FormsModule } from '@angular/forms';
import { HttpClientModule } from '@angular/common/http';
import { RouterModule, Routes } from '@angular/router';

import { AppComponent } from './app.component';
import { AnalyzerPageComponent } from './analyzer-page.component';
import { RadarPageComponent } from './radar-page.component';
import { PortfolioPageComponent } from './portfolio-page.component';
import { ChartComponent } from './chart.component';
import { StockQuicklookComponent } from './stock-quicklook.component';

// Three pages, one shell (`AppComponent` is just `<router-outlet>`). The analyzer
// stays at '' — it's the app's front door, same as before routing existed. Radar
// and Portfolio each live at their own address so they're linkable, have their
// own back-button behaviour, and don't fight the analyzer's own state (a big scan
// running alongside a chart re-render was the alternative).
const routes: Routes = [
  { path: '', component: AnalyzerPageComponent },
  { path: 'radar', component: RadarPageComponent },
  { path: 'portfolio', component: PortfolioPageComponent },
  { path: '**', redirectTo: '' },
];

@NgModule({
  declarations: [
    AppComponent, AnalyzerPageComponent, RadarPageComponent, PortfolioPageComponent, ChartComponent,
    StockQuicklookComponent,
  ],
  imports: [
    BrowserModule,
    FormsModule,
    HttpClientModule,
    RouterModule.forRoot(routes, { scrollPositionRestoration: 'enabled' }),
  ],
  bootstrap: [AppComponent],
})
export class AppModule {}
