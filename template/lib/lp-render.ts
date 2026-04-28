import type { LpContent } from './lp-content-types'
import { DEFAULT_THEME } from './lp-content-types'
import { getGoogleVerificationTokens } from './lp-domains'
import { composeJobDescriptionHtml } from './lp-description'

// ─── SEO helpers ──────────────────────────────────────────────────────────

// Tells Google's snippet engine to use the largest available image preview
// and unbounded text snippet. Without this, search results often show a
// shrunken thumbnail and a truncated description. Pure win.
const ROBOTS_SNIPPET_META =
  '<meta name="robots" content="max-image-preview:large,max-snippet:-1,max-video-preview:-1">'

function renderVerificationMetas(slug: string): string {
  return getGoogleVerificationTokens(slug)
    .map((t) => `<meta name="google-site-verification" content="${esc(t)}" />`)
    .join('\n')
}

// Default JobPosting validThrough = posted_date + 90 days. Google for Jobs
// drops postings ~30 days after datePosted unless validThrough exists, so
// emitting a stable default keeps listings in the dedicated Jobs UI longer
// without making the value churn on every save (which would look spammy).
function addDaysIso(isoDate: string, days: number): string | null {
  const t = Date.parse(isoDate)
  if (!Number.isFinite(t)) return null
  return new Date(t + days * 86400_000).toISOString().split('T')[0]
}

