/** Sector names as the data provider sends them → how the app says them. */
export const SECTOR_HE: { [k: string]: string } = {
  'Technology': 'טכנולוגיה',
  'Healthcare': 'בריאות',
  'Financial Services': 'פיננסים',
  'Consumer Cyclical': 'צריכה מחזורית',
  'Consumer Defensive': 'צריכה בסיסית',
  'Communication Services': 'תקשורת',
  'Industrials': 'תעשייה',
  'Energy': 'אנרגיה',
  'Basic Materials': 'חומרי גלם',
  'Real Estate': 'נדל"ן',
  'Utilities': 'תשתיות',
};

export function sectorHe(s: string | null | undefined): string {
  return s ? (SECTOR_HE[s] || s) : '';
}
