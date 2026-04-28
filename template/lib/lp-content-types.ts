// ═════════════════════════════════════════════════════════════════════════
// LP Content schema (Phase 5) — the shape of the editable content for
// each LP. Stored as a JSONB blob in public.lp_content.content.
// ═════════════════════════════════════════════════════════════════════════

export type LpContent = {
  meta: {
    title: string              // HTML <title>
    description: string        // meta description
  }
  header: {
    company_name: string       // 株式会社ミライ工業
    logo_letter: string        // single char, fallback when logo_image is not set
    logo_image?: string        // URL to the actual company logo; takes precedence over logo_letter
    favicon_url?: string       // Square favicon URL (ideally 192×192). When set, used for browser tab
                               // icon, apple-touch-icon, and hiringOrganization.logo in JSON-LD.
                               // Mirrors how real company sites use a square icon mark (no wordmark)
                               // for favicons. Takes precedence over logo_image for all favicon uses.
  }
  hero: {
    label: string              // Recruiting 2026
    en_title: string           // "Recruitment" — the big paint-sweep text
    jp_tagline: string         // つくる力で、未来を変えていく。
    subtext: string            // supports \n
    bg_image: string           // URL
    cta_label: string          // 採用職種を見る
    cta_anchor: string         // #openings (usually)
  }
  about: {
    sub: string                // ミライ工業を知る
    photo: string              // URL
    headline: string           // supports <br>
    paragraphs: string[]       // 1-3 paragraphs
    button_label: string       // 私たちの強み
    button_anchor: string      // #strengths
  }
  strengths: {
    sub: string                // 選ばれ続ける3つの理由
    items: Array<{ title: string; body: string }>
  }
  data: {
    sub: string                // 数字で見るミライ工業
    items: Array<{ value: number; unit: string; label: string }>
  }
  voices: {
    sub: string                // 先輩たちのリアルな声
    items: Array<{ photo: string; dept: string; name: string; meta: string; quote: string }>
  }
  openings: {
    sub: string                // 現在募集中のポジション
    items: Array<{
      image: string
      badge: string
      title: string
      description: string
      detail?: JobDetail       // Optional job-detail page data
    }>
  }
  welfare: {
    sub: string                // 待遇・福利厚生
    items: Array<{ term: string; description: string }>
  }
  cta: {
    headline: string
    sub: string
    button_label: string
  }
  map_embed_src: string        // Google Maps iframe src
  map?: {                      // Structured address for JSON-LD / Google for Jobs
    region?: string            // 都道府県 e.g. "京都府"
    locality?: string          // 市区町村 e.g. "京都市中京区"
    street?: string            // 番地 e.g. "烏丸通四条上る"
    postal_code?: string       // 〒 e.g. "604-8301"
  }
  footer: {
    company_name: string
    tagline: string
    address: string            // supports <br>
    founded: string
    representative: string
    business: string
    website?: string           // e.g. "https://example.co.jp"
  }
  // Theme colors (optional, defaults to current palette if unset)
  theme?: {
    primary?: string           // --c1 (navy)
    accent?: string            // --c2 (orange)
    accent2?: string           // --c3 (amber)
  }
}

// Job detail page schema — optional per-opening extension enabling the
// dedicated /lp/[slug]/jobs/[index] detail pages (求人のポイント, 募集要項,
// 選考フロー, 社員紹介, 1日の流れ).
export type JobDetail = {
  en_title?: string                                   // big English title, e.g. "MANUFACTURING STAFF"
  tagline?: string                                    // main hero tagline
  intro?: string                                      // intro paragraph under the tagline
  hero_bg?: string                                    // dedicated background image for the detail-page hero; falls back to the opening card image if unset
  points?: Array<{ title: string }>                   // 求人のポイント — simple numbered highlights
  ideal_candidate?: Array<{ title: string }>          // 求める人物像 — ideal candidate bullet list
  requirements?: Array<{ term: string; description: string }>  // 募集要項
  selection_flow?: Array<{ title: string; description: string }>  // 選考フロー steps
  employee?: {
    photo: string
    dept: string
    joined: string
    name: string
    qa: Array<{ q: string; a: string }>
  }
  day_in_life?: Array<{ time: string; title: string; description: string }>
  // Google for Jobs / JSON-LD structured data fields
  // Google for Jobs / JSON-LD structured data fields
  direct_apply?: boolean         // Default true. Set false when apply flow redirects to an external
                                 // ATS — misrepresenting this as true is a Google policy violation
                                 // that can suppress the listing domain-wide.
  employment_type?: 'FULL_TIME' | 'PART_TIME' | 'CONTRACTOR' | 'TEMPORARY' | 'OTHER'
  posted_date?: string       // ISO date e.g. "2026-01-15". Set at creation/publish, not re-derived.
  valid_through?: string     // ISO date e.g. "2026-12-31"
  salary_amount?: number     // single-value salary (legacy; prefer salary_min/max)
  salary_min?: number        // min end of salary range e.g. 235000
  salary_max?: number        // max end of salary range e.g. 430000
  salary_unit?: 'MONTH' | 'YEAR' | 'HOUR' | 'DAY'
  salary_display?: string    // free-text e.g. "月給25万〜35万円"
  // Optional full HTML description override (admin-editable). When set, this
  // verbatim HTML is used as JobPosting.description. When unset, a structured
  // description is auto-composed from intro + detail.requirements + salary.
  description_html?: string
}

// Default theme — matches the current yamaguchi LP
export const DEFAULT_THEME = {
  primary: '#1B2B5A',
  accent: '#E85D3A',
  accent2: '#f59e0b',
}

// Blank template for new LPs
export function emptyLpContent(slug: string): LpContent {
  return {
    meta: { title: `採用情報｜${slug}`, description: '' },
    header: { company_name: slug, logo_letter: slug[0]?.toUpperCase() || 'A' },
    hero: {
      label: 'Recruiting 2026',
      en_title: 'Recruitment',
      jp_tagline: '',
      subtext: '',
      bg_image: '',
      cta_label: '採用職種を見る',
      cta_anchor: '#openings',
    },
    about: { sub: '', photo: '', headline: '', paragraphs: [''], button_label: '私たちの強み', button_anchor: '#strengths' },
    strengths: { sub: '', items: [] },
    data: { sub: '', items: [] },
    voices: { sub: '', items: [] },
    openings: { sub: '', items: [] },
    welfare: { sub: '', items: [] },
    cta: { headline: '', sub: '', button_label: 'エントリーする' },
    map_embed_src: '',
    footer: { company_name: slug, tagline: '', address: '', founded: '', representative: '', business: '' },
  }
}