// Escape HTML for safe interpolation into the template
function esc(s: unknown): string {
  if (s == null) return ''
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

// Like esc() but allows <br> (used for fields where we want line breaks)
function escBr(s: unknown): string {
  return esc(s).replace(/&lt;br\s*\/?&gt;/gi, '<br>')
}

// Render the LP HTML. Based on yamaguchi's original template.
export function renderLpHtml(slug: string, c: LpContent, canonicalBase: string = `https://nippo-sync.vercel.app/lp/${slug}`): string {
  const theme = { ...DEFAULT_THEME, ...(c.theme || {}) }
  const strengthsHtml = (c.strengths.items || []).map((s, i) => `
      <div class="str-card">
        <div class="str-num">${String(i + 1).padStart(2, '0')}</div>
        <h3>${esc(s.title)}</h3>
        <p>${esc(s.body)}</p>
      </div>`).join('\n')

  const dataHtml = (c.data.items || []).map((d) => `
      <div class="data-pill"><div><div class="data-val"><span class="count-up" data-target="${Number(d.value) || 0}">0</span></div><div class="data-label">${esc(d.label)}</div></div><div class="data-unit">${esc(d.unit)}</div></div>`).join('\n')

  const voicesHtml = (c.voices.items || []).map((v) => `
      <div class="voice-card">
        <img src="${esc(v.photo)}" alt="${esc(v.name)}">
        <div class="voice-body">
          <div class="voice-dept">${esc(v.dept)}</div>
          <h3 class="voice-name">${esc(v.name)}</h3>
          <p class="voice-meta">${esc(v.meta)}</p>
          <p class="voice-quote">${esc(v.quote)}</p>
        </div>
      </div>`).join('\n')

  const openingsHtml = (c.openings.items || []).map((o, i) => `
      <div class="open-card">
        <img src="${esc(o.image)}" alt="${esc(o.title)}">
        <div class="open-info">
          <span class="open-badge">${esc(o.badge)}</span>
          <h3 class="open-title">${esc(o.title)}</h3>
          <p class="open-desc">${esc(o.description)}</p>
          <a href="${canonicalBase}/jobs/${i}" class="open-link">詳しく見る →</a>
        </div>
      </div>`).join('\n')

  const welfareHtml = (c.welfare.items || []).map((w) => `
      <div class="welfare-item"><dt>${esc(w.term)}</dt><dd>${escBr(w.description)}</dd></div>`).join('\n')

  const aboutParagraphsHtml = (c.about.paragraphs || []).filter(Boolean).map((p) => `<p>${esc(p)}</p>`).join('\n        ')

  const navLinks = [
    { href: '#about', label: '会社を知る' },
    { href: '#strengths', label: '強み' },
    { href: '#data', label: '数字で見る' },
    { href: '#voices', label: '先輩の声' },
    { href: '#openings', label: '採用職種' },
    { href: '#welfare', label: '待遇' },
  ]

  return `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="${esc(c.meta.description)}">
<title>${esc(c.meta.title)}</title>
<link rel="canonical" href="${canonicalBase}">
${ROBOTS_SNIPPET_META}
${renderVerificationMetas(slug)}
<!-- Open Graph / Twitter Card metadata for link unfurling -->
<meta property="og:type" content="website">
<meta property="og:url" content="${canonicalBase}">
<meta property="og:title" content="${esc(c.meta.title)}">
<meta property="og:description" content="${esc(c.meta.description)}">
<meta property="og:site_name" content="${esc(c.header.company_name || c.footer.company_name || '')}">
<meta property="og:locale" content="ja_JP">
${c.hero?.bg_image ? `<meta property="og:image" content="${esc(c.hero.bg_image)}">` : ''}
${c.header?.favicon_url
  ? `<link rel="icon" type="image/png" sizes="32x32" href="${esc(c.header.favicon_url)}">
<link rel="icon" type="image/png" sizes="192x192" href="${esc(c.header.favicon_url)}">
<link rel="apple-touch-icon" sizes="180x180" href="${esc(c.header.favicon_url)}">`
  : c.header?.logo_image
  ? `<link rel="icon" type="image/png" href="${esc(c.header.logo_image)}">`
  : ''}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(c.meta.title)}">
<meta name="twitter:description" content="${esc(c.meta.description)}">
${c.hero?.bg_image ? `<meta name="twitter:image" content="${esc(c.hero.bg_image)}">` : ''}
<script type="application/ld+json">${JSON.stringify({
  '@context': 'https://schema.org',
  '@type': 'Organization',
  name: c.header.company_name || c.footer.company_name || slug,
  url: canonicalBase,
  ...(c.header.favicon_url ?? c.header.logo_image ? { logo: c.header.favicon_url ?? c.header.logo_image } : {}),
  ...(c.footer?.website ? { sameAs: [c.footer.website] } : {}),
}).replace(/</g, '\\u003c')}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Noto+Sans+JP:wght@400;500;700;900&family=Outfit:wght@600;800;900&display=swap" rel="stylesheet">
<style>
:root{--c1:${theme.primary};--c2:${theme.accent};--c3:${theme.accent2};--c2-dark:#c94a2b;--ct:#1a1a2e;--ct2:#5a5a72;--cbg:#FAFBFD;--cbg2:#F0F2F7;--fen:"Outfit",sans-serif;--fjp:"Noto Sans JP",sans-serif;--fi:"Inter",sans-serif;--mw:1200px;--hh:72px;--rad:12px;--sh:0 8px 32px rgba(27,43,90,.07)}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--fjp);color:var(--ct);background:#fff;line-height:1.85;letter-spacing:.03em;-webkit-font-smoothing:antialiased;overflow-x:hidden}
a{text-decoration:none;color:inherit;transition:.25s}img{max-width:100%;height:auto;display:block}
.fade-in{opacity:0;transform:translateY(30px);transition:.8s ease}.is-visible{opacity:1;transform:translateY(0)}
.wrap{max-width:var(--mw);margin:0 auto;padding:0 32px}
.block{padding:140px 0;position:relative}
.block--alt{background:var(--cbg2)}
.anime-txt{font-family:var(--fen);font-weight:900;font-size:clamp(3.5rem,9vw,7.5rem);letter-spacing:-0.025em;line-height:.95;background-image:url('https://mgc-pass-proxy.duckdns.org/img/text_back.png?v=3');background-size:200% 100%;background-repeat:no-repeat;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:rgba(0,0,0,0);display:inline-block;transition:1.1s background-position-x;transition-timing-function:linear;background-position-x:300%;text-transform:uppercase}
.anime-txt.anime{background-position-x:0%}
.sec-head{margin-bottom:70px}
.sec-en{font-family:var(--fen);font-weight:900;font-size:clamp(2.5rem,5.5vw,4.5rem);letter-spacing:-.02em;line-height:1;color:var(--c1);display:block;margin-bottom:14px;text-transform:uppercase}
.sec-head .jp-sub{font-size:1.05rem;font-weight:700;color:var(--c1);letter-spacing:.08em;display:flex;align-items:center;gap:14px}
.sec-head .jp-sub::before{content:"";width:32px;height:2px;background:var(--c2)}
.btn-main{display:inline-flex;align-items:center;gap:8px;padding:14px 40px;background:var(--c2);color:#fff;font-size:.95rem;font-weight:700;border-radius:var(--rad);letter-spacing:.06em;transition:.25s;cursor:pointer;border:none}
.btn-main:hover{background:var(--c2-dark);transform:translateY(-2px)}
.btn-ghost{display:inline-block;padding:10px 28px;border:1.5px solid var(--c1);color:var(--c1);border-radius:var(--rad);font-size:.88rem;font-weight:600}
.btn-ghost:hover{background:var(--c1);color:#fff}
.hdr{position:fixed;top:0;left:0;width:100%;height:var(--hh);background:rgba(255,255,255,.97);backdrop-filter:blur(12px);z-index:1000;display:flex;align-items:center;justify-content:space-between;padding:0 32px;border-bottom:1px solid rgba(27,43,90,.06)}
.hdr-logo{font-family:var(--fjp);font-weight:900;font-size:1.15rem;color:var(--c1);display:flex;align-items:center;gap:10px}
.hdr-logo-icon{width:34px;height:34px;background:linear-gradient(135deg,var(--c1),var(--c2));border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-family:var(--fen);font-weight:800;font-size:1rem}.hdr-logo-icon.has-img{background:transparent;padding:2px;overflow:hidden;width:auto;min-width:34px;height:34px}.hdr-logo-icon.has-img img{height:100%;width:auto;max-width:120px;object-fit:contain;display:block}
.hdr-nav{display:flex;gap:28px;align-items:center}
.hdr-nav a{font-size:.85rem;font-weight:600;color:var(--ct2);font-family:var(--fi)}
.hdr-nav a:hover{color:var(--c2)}
.hdr-nav .hdr-cta{background:var(--c1);color:#fff;padding:9px 22px;border-radius:8px;font-weight:700;font-size:.82rem;letter-spacing:.05em}
.hdr-nav .hdr-cta:hover{background:var(--c2);color:#fff}
.hamburger{display:none;width:36px;height:36px;background:none;border:none;cursor:pointer;position:relative;z-index:1002}
.hamburger span{position:absolute;right:0;width:26px;height:2px;background:var(--c1);transition:.3s}
.hamburger span:nth-child(1){top:10px}.hamburger span:nth-child(2){top:17px;width:18px}.hamburger span:nth-child(3){top:24px}
.hamburger.is-active span:nth-child(1){top:17px;transform:rotate(45deg);width:26px}
.hamburger.is-active span:nth-child(2){opacity:0}
.hamburger.is-active span:nth-child(3){top:17px;transform:rotate(-45deg);width:26px}
.mob-nav{position:fixed;top:0;right:-100%;width:100%;height:100vh;background:#fff;z-index:1001;transition:.4s cubic-bezier(.77,0,.175,1);display:flex;flex-direction:column;justify-content:center;align-items:center;gap:28px}
.mob-nav.is-active{right:0}
.mob-nav a{font-size:1.15rem;font-weight:700;color:var(--c1)}
.mob-close{position:absolute;top:18px;right:18px;width:36px;height:36px;border:none;background:none;cursor:pointer}
.mob-close span{position:absolute;width:26px;height:2px;background:var(--c1);left:5px;top:17px}
.mob-close span:nth-child(1){transform:rotate(45deg)}
.mob-close span:nth-child(2){transform:rotate(-45deg)}
.hero{height:100vh;min-height:680px;position:relative;display:flex;align-items:center;overflow:hidden}
.hero-bg{position:absolute;inset:0;background:url('${esc(c.hero.bg_image)}') center/cover no-repeat;animation:slowZoom 30s ease-in-out infinite alternate}
@keyframes slowZoom{0%{transform:scale(1.08)}100%{transform:scale(1)}}
.hero-overlay{position:absolute;inset:0;background:linear-gradient(160deg,rgba(255,255,255,.92) 0%,rgba(255,255,255,.65) 45%,rgba(232,93,58,.12) 100%)}
.hero-inner{position:relative;z-index:2;max-width:var(--mw);margin:0 auto;padding:0 32px;width:100%}
.hero-label{font-family:var(--fi);font-size:.85rem;font-weight:700;color:var(--c2);letter-spacing:.25em;text-transform:uppercase;margin-bottom:24px;display:flex;align-items:center;gap:14px}
.hero-label::before{content:"";width:48px;height:2px;background:var(--c2)}
.hero-title-wrap{margin-bottom:32px}
.hero-title-wrap .anime-txt{font-size:clamp(4rem,11vw,9.5rem);display:block;line-height:.92}
.hero-jp{font-size:clamp(1.4rem,2.4vw,1.9rem);font-weight:900;color:var(--c1);margin-top:18px;line-height:1.45;letter-spacing:.04em}
.hero-sub{font-size:1rem;color:var(--ct2);font-weight:500;line-height:1.85;margin-bottom:36px;max-width:520px}
.about-grid{display:grid;grid-template-columns:1fr 1fr;gap:60px;align-items:center}
.about-photo img{border-radius:var(--rad);box-shadow:var(--sh)}
.about-copy h3{font-size:1.7rem;font-weight:900;color:var(--c1);line-height:1.5;margin-bottom:24px}
.about-copy p{color:var(--ct2);margin-bottom:16px;text-align:justify;font-size:.95rem}
.str-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}
.str-card{background:#fff;border-radius:var(--rad);padding:36px 28px;box-shadow:var(--sh);transition:.3s;position:relative;border-top:3px solid transparent}
.str-card:hover{transform:translateY(-4px);border-top-color:var(--c2)}
.str-num{font-family:var(--fen);font-size:3rem;font-weight:800;color:var(--c2);opacity:.25;line-height:1;margin-bottom:12px}
.str-card h3{font-size:1.05rem;font-weight:700;margin-bottom:12px;color:var(--c1)}
.str-card p{font-size:.88rem;color:var(--ct2);line-height:1.85}
.data-row{display:flex;justify-content:center;gap:32px;flex-wrap:wrap}
.data-pill{background:#fff;border-radius:60px;padding:28px 36px;box-shadow:var(--sh);display:flex;align-items:center;gap:16px;min-width:200px}
.data-val{font-family:var(--fen);font-size:2.8rem;font-weight:800;color:var(--c1);line-height:1}
.data-unit{font-size:.95rem;color:var(--c2);font-weight:700}
.data-label{font-size:.82rem;color:var(--ct2);font-weight:500}
.voice-list{display:flex;flex-direction:column;gap:32px}
.voice-card{display:grid;grid-template-columns:200px 1fr;background:#fff;border-radius:var(--rad);overflow:hidden;box-shadow:var(--sh);transition:.3s}
.voice-card:hover{transform:translateX(4px)}
.voice-card img{width:100%;height:100%;object-fit:cover;min-height:220px}
.voice-body{padding:32px;display:flex;flex-direction:column;justify-content:center}
.voice-dept{font-family:var(--fi);font-size:.75rem;font-weight:700;color:var(--c2);letter-spacing:.12em;text-transform:uppercase;margin-bottom:6px}
.voice-name{font-size:1.2rem;font-weight:700;margin-bottom:4px;color:var(--c1)}
.voice-meta{font-size:.78rem;color:var(--ct2);margin-bottom:14px}
.voice-quote{font-size:.9rem;color:var(--ct2);line-height:1.85;padding-left:16px;border-left:3px solid var(--c2)}
.open-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:28px}
.open-card{background:#fff;border-radius:var(--rad);overflow:hidden;box-shadow:var(--sh);transition:.3s;display:flex;flex-direction:column}
.open-card:hover{transform:translateY(-4px)}
.open-card img{width:100%;height:220px;object-fit:cover}
.open-info{padding:28px;flex-grow:1;display:flex;flex-direction:column}
.open-badge{display:inline-block;background:var(--c1);color:#fff;font-size:.72rem;font-weight:700;padding:4px 14px;border-radius:20px;margin-bottom:12px;align-self:flex-start;letter-spacing:.05em}
.open-title{font-size:1.1rem;font-weight:700;margin-bottom:10px;color:var(--c1)}
.open-desc{font-size:.85rem;color:var(--ct2);line-height:1.85;flex-grow:1;margin-bottom:16px}
.open-link{font-family:var(--fi);font-weight:600;font-size:.85rem;color:var(--c2);display:inline-flex;align-items:center;gap:6px}
.open-link:hover{gap:10px}
.welfare-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}
.welfare-item{background:#fff;border-radius:var(--rad);padding:24px 28px;box-shadow:var(--sh)}
.welfare-item dt{font-weight:700;font-size:.95rem;color:var(--c1);margin-bottom:6px;display:flex;align-items:center;gap:8px}
.welfare-item dt::before{content:"";width:8px;height:8px;background:var(--c2);border-radius:50%;flex-shrink:0}
.welfare-item dd{font-size:.85rem;color:var(--ct2);line-height:1.75}
.job-hero{min-height:70vh;position:relative;display:flex;align-items:center;padding:calc(var(--hh) + 80px) 0 80px;background:linear-gradient(160deg,#fff 0%,var(--cbg2) 60%,rgba(232,93,58,.08) 100%)}.job-hero .hero-inner{padding-top:0}.job-hero .anime-txt{font-size:clamp(3rem,8.5vw,7rem)}.job-hero .hero-jp{font-size:clamp(1.2rem,2vw,1.6rem)}.job-tagline{font-size:clamp(1.3rem,2.6vw,2rem);font-weight:900;color:var(--c1);line-height:1.55;margin:24px 0 18px;letter-spacing:.02em}.job-hero-cta{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-top:32px}.points-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}.point-item{background:#fff;border-radius:var(--rad);padding:32px 28px;box-shadow:var(--sh);position:relative;border-left:3px solid var(--c2);transition:.3s}.point-item:hover{transform:translateY(-4px);border-left-color:var(--c1)}.point-num{font-family:var(--fen);font-size:2.2rem;font-weight:800;color:var(--c2);opacity:.3;line-height:1;margin-bottom:10px}.point-title{font-size:1.05rem;font-weight:700;color:var(--c1);line-height:1.55}.req-table{background:#fff;border-radius:var(--rad);box-shadow:var(--sh);overflow:hidden}.req-row{display:grid;grid-template-columns:220px 1fr;border-bottom:1px solid var(--cbg2);padding:22px 32px;align-items:start}.req-row:last-child{border-bottom:none}.req-row dt{font-size:.88rem;font-weight:700;color:var(--c1);letter-spacing:.04em;position:relative;padding-left:16px}.req-row dt::before{content:"";position:absolute;left:0;top:9px;width:6px;height:6px;background:var(--c2);border-radius:50%}.req-row dd{font-size:.92rem;color:var(--ct2);line-height:1.85;white-space:pre-wrap}.flow-list{display:flex;flex-direction:column;gap:20px;position:relative;padding-left:8px}.flow-list::before{content:"";position:absolute;left:44px;top:24px;bottom:24px;width:2px;background:linear-gradient(180deg,var(--c2) 0%,var(--c1) 100%);opacity:.25}.flow-step{display:grid;grid-template-columns:100px 1fr;gap:28px;background:#fff;border-radius:var(--rad);padding:28px 32px;box-shadow:var(--sh);position:relative;align-items:start}.flow-num{font-family:var(--fen);font-size:.72rem;font-weight:700;color:var(--c2);letter-spacing:.2em;text-align:center;padding:14px 0;border-radius:50%;background:#fff;border:2px solid var(--c2);width:80px;height:80px;display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1;position:relative;z-index:2}.flow-num span{font-size:1.6rem;font-weight:900;color:var(--c1);margin-top:4px;letter-spacing:-.02em}.flow-body h3{font-size:1.15rem;font-weight:700;color:var(--c1);margin-bottom:8px}.flow-body p{font-size:.9rem;color:var(--ct2);line-height:1.85}.emp-card{display:grid;grid-template-columns:320px 1fr;gap:48px;background:#fff;border-radius:var(--rad);box-shadow:var(--sh);overflow:hidden;align-items:stretch}.emp-photo{position:relative;background:var(--cbg2)}.emp-photo img{width:100%;height:100%;object-fit:cover;min-height:420px}.emp-body{padding:48px 44px;display:flex;flex-direction:column;justify-content:center}.emp-meta{font-family:var(--fi);font-size:.78rem;font-weight:700;color:var(--c2);letter-spacing:.12em;text-transform:uppercase;margin-bottom:8px}.emp-name{font-size:1.6rem;font-weight:900;color:var(--c1);margin-bottom:32px;letter-spacing:.02em}.emp-qa{display:flex;flex-direction:column;gap:24px}.emp-qa-row{padding-bottom:24px;border-bottom:1px solid var(--cbg2)}.emp-qa-row:last-child{border-bottom:none;padding-bottom:0}.emp-q{font-size:.95rem;font-weight:700;color:var(--c1);margin-bottom:10px;padding-left:26px;position:relative;line-height:1.65}.emp-q::before{content:"Q";position:absolute;left:0;top:-2px;font-family:var(--fen);font-size:1.2rem;font-weight:900;color:var(--c2);line-height:1}.emp-a{font-size:.88rem;color:var(--ct2);line-height:1.95;padding-left:26px;position:relative}.emp-a::before{content:"A";position:absolute;left:0;top:-2px;font-family:var(--fen);font-size:1.2rem;font-weight:900;color:var(--c1);line-height:1;opacity:.45}.day-list{display:flex;flex-direction:column;gap:0;position:relative;max-width:760px;margin:0 auto}.day-list::before{content:"";position:absolute;left:70px;top:20px;bottom:20px;width:2px;background:var(--cbg2);z-index:0}.day-row{display:grid;grid-template-columns:140px 1fr;gap:32px;padding:22px 0;position:relative;align-items:start}.day-time{font-family:var(--fen);font-size:1.6rem;font-weight:800;color:var(--c1);letter-spacing:-.02em;position:relative;padding-left:0;line-height:1}.day-time::after{content:"";position:absolute;right:-20px;top:6px;width:12px;height:12px;border-radius:50%;background:var(--c2);border:3px solid #fff;box-shadow:0 0 0 2px var(--c2);z-index:2}.day-body{padding-left:32px;border-left:0;padding-top:2px}.day-body h3{font-size:1.05rem;font-weight:700;color:var(--c1);margin-bottom:6px}.day-body p{font-size:.88rem;color:var(--ct2);line-height:1.85}@media (max-width:900px){.points-grid{grid-template-columns:repeat(2,1fr)}.flow-step{grid-template-columns:70px 1fr;gap:18px;padding:20px 22px}.flow-num{width:64px;height:64px;font-size:.65rem}.flow-num span{font-size:1.3rem}.flow-list::before{left:36px}.req-row{grid-template-columns:1fr;gap:8px;padding:20px 24px}.emp-card{grid-template-columns:1fr}.emp-photo img{min-height:280px}.emp-body{padding:32px 28px}.day-row{grid-template-columns:90px 1fr;gap:18px}.day-time{font-size:1.2rem}.day-list::before{left:46px}}@media (max-width:640px){.points-grid{grid-template-columns:1fr}}.cta{background:linear-gradient(135deg,var(--c1) 0%,#2a3f7a 100%);padding:100px 0;text-align:center;position:relative;overflow:hidden}
.cta h2{font-size:1.6rem;font-weight:900;color:#fff;margin-bottom:10px}
.cta p{color:rgba(255,255,255,.75);margin-bottom:32px}
.map-wrap{width:100%;height:360px}
.map-wrap iframe{width:100%;height:100%;border:0;filter:grayscale(80%) contrast(1.1);transition:.4s}
.map-wrap iframe:hover{filter:grayscale(0%)}
.ftr{background:var(--c1);color:#fff;padding:56px 0}
.ftr-inner{display:flex;justify-content:space-between;gap:40px;padding-bottom:36px;border-bottom:1px solid rgba(255,255,255,.15);margin-bottom:20px}
.ftr-brand{flex:1;max-width:380px}
.ftr-brand h2{font-size:1.35rem;font-weight:700;margin-bottom:8px}
.ftr-brand p{font-size:.85rem;opacity:.75}
.ftr-tbl{flex:1}
.ftr-tbl table{width:100%;font-size:.85rem;border-collapse:collapse}
.ftr-tbl th,.ftr-tbl td{padding:10px 12px;text-align:left;border-bottom:1px solid rgba(255,255,255,.12);color:#fff}
.ftr-tbl th{width:28%;opacity:.65;font-weight:400}
.ftr-copy{text-align:center;font-size:.75rem;opacity:.5;font-family:var(--fi)}
@media(max-width:900px){
.hdr{padding:0 18px}
.hdr-logo{font-size:1rem}
.hdr-nav{display:none}.hamburger{display:block}
.wrap{padding:0 20px}
.block{padding:70px 0}
.hero{height:auto;min-height:0;padding:calc(var(--hh) + 70px) 0 70px}
.hero-inner{padding:0 20px}
.hero-title-wrap .anime-txt{font-size:clamp(3rem,13vw,5rem)}
.hero-jp{font-size:clamp(1.1rem,3.5vw,1.5rem);margin-top:14px}
.hero-sub{font-size:.92rem;margin-bottom:28px}
.btn-main{padding:12px 30px;font-size:.88rem}
.anime-txt{font-size:clamp(2.6rem,9vw,4.5rem)}
.sec-en{font-size:clamp(2rem,7vw,3rem)}
.sec-head{margin-bottom:40px}
.sec-head .jp-sub{font-size:.88rem;gap:10px}
.sec-head .jp-sub::before{width:24px}
.about-grid{grid-template-columns:1fr;gap:32px}
.about-copy h3{font-size:1.3rem;margin-bottom:18px}
.about-copy p{font-size:.9rem}
.str-grid{grid-template-columns:1fr;gap:18px}
.str-card{padding:28px 24px}
.data-row{gap:14px;flex-direction:column;align-items:stretch}
.data-pill{min-width:0;padding:20px 24px;justify-content:space-between}
.data-val{font-size:2.2rem}
.voice-card{grid-template-columns:1fr}
.voice-card img{height:240px;min-height:0}
.voice-body{padding:24px}
.voice-quote{font-size:.88rem}
.open-grid{grid-template-columns:1fr;gap:18px}
.open-card img{height:180px}
.open-info{padding:22px}
.welfare-grid{grid-template-columns:1fr;gap:14px}
.welfare-item{padding:20px 22px}
.cta{padding:70px 0}
.cta h2{font-size:1.3rem;padding:0 20px}
.cta p{font-size:.88rem;padding:0 20px;margin-bottom:24px}
.map-wrap{height:280px}
.ftr{padding:44px 0}
.ftr-inner{flex-direction:column;gap:24px;padding-bottom:28px}
.ftr-tbl table{font-size:.78rem}
.ftr-tbl th,.ftr-tbl td{padding:8px 10px}
}
@media(max-width:540px){
.wrap{padding:0 16px}
.hdr{padding:0 14px;height:60px}
.hdr-logo-icon{width:30px;height:30px;font-size:.88rem}
.hdr-logo{font-size:.92rem}
:root{--hh:60px}
.block{padding:56px 0}
.hero{padding:calc(var(--hh) + 50px) 0 56px}
.hero-inner{padding:0 16px}
.hero-label{font-size:.72rem;margin-bottom:16px;letter-spacing:.2em}
.hero-label::before{width:32px}
.hero-title-wrap{margin-bottom:20px}
.hero-title-wrap .anime-txt{font-size:clamp(2.4rem,11vw,3.4rem);line-height:.94}
.hero-jp{font-size:1rem;line-height:1.5;margin-top:10px}
.hero-sub{font-size:.85rem;line-height:1.8;margin-bottom:22px}
.btn-main{padding:11px 26px;font-size:.82rem;width:auto}
.anime-txt{font-size:clamp(2rem,8vw,2.8rem)}
.sec-en{font-size:clamp(1.7rem,6.5vw,2.3rem);margin-bottom:10px}
.sec-head{margin-bottom:32px}
.sec-head .jp-sub{font-size:.82rem}
.about-grid{gap:24px}
.about-copy h3{font-size:1.15rem;line-height:1.55;margin-bottom:14px}
.about-copy p{font-size:.85rem;margin-bottom:12px}
.str-card{padding:24px 20px}
.str-num{font-size:2.4rem}
.str-card h3{font-size:.98rem}
.str-card p{font-size:.82rem}
.data-pill{padding:18px 22px;border-radius:16px}
.data-val{font-size:1.9rem}
.data-label{font-size:.78rem}
.data-unit{font-size:.88rem}
.voice-card img{height:200px}
.voice-body{padding:22px 20px}
.voice-name{font-size:1.1rem}
.voice-quote{font-size:.85rem;padding-left:12px}
.open-card img{height:160px}
.open-info{padding:20px}
.open-title{font-size:1rem}
.open-desc{font-size:.82rem}
.welfare-item{padding:18px 20px}
.welfare-item dt{font-size:.9rem}
.welfare-item dd{font-size:.82rem}
.cta{padding:56px 0}
.cta h2{font-size:1.15rem;line-height:1.55}
.cta p{font-size:.82rem}
.map-wrap{height:240px}
.ftr{padding:36px 0}
.ftr-brand h2{font-size:1.2rem}
.ftr-brand p{font-size:.8rem}
.ftr-tbl table{font-size:.74rem}
.ftr-tbl th{width:32%}
.ftr-tbl th,.ftr-tbl td{padding:7px 8px}
.ftr-copy{font-size:.68rem}
}
</style>
</head>
<body>

<header class="hdr">
  <a href="#" class="hdr-logo">${c.header.logo_image
    ? `<div class="hdr-logo-icon has-img"><img src="${esc(c.header.logo_image)}" alt="${esc(c.header.company_name)}"></div>`
    : ''}${esc(c.header.company_name)}</a>
  <nav class="hdr-nav">
    ${navLinks.map(l => `<a href="${l.href}">${l.label}</a>`).join('\n    ')}
    <a href="#entry" class="hdr-cta">応募する</a>
  </nav>
  <button class="hamburger" id="js-ham"><span></span><span></span><span></span></button>
</header>

<div class="mob-nav" id="js-mob">
  <button class="mob-close" id="js-mob-x"><span></span><span></span></button>
  ${navLinks.map(l => `<a href="${l.href}">${l.label}</a>`).join('\n  ')}
  <a href="#entry">応募する</a>
</div>

<section class="hero">
  <div class="hero-bg"></div>
  <div class="hero-overlay"></div>
  <div class="hero-inner">
    <div class="hero-label">${esc(c.hero.label)}</div>
    <div class="hero-title-wrap">
      <span class="anime-txt">${esc(c.hero.en_title)}</span>
      <h1 class="hero-jp">${esc(c.hero.jp_tagline)}</h1>
    </div>
    <p class="hero-sub">${escBr(c.hero.subtext).replace(/\n/g, '<br>')}</p>
    <a href="${esc(c.hero.cta_anchor)}" class="btn-main">${esc(c.hero.cta_label)} →</a>
  </div>
</section>

<section id="about" class="block">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Company</span>
      <p class="jp-sub">${esc(c.about.sub)}</p>
    </div>
    <div class="about-grid">
      <div class="about-photo"><img src="${esc(c.about.photo)}" alt="about"></div>
      <div class="about-copy">
        <h3>${escBr(c.about.headline)}</h3>
        ${aboutParagraphsHtml}
        <a href="${esc(c.about.button_anchor)}" class="btn-ghost">${esc(c.about.button_label)} →</a>
      </div>
    </div>
  </div>
</section>

<section id="strengths" class="block block--alt">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Strengths</span>
      <p class="jp-sub">${esc(c.strengths.sub)}</p>
    </div>
    <div class="str-grid">${strengthsHtml}
    </div>
  </div>
</section>

<section id="data" class="block">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Data</span>
      <p class="jp-sub">${esc(c.data.sub)}</p>
    </div>
    <div class="data-row">${dataHtml}
    </div>
  </div>
</section>

<section id="voices" class="block block--alt">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Voices</span>
      <p class="jp-sub">${esc(c.voices.sub)}</p>
    </div>
    <div class="voice-list">${voicesHtml}
    </div>
  </div>
</section>

<section id="openings" class="block">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Openings</span>
      <p class="jp-sub">${esc(c.openings.sub)}</p>
    </div>
    <div class="open-grid">${openingsHtml}
    </div>
  </div>
</section>

<section id="welfare" class="block block--alt">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Welfare</span>
      <p class="jp-sub">${esc(c.welfare.sub)}</p>
    </div>
    <div class="welfare-grid">${welfareHtml}
    </div>
  </div>
</section>

<section id="entry" class="cta">
  <div class="wrap fade-in">
    <h2>${esc(c.cta.headline)}</h2>
    <p>${esc(c.cta.sub)}</p>
    <a href="${canonicalBase}/entry" class="btn-main">${esc(c.cta.button_label)} →</a>
  </div>
</section>

${c.map_embed_src ? `<div class="map-wrap">
  <iframe src="${esc(c.map_embed_src)}" allowfullscreen="" loading="lazy"></iframe>
</div>` : ''}

<footer class="ftr">
  <div class="wrap">
    <div class="ftr-inner">
      <div class="ftr-brand"><h2>${esc(c.footer.company_name)}</h2><p>${esc(c.footer.tagline)}</p></div>
      <div class="ftr-tbl"><table>
        <tr><th>所在地</th><td>${escBr(c.footer.address)}</td></tr>
        <tr><th>設立</th><td>${esc(c.footer.founded)}</td></tr>
        <tr><th>代表</th><td>${esc(c.footer.representative)}</td></tr>
        <tr><th>事業</th><td>${esc(c.footer.business)}</td></tr>
      </table></div>
    </div>
    <p class="ftr-copy">© 2026 ${esc(c.footer.company_name)}</p>
  </div>
</footer>

<script>
document.addEventListener('DOMContentLoaded',()=>{
  const io=new IntersectionObserver(e=>{e.forEach(e=>{if(e.isIntersecting){e.target.classList.add('is-visible');io.unobserve(e.target)}})},{threshold:.08});
  document.querySelectorAll('.fade-in').forEach(e=>io.observe(e));
  const ao=new IntersectionObserver(e=>{e.forEach(e=>{if(e.isIntersecting){e.target.classList.add('anime');ao.unobserve(e.target)}})},{root:null,rootMargin:"0% 0px -200px 0px",threshold:0});
  document.querySelectorAll('.anime-txt').forEach(e=>ao.observe(e));
  setTimeout(()=>{document.querySelectorAll('.hero .anime-txt').forEach(e=>e.classList.add('anime'))},400);
  const co=new IntersectionObserver(e=>{e.forEach(e=>{if(e.isIntersecting){const t=e.target,m=+t.dataset.target;if(!m)return;let v=0;const s=Math.ceil(m/40),i=setInterval(()=>{v+=s;if(v>=m){v=m;clearInterval(i)}t.innerText=v},35);co.unobserve(t)}})},{threshold:.4});
  document.querySelectorAll('.count-up').forEach(e=>co.observe(e));
  const h=document.getElementById('js-ham'),n=document.getElementById('js-mob'),x=document.getElementById('js-mob-x');
  if(h&&n){h.onclick=()=>{h.classList.toggle('is-active');n.classList.toggle('is-active')};
  if(x)x.onclick=()=>{h.classList.remove('is-active');n.classList.remove('is-active')};
  n.querySelectorAll('a').forEach(a=>a.onclick=()=>{h.classList.remove('is-active');n.classList.remove('is-active')})}
  document.querySelectorAll('a[href^="#"]').forEach(a=>{a.onclick=function(e){e.preventDefault();const t=document.querySelector(this.getAttribute('href'));if(t)window.scrollTo({top:t.getBoundingClientRect().top+scrollY-72,behavior:'smooth'})}});
});
</script>
<script>
(function(){
  try {
    var slug = "${slug}";
    var sid = sessionStorage.getItem('lp_sid_'+slug);
    if (!sid) { sid = Date.now()+Math.random().toString(36).slice(2); sessionStorage.setItem('lp_sid_'+slug, sid); }
    var ep = '/api/lp/'+slug+'/track';
    fetch(ep, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      keepalive:true,
      body: JSON.stringify({event_type:'page_view', path:location.pathname, session_id:sid, referrer:document.referrer||''})
    }).catch(function(){});
  } catch(e){}
})();
</script>
</body>
</html>`
}

// ═════════════════════════════════════════════════════════════════════════
// renderJobDetailHtml — individual job detail page for /lp/[slug]/jobs/[i]
//
// Takes an opening item by index and renders a full detail page with:
//   - Site header + mobile nav (links back to the main LP anchors)
//   - Job hero (anime-txt EN title + JA title + tagline + intro + CTA row)
//   - 求人のポイント (Points) — numbered highlight grid (conditional)
//   - 募集要項 (Requirements) — key/value description list (conditional)
//   - 選考フロー (Selection flow) — numbered vertical timeline (conditional)
//   - 社員紹介 (Employee interview) — photo + Q&A card (conditional)
//   - 1日の流れ (Day in life) — time-stamped vertical timeline (conditional)
//   - Apply CTA section linking to /lp/${slug}/entry?position=...
//   - Shared footer
//
// All detail sub-sections render only if their data is present, so an
// opening with no `detail` object still produces a valid minimal page.
//
// Returns null if jobIndex is out of range — the route handler turns
// that into a 404.
//
// Design note: head/header/footer/scripts are intentionally duplicated
// from renderLpHtml rather than extracted to helpers, because both
// functions share the same big <style> block (module-scope theme vars)
// and extracting would add indirection without meaningful reuse.
// ═════════════════════════════════════════════════════════════════════════
export function renderJobDetailHtml(
  slug: string,
  c: LpContent,
  jobIndex: number,
  canonicalBase: string = `https://nippo-sync.vercel.app/lp/${slug}`
): string | null {
  const items = c.openings.items || []
  if (jobIndex < 0 || jobIndex >= items.length) return null
  const job = items[jobIndex]
  const d = job.detail || {}
  const theme = { ...DEFAULT_THEME, ...(c.theme || {}) }

  const navLinks = [
    { href: `${canonicalBase}#about`, label: '会社を知る' },
    { href: `${canonicalBase}#strengths`, label: '強み' },
    { href: `${canonicalBase}#openings`, label: '採用職種' },
    { href: `${canonicalBase}#welfare`, label: '待遇' },
  ]

  const idealHtml = (d.ideal_candidate || []).map((p, i) => `
      <div class="point-item">
        <div class="point-num">${String(i + 1).padStart(2, '0')}</div>
        <div class="point-title">${esc(p.title)}</div>
      </div>`).join('\n')

  const pointsHtml = (d.points || []).map((p, i) => `
      <div class="point-item">
        <div class="point-num">${String(i + 1).padStart(2, '0')}</div>
        <div class="point-title">${esc(p.title)}</div>
      </div>`).join('\n')

  const reqHtml = (d.requirements || []).map((r) => `
      <div class="req-row">
        <dt>${esc(r.term)}</dt>
        <dd>${escBr(r.description)}</dd>
      </div>`).join('\n')

  const flowHtml = (d.selection_flow || []).map((f, i) => `
      <div class="flow-step">
        <div class="flow-num">STEP<br><span>${String(i + 1).padStart(2, '0')}</span></div>
        <div class="flow-body">
          <h3>${esc(f.title)}</h3>
          <p>${esc(f.description)}</p>
        </div>
      </div>`).join('\n')

  const empQaHtml = (d.employee?.qa || []).map((qa) => `
      <div class="emp-qa-row">
        <div class="emp-q">${esc(qa.q)}</div>
        <div class="emp-a">${escBr(qa.a)}</div>
      </div>`).join('\n')

  const dayHtml = (d.day_in_life || []).map((day) => `
      <div class="day-row">
        <div class="day-time">${esc(day.time)}</div>
        <div class="day-body">
          <h3>${esc(day.title)}</h3>
          <p>${esc(day.description)}</p>
        </div>
      </div>`).join('\n')

  const pageTitle = `${job.title}｜${c.header.company_name || c.footer.company_name || slug}`
  const metaDesc = d.intro || d.tagline || job.description || c.meta.description

  // JSON-LD description: admin-set override wins, otherwise shared
  // composer assembles structured <p> blocks from intro + requirements +
  // salary + welfare. Both this renderer and the admin editor use the
  // same helper so what Google receives matches what the admin sees.
  const _descriptionHtml = d.description_html?.trim() || composeJobDescriptionHtml(c, job, d)

  // Salary structured data: prefer min/max range, fall back to legacy single value.
  const _salaryValue =
    d.salary_min || d.salary_max
      ? {
          '@type': 'QuantitativeValue',
          ...(d.salary_min ? { minValue: d.salary_min } : {}),
          ...(d.salary_max ? { maxValue: d.salary_max } : {}),
          unitText: d.salary_unit || 'MONTH',
        }
      : d.salary_amount
        ? {
            '@type': 'QuantitativeValue',
            value: d.salary_amount,
            unitText: d.salary_unit || 'MONTH',
          }
        : null

  // validThrough fallback: posted_date + 90 days. Stable across saves
  // (won't churn) — see addDaysIso() for rationale.
  const _validThrough =
    d.valid_through || (d.posted_date ? addDaysIso(d.posted_date, 90) : null)

  const _companyName = c.header.company_name || c.footer.company_name || slug

  const _jobLd: Record<string, unknown> = {
    '@context': 'https://schema.org/',
    '@type': 'JobPosting',
    title: job.title,
    description: _descriptionHtml,
    // Stable identifier helps Google dedupe across re-crawls and across
    // any aggregator that picks the listing up. Value is slug-scoped so
    // it's globally unique without needing a separate ID column.
    identifier: {
      '@type': 'PropertyValue',
      name: _companyName,
      value: `${slug}-${jobIndex}`,
    },
    // directApply unlocks the "Apply on company site" badge in Google for Jobs
    // and is a documented ranking signal since 2024. Defaults true — the /entry
    // route on this same domain handles applications. Set direct_apply: false in
    // the DB when the apply flow redirects to an external ATS (misrepresenting
    // this as true is a Google policy violation that can suppress domain-wide).
    directApply: d.direct_apply !== false,
    // datePosted is REQUIRED by schema.org. Only emit it when we have a real
    // value from the admin (set at create/publish). We deliberately do NOT
    // default to today — that would make the date change on every crawl and
    // would look like spam to Google.
    ...(d.posted_date ? { datePosted: d.posted_date } : {}),
    ...(_validThrough ? { validThrough: _validThrough } : {}),
    ...(d.employment_type ? { employmentType: d.employment_type } : {}),
    hiringOrganization: {
      '@type': 'Organization',
      name: _companyName,
      ...(c.header.favicon_url ?? c.header.logo_image ? { logo: c.header.favicon_url ?? c.header.logo_image } : {}),
      ...(c.footer.website ? { sameAs: c.footer.website } : {}),
    },
    jobLocation: {
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        ...(c.map?.region ? { addressRegion: c.map.region } : {}),
        ...(c.map?.locality ? { addressLocality: c.map.locality } : {}),
        ...(c.map?.street ? { streetAddress: c.map.street } : {}),
        ...(c.map?.postal_code ? { postalCode: c.map.postal_code } : {}),
        addressCountry: 'JP',
      },
    },
    ...(_salaryValue
      ? {
          baseSalary: {
            '@type': 'MonetaryAmount',
            currency: 'JPY',
            value: _salaryValue,
          },
        }
      : {}),
  }
  const _jobLdJson = JSON.stringify(_jobLd).replace(/</g, '\\u003c')

  return `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="${esc(metaDesc)}">
<title>${esc(pageTitle)}</title>
<link rel="canonical" href="${canonicalBase}/jobs/${jobIndex}">
${ROBOTS_SNIPPET_META}
${renderVerificationMetas(slug)}
<!-- Open Graph / Twitter Card metadata for link unfurling -->
<meta property="og:type" content="website">
<meta property="og:url" content="${canonicalBase}/jobs/${jobIndex}">
<meta property="og:title" content="${esc(pageTitle)}">
<meta property="og:description" content="${esc(metaDesc)}">
<meta property="og:site_name" content="${esc(c.header.company_name || c.footer.company_name || '')}">
<meta property="og:locale" content="ja_JP">
${d.hero_bg ? `<meta property="og:image" content="${esc(d.hero_bg)}">` : c.hero?.bg_image ? `<meta property="og:image" content="${esc(c.hero.bg_image)}">` : ''}
${c.header?.favicon_url
  ? `<link rel="icon" type="image/png" sizes="32x32" href="${esc(c.header.favicon_url)}">
<link rel="icon" type="image/png" sizes="192x192" href="${esc(c.header.favicon_url)}">
<link rel="apple-touch-icon" sizes="180x180" href="${esc(c.header.favicon_url)}">`
  : c.header?.logo_image
  ? `<link rel="icon" type="image/png" href="${esc(c.header.logo_image)}">`
  : ''}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(pageTitle)}">
<meta name="twitter:description" content="${esc(metaDesc)}">
${d.hero_bg ? `<meta name="twitter:image" content="${esc(d.hero_bg)}">` : c.hero?.bg_image ? `<meta name="twitter:image" content="${esc(c.hero.bg_image)}">` : ''}
<!-- ▽ 構造化マークアップ ▽ -->
<script type="application/ld+json">${_jobLdJson}</script>
<script type="application/ld+json">${JSON.stringify({
  '@context': 'https://schema.org',
  '@type': 'BreadcrumbList',
  itemListElement: [
    { '@type': 'ListItem', position: 1, name: '採用情報', item: canonicalBase },
    { '@type': 'ListItem', position: 2, name: job.title, item: `${canonicalBase}/jobs/${jobIndex}` },
  ],
}).replace(/</g, '\\u003c')}</script>
<!-- △ 構造化マークアップ △ -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Noto+Sans+JP:wght@400;500;700;900&family=Outfit:wght@600;800;900&display=swap" rel="stylesheet">
<style>
:root{--c1:${theme.primary};--c2:${theme.accent};--c3:${theme.accent2};--c2-dark:#c94a2b;--ct:#1a1a2e;--ct2:#5a5a72;--cbg:#FAFBFD;--cbg2:#F0F2F7;--fen:"Outfit",sans-serif;--fjp:"Noto Sans JP",sans-serif;--fi:"Inter",sans-serif;--mw:1200px;--hh:72px;--rad:12px;--sh:0 8px 32px rgba(27,43,90,.07)}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--fjp);color:var(--ct);background:#fff;line-height:1.85;letter-spacing:.03em;-webkit-font-smoothing:antialiased;overflow-x:hidden}
a{text-decoration:none;color:inherit;transition:.25s}img{max-width:100%;height:auto;display:block}
.fade-in{opacity:0;transform:translateY(30px);transition:.8s ease}.is-visible{opacity:1;transform:translateY(0)}
.wrap{max-width:var(--mw);margin:0 auto;padding:0 32px}
.block{padding:120px 0;position:relative}
.block--alt{background:var(--cbg2)}
.anime-txt{font-family:var(--fen);font-weight:900;font-size:clamp(3rem,8.5vw,7rem);letter-spacing:-0.025em;line-height:.95;background-image:url('https://mgc-pass-proxy.duckdns.org/img/text_back.png?v=3');background-size:200% 100%;background-repeat:no-repeat;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:rgba(0,0,0,0);display:inline-block;transition:1.1s background-position-x;transition-timing-function:linear;background-position-x:300%;text-transform:uppercase}
.anime-txt.anime{background-position-x:0%}
.sec-head{margin-bottom:60px}
.sec-en{font-family:var(--fen);font-weight:900;font-size:clamp(2.5rem,5.5vw,4.5rem);letter-spacing:-.02em;line-height:1;color:var(--c1);display:block;margin-bottom:14px;text-transform:uppercase}
.sec-head .jp-sub{font-size:1.05rem;font-weight:700;color:var(--c1);letter-spacing:.08em;display:flex;align-items:center;gap:14px}
.sec-head .jp-sub::before{content:"";width:32px;height:2px;background:var(--c2)}
.btn-main{display:inline-flex;align-items:center;gap:8px;padding:14px 40px;background:var(--c2);color:#fff;font-size:.95rem;font-weight:700;border-radius:var(--rad);letter-spacing:.06em;transition:.25s;cursor:pointer;border:none}
.btn-main:hover{background:var(--c2-dark);transform:translateY(-2px)}
.btn-ghost{display:inline-block;padding:12px 28px;border:1.5px solid var(--c1);color:var(--c1);border-radius:var(--rad);font-size:.88rem;font-weight:600}
.btn-ghost:hover{background:var(--c1);color:#fff}
.hdr{position:fixed;top:0;left:0;width:100%;height:var(--hh);background:rgba(255,255,255,.97);backdrop-filter:blur(12px);z-index:1000;display:flex;align-items:center;justify-content:space-between;padding:0 32px;border-bottom:1px solid rgba(27,43,90,.06)}
.hdr-logo{font-family:var(--fjp);font-weight:900;font-size:1.15rem;color:var(--c1);display:flex;align-items:center;gap:10px}
.hdr-logo-icon{width:34px;height:34px;background:linear-gradient(135deg,var(--c1),var(--c2));border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-family:var(--fen);font-weight:800;font-size:1rem}.hdr-logo-icon.has-img{background:transparent;padding:2px;overflow:hidden;width:auto;min-width:34px;height:34px}.hdr-logo-icon.has-img img{height:100%;width:auto;max-width:120px;object-fit:contain;display:block}
.hdr-nav{display:flex;gap:28px;align-items:center}
.hdr-nav a{font-size:.85rem;font-weight:600;color:var(--ct2);font-family:var(--fi)}
.hdr-nav a:hover{color:var(--c2)}
.hdr-nav .hdr-cta{background:var(--c1);color:#fff;padding:9px 22px;border-radius:8px;font-weight:700;font-size:.82rem;letter-spacing:.05em}
.hdr-nav .hdr-cta:hover{background:var(--c2);color:#fff}
.hamburger{display:none;width:36px;height:36px;background:none;border:none;cursor:pointer;position:relative;z-index:1002}
.hamburger span{position:absolute;right:0;width:26px;height:2px;background:var(--c1);transition:.3s}
.hamburger span:nth-child(1){top:10px}.hamburger span:nth-child(2){top:17px;width:18px}.hamburger span:nth-child(3){top:24px}
.hamburger.is-active span:nth-child(1){top:17px;transform:rotate(45deg);width:26px}
.hamburger.is-active span:nth-child(2){opacity:0}
.hamburger.is-active span:nth-child(3){top:17px;transform:rotate(-45deg);width:26px}
.mob-nav{position:fixed;top:0;right:-100%;width:100%;height:100vh;background:#fff;z-index:1001;transition:.4s cubic-bezier(.77,0,.175,1);display:flex;flex-direction:column;justify-content:center;align-items:center;gap:28px}
.mob-nav.is-active{right:0}
.mob-nav a{font-size:1.15rem;font-weight:700;color:var(--c1)}
.mob-close{position:absolute;top:18px;right:18px;width:36px;height:36px;border:none;background:none;cursor:pointer}
.mob-close span{position:absolute;width:26px;height:2px;background:var(--c1);left:5px;top:17px}
.mob-close span:nth-child(1){transform:rotate(45deg)}
.mob-close span:nth-child(2){transform:rotate(-45deg)}
.job-hero{min-height:70vh;position:relative;display:flex;align-items:center;padding:calc(var(--hh) + 90px) 0 80px;background:linear-gradient(160deg,#fff 0%,var(--cbg2) 60%,rgba(232,93,58,.08) 100%);overflow:hidden}
.job-hero::before{content:"";position:absolute;top:0;right:0;width:40%;height:100%;background:url('${esc((d && d.hero_bg) || job.image || c.hero.bg_image)}') center/cover no-repeat;opacity:.28;mask-image:linear-gradient(270deg,#000 25%,transparent 100%);-webkit-mask-image:linear-gradient(270deg,#000 25%,transparent 100%)}
.job-hero .hero-inner{position:relative;z-index:2;max-width:var(--mw);margin:0 auto;padding:0 32px;width:100%}
.job-badge{display:inline-block;background:var(--c1);color:#fff;font-size:.75rem;font-weight:700;padding:6px 18px;border-radius:20px;margin-bottom:24px;letter-spacing:.06em;text-transform:uppercase}
.job-hero .hero-title-wrap{margin-bottom:24px}
.job-hero .anime-txt{display:block;line-height:.92}
.job-hero .hero-jp{font-size:clamp(1.2rem,2.1vw,1.7rem);font-weight:900;color:var(--c1);margin-top:16px;line-height:1.45;letter-spacing:.04em}
.job-tagline{font-size:clamp(1.35rem,2.6vw,2rem);font-weight:900;color:var(--c1);line-height:1.55;margin:10px 0 18px;letter-spacing:.02em;max-width:760px}
.job-hero .hero-sub{font-size:1rem;color:var(--ct2);font-weight:500;line-height:1.85;margin-bottom:36px;max-width:640px}
.job-hero-cta{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-top:8px}
.points-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}
.point-item{background:#fff;border-radius:var(--rad);padding:36px 30px;box-shadow:var(--sh);position:relative;border-left:3px solid var(--c2);transition:.3s}
.point-item:hover{transform:translateY(-4px);border-left-color:var(--c1)}
.point-num{font-family:var(--fen);font-size:2.2rem;font-weight:800;color:var(--c2);opacity:.3;line-height:1;margin-bottom:10px}
.point-title{font-size:1.08rem;font-weight:700;color:var(--c1);line-height:1.55}
.req-table{background:#fff;border-radius:var(--rad);box-shadow:var(--sh);overflow:hidden}
.req-row{display:grid;grid-template-columns:220px 1fr;border-bottom:1px solid var(--cbg2);padding:24px 36px;align-items:start}
.req-row:last-child{border-bottom:none}
.req-row dt{font-size:.9rem;font-weight:700;color:var(--c1);letter-spacing:.04em;position:relative;padding-left:16px}
.req-row dt::before{content:"";position:absolute;left:0;top:9px;width:6px;height:6px;background:var(--c2);border-radius:50%}
.req-row dd{font-size:.93rem;color:var(--ct2);line-height:1.9;white-space:pre-wrap}
.flow-list{display:flex;flex-direction:column;gap:20px;position:relative;padding-left:8px}
.flow-list::before{content:"";position:absolute;left:48px;top:40px;bottom:40px;width:2px;background:linear-gradient(180deg,var(--c2) 0%,var(--c1) 100%);opacity:.25}
.flow-step{display:grid;grid-template-columns:100px 1fr;gap:28px;background:#fff;border-radius:var(--rad);padding:28px 36px;box-shadow:var(--sh);position:relative;align-items:start}
.flow-num{font-family:var(--fen);font-size:.68rem;font-weight:700;color:var(--c2);letter-spacing:.2em;text-align:center;padding:0;border-radius:50%;background:#fff;border:2px solid var(--c2);width:80px;height:80px;display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1;position:relative;z-index:2}
.flow-num span{font-size:1.6rem;font-weight:900;color:var(--c1);margin-top:4px;letter-spacing:-.02em}
.flow-body h3{font-size:1.15rem;font-weight:700;color:var(--c1);margin-bottom:8px}
.flow-body p{font-size:.9rem;color:var(--ct2);line-height:1.85}
.emp-card{display:grid;grid-template-columns:320px 1fr;gap:0;background:#fff;border-radius:var(--rad);box-shadow:var(--sh);overflow:hidden;align-items:stretch}
.emp-photo{position:relative;background:var(--cbg2)}
.emp-photo img{width:100%;height:100%;object-fit:cover;min-height:420px}
.emp-body{padding:48px 52px;display:flex;flex-direction:column;justify-content:center}
.emp-meta{font-family:var(--fi);font-size:.78rem;font-weight:700;color:var(--c2);letter-spacing:.12em;text-transform:uppercase;margin-bottom:8px}
.emp-name{font-size:1.6rem;font-weight:900;color:var(--c1);margin-bottom:32px;letter-spacing:.02em}
.emp-qa{display:flex;flex-direction:column;gap:24px}
.emp-qa-row{padding-bottom:24px;border-bottom:1px solid var(--cbg2)}
.emp-qa-row:last-child{border-bottom:none;padding-bottom:0}
.emp-q{font-size:.95rem;font-weight:700;color:var(--c1);margin-bottom:12px;padding-left:28px;position:relative;line-height:1.65}
.emp-q::before{content:"Q";position:absolute;left:0;top:-3px;font-family:var(--fen);font-size:1.25rem;font-weight:900;color:var(--c2);line-height:1}
.emp-a{font-size:.88rem;color:var(--ct2);line-height:1.95;padding-left:28px;position:relative}
.emp-a::before{content:"A";position:absolute;left:0;top:-3px;font-family:var(--fen);font-size:1.25rem;font-weight:900;color:var(--c1);line-height:1;opacity:.45}
.day-list{display:flex;flex-direction:column;gap:0;position:relative;max-width:760px;margin:0 auto}
.day-list::before{content:"";position:absolute;left:74px;top:20px;bottom:20px;width:2px;background:var(--cbg2);z-index:0}
.day-row{display:grid;grid-template-columns:140px 1fr;gap:32px;padding:22px 0;position:relative;align-items:start}
.day-time{font-family:var(--fen);font-size:1.6rem;font-weight:800;color:var(--c1);letter-spacing:-.02em;position:relative;padding-left:0;line-height:1}
.day-time::after{content:"";position:absolute;right:-20px;top:6px;width:14px;height:14px;border-radius:50%;background:#fff;border:3px solid var(--c2);z-index:2;box-shadow:0 0 0 3px #fff}
.day-body{padding-left:36px;padding-top:2px}
.day-body h3{font-size:1.05rem;font-weight:700;color:var(--c1);margin-bottom:6px}
.day-body p{font-size:.88rem;color:var(--ct2);line-height:1.85}
.cta{background:linear-gradient(135deg,var(--c1) 0%,#2a3f7a 100%);padding:100px 0;text-align:center;position:relative;overflow:hidden}
.cta h2{font-size:1.6rem;font-weight:900;color:#fff;margin-bottom:10px}
.cta p{color:rgba(255,255,255,.75);margin-bottom:32px}
.ftr{background:var(--c1);color:#fff;padding:56px 0}
.ftr-inner{display:flex;justify-content:space-between;gap:40px;padding-bottom:36px;border-bottom:1px solid rgba(255,255,255,.15);margin-bottom:20px}
.ftr-brand{flex:1;max-width:380px}
.ftr-brand h2{font-size:1.35rem;font-weight:700;margin-bottom:8px}
.ftr-brand p{font-size:.85rem;opacity:.75}
.ftr-tbl{flex:1}
.ftr-tbl table{width:100%;font-size:.8rem}
.ftr-tbl th{text-align:left;padding:6px 14px 6px 0;font-weight:600;opacity:.65;white-space:nowrap;vertical-align:top}
.ftr-tbl td{padding:6px 0;opacity:.9;line-height:1.75}
.ftr-copy{text-align:center;font-size:.75rem;opacity:.55;font-family:var(--fi);letter-spacing:.05em}
@media (max-width:900px){
  .hdr-nav{display:none}
  .hamburger{display:block}
  .block{padding:80px 0}
  .sec-head{margin-bottom:40px}
  .job-hero{min-height:auto;padding:calc(var(--hh) + 60px) 0 60px}
  .job-hero::before{display:none}
  .points-grid{grid-template-columns:repeat(2,1fr);gap:18px}
  .point-item{padding:28px 24px}
  .flow-step{grid-template-columns:70px 1fr;gap:18px;padding:22px 24px}
  .flow-num{width:64px;height:64px;font-size:.62rem}
  .flow-num span{font-size:1.3rem}
  .flow-list::before{left:40px}
  .req-row{grid-template-columns:1fr;gap:8px;padding:20px 26px}
  .req-row dt{font-size:.85rem}
  .emp-card{grid-template-columns:1fr}
  .emp-photo img{min-height:280px}
  .emp-body{padding:32px 28px}
  .day-row{grid-template-columns:90px 1fr;gap:18px}
  .day-time{font-size:1.2rem}
  .day-list::before{left:50px}
  .day-time::after{right:-14px;width:12px;height:12px}
  .day-body{padding-left:28px}
  .ftr-inner{flex-direction:column;gap:24px}
}
@media (max-width:640px){
  .points-grid{grid-template-columns:1fr}
  .job-hero-cta{flex-direction:column;align-items:stretch}
  .job-hero-cta .btn-main,.job-hero-cta .btn-ghost{text-align:center;justify-content:center}
}
</style>
</head>
<body>

<header class="hdr">
  <a href="${canonicalBase}" class="hdr-logo">${c.header.logo_image
    ? `<div class="hdr-logo-icon has-img"><img src="${esc(c.header.logo_image)}" alt="${esc(c.header.company_name)}"></div>`
    : ''}${esc(c.header.company_name)}</a>
  <nav class="hdr-nav">
    ${navLinks.map(l => `<a href="${l.href}">${l.label}</a>`).join('\n    ')}
    <a href="#entry" class="hdr-cta">応募する</a>
  </nav>
  <button class="hamburger" id="js-ham"><span></span><span></span><span></span></button>
</header>

<div class="mob-nav" id="js-mob">
  <button class="mob-close" id="js-mob-x"><span></span><span></span></button>
  ${navLinks.map(l => `<a href="${l.href}">${l.label}</a>`).join('\n  ')}
  <a href="#entry">応募する</a>
</div>

<section class="job-hero">
  <div class="hero-inner">
    <span class="job-badge">${esc(job.badge || '募集中')}</span>
    <div class="hero-title-wrap">
      <span class="anime-txt">${esc(d.en_title || job.title)}</span>
      <h1 class="hero-jp">${esc(job.title)}</h1>
    </div>
    ${d.tagline ? `<p class="job-tagline">${escBr(d.tagline)}</p>` : ''}
    ${d.intro ? `<p class="hero-sub">${escBr(d.intro)}</p>` : (job.description ? `<p class="hero-sub">${escBr(job.description)}</p>` : '')}
    <div class="job-hero-cta">
      <a href="#entry" class="btn-main">この職種に応募する →</a>
      <a href="${canonicalBase}#openings" class="btn-ghost">← 募集職種一覧へ</a>
    </div>
  </div>
</section>

${d.points && d.points.length ? `
<section class="block">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Points</span>
      <p class="jp-sub">求人のポイント</p>
    </div>
    <div class="points-grid">${pointsHtml}
    </div>
  </div>
</section>` : ''}

${d.ideal_candidate && d.ideal_candidate.length ? `
<section class="block block--alt">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Ideal</span>
      <p class="jp-sub">求める人物像</p>
    </div>
    <div class="points-grid">${idealHtml}
    </div>
  </div>
</section>` : ''}

${d.requirements && d.requirements.length ? `
<section class="block">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Requirements</span>
      <p class="jp-sub">募集要項</p>
    </div>
    <dl class="req-table">${reqHtml}
    </dl>
  </div>
</section>` : ''}

${d.selection_flow && d.selection_flow.length ? `
<section class="block">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Selection</span>
      <p class="jp-sub">選考フロー</p>
    </div>
    <div class="flow-list">${flowHtml}
    </div>
  </div>
</section>` : ''}

${d.employee ? `
<section class="block block--alt">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">Interview</span>
      <p class="jp-sub">社員紹介</p>
    </div>
    <div class="emp-card">
      <div class="emp-photo"><img src="${esc(d.employee.photo)}" alt="${esc(d.employee.name)}"></div>
      <div class="emp-body">
        <div class="emp-meta">${esc(d.employee.dept)} / ${esc(d.employee.joined)}</div>
        <h3 class="emp-name">${esc(d.employee.name)}</h3>
        <div class="emp-qa">${empQaHtml}
        </div>
      </div>
    </div>
  </div>
</section>` : ''}

${d.day_in_life && d.day_in_life.length ? `
<section class="block">
  <div class="wrap fade-in">
    <div class="sec-head">
      <span class="sec-en">A Day</span>
      <p class="jp-sub">1日の流れ</p>
    </div>
    <div class="day-list">${dayHtml}
    </div>
  </div>
</section>` : ''}

<section id="entry" class="cta">
  <div class="wrap fade-in">
    <h2>${esc(job.title)}に応募する</h2>
    <p>${esc(c.cta.sub || '一緒に働ける仲間をお待ちしています')}</p>
    <a href="${canonicalBase}/entry?position=${encodeURIComponent(job.title)}" class="btn-main">${esc(c.cta.button_label || 'エントリーする')} →</a>
  </div>
</section>

<footer class="ftr">
  <div class="wrap">
    <div class="ftr-inner">
      <div class="ftr-brand"><h2>${esc(c.footer.company_name)}</h2><p>${esc(c.footer.tagline)}</p></div>
      <div class="ftr-tbl"><table>
        <tr><th>所在地</th><td>${escBr(c.footer.address)}</td></tr>
        <tr><th>設立</th><td>${esc(c.footer.founded)}</td></tr>
        <tr><th>代表</th><td>${esc(c.footer.representative)}</td></tr>
        <tr><th>事業</th><td>${esc(c.footer.business)}</td></tr>
      </table></div>
    </div>
    <p class="ftr-copy">© 2026 ${esc(c.footer.company_name)}</p>
  </div>
</footer>

<script>
document.addEventListener('DOMContentLoaded',()=>{
  const io=new IntersectionObserver(e=>{e.forEach(e=>{if(e.isIntersecting){e.target.classList.add('is-visible');io.unobserve(e.target)}})},{threshold:.08});
  document.querySelectorAll('.fade-in').forEach(e=>io.observe(e));
  const ao=new IntersectionObserver(e=>{e.forEach(e=>{if(e.isIntersecting){e.target.classList.add('anime');ao.unobserve(e.target)}})},{root:null,rootMargin:"0% 0px -200px 0px",threshold:0});
  document.querySelectorAll('.anime-txt').forEach(e=>ao.observe(e));
  setTimeout(()=>{document.querySelectorAll('.job-hero .anime-txt').forEach(e=>e.classList.add('anime'))},400);
  const h=document.getElementById('js-ham'),n=document.getElementById('js-mob'),x=document.getElementById('js-mob-x');
  if(h&&n){h.onclick=()=>{h.classList.toggle('is-active');n.classList.toggle('is-active')};
  if(x)x.onclick=()=>{h.classList.remove('is-active');n.classList.remove('is-active')};
  n.querySelectorAll('a').forEach(a=>a.onclick=()=>{h.classList.remove('is-active');n.classList.remove('is-active')})}
  document.querySelectorAll('a[href^="#"]').forEach(a=>{a.onclick=function(e){const t=document.querySelector(this.getAttribute('href'));if(t){e.preventDefault();window.scrollTo({top:t.getBoundingClientRect().top+scrollY-72,behavior:'smooth'})}}});
});
</script>
<script>
(function(){
  try {
    var slug = "${slug}";
    var sid = sessionStorage.getItem('lp_sid_'+slug);
    if (!sid) { sid = Date.now()+Math.random().toString(36).slice(2); sessionStorage.setItem('lp_sid_'+slug, sid); }
    var ep = '/api/lp/'+slug+'/track';
    fetch(ep, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      keepalive:true,
      body: JSON.stringify({event_type:'page_view', path:location.pathname, session_id:sid, referrer:document.referrer||''})
    }).catch(function(){});
  } catch(e){}
})();
</script>
</body>
</html>`
}
