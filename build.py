#!/usr/bin/env python3
"""Genera el sitio estático bilingüe a partir de content/ y templates/.

Español en la raíz (URLs históricas: index.html, proys/*.html…) e inglés bajo en/.
Solo usa la biblioteca estándar de Python (3.11 o superior).

Uso:
    python build.py              # genera las páginas y verifica los enlaces
    python -m http.server 8000   # previsualizar en http://localhost:8000/

Datos:
    content/site.toml            nombre, lema, Info, CV, contacto, textos de interfaz
    content/projects/<slug>.toml una ficha por proyecto; <slug> es la URL proys/<slug>.html
    - clave_es / clave_en para textos traducidos; una clave sin sufijo vale para ambos.
    - *texto* = cursiva; una línea en blanco separa párrafos.
    - images = { prefix = "...", count = N } busca assets/jpg/<prefix>-01.jpg … -NN.jpg;
      thumb es la miniatura en assets/jpg/tn/.
    - sort ordena los proyectos (descendente); cv_es / cv_en los incluye en el CV.
"""
import datetime
import html
import os
import posixpath
import re
import struct
import sys
import tomllib
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / 'content'
JPG = 'assets/jpg'
LANGS = ('es', 'en')
OTHER = {'es': 'en', 'en': 'es'}
OG_LOCALE = {'es': 'es_CO', 'en': 'en_US'}

PAGES = {
    'home': {'es': 'index.html', 'en': 'en/index.html'},
    'info': {'es': 'info.html', 'en': 'en/info.html'},
    'cv': {'es': 'cv.html', 'en': 'en/cv.html'},
    'projects': {'es': 'proys.html', 'en': 'en/projects.html'},
    'contact': {'es': 'contacto.html', 'en': 'en/contact.html'},
}
NAV = ('info', 'cv', 'projects', 'contact')

# Páginas retiradas cuya URL se conserva con una redirección.
REDIRECTS = {'proys/acciones-directas.html': 'proys.html'}

SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}

warnings = []
_listing = {}
_sizes = {}


# --- utilidades -------------------------------------------------------------

def t(data, key, lang, default=None):
    """Texto traducido: busca clave_<lang> y luego la clave sin sufijo."""
    return data.get(f'{key}_{lang}', data.get(key, default))


def esc(text):
    return html.escape(text, quote=True)


def inline(text):
    """Escapa HTML y convierte *texto* en cursiva."""
    return re.sub(r'\*(.+?)\*', r'<em>\1</em>', html.escape(text, quote=False))


def plain(text):
    return text.replace('*', '')


def paragraphs(text):
    parts = [p.strip() for p in re.split(r'\n\s*\n', text.strip())]
    return '\n'.join(f'<p>{inline(p)}</p>' for p in parts if p)


def summary(text, limit=155):
    first = plain(re.split(r'\n\s*\n', text.strip())[0])
    if len(first) <= limit:
        return first
    return first[:limit].rsplit(' ', 1)[0] + '…'


def rel(page, target):
    """Ruta relativa desde la página `page` hasta `target` (ambas relativas a ROOT)."""
    return posixpath.relpath(target, posixpath.dirname(page) or '.')


def url_path(path):
    """Ruta pública: index.html se sirve como el directorio."""
    return path[:-len('index.html')] if path.endswith('index.html') else path


def exists_exact(path):
    """Comprueba que el archivo existe respetando mayúsculas, como GitHub Pages."""
    current = ROOT
    for part in path.split('/'):
        if current not in _listing:
            try:
                _listing[current] = set(os.listdir(current))
            except (FileNotFoundError, NotADirectoryError):
                return False
        if part not in _listing[current]:
            return False
        current = current / part
    return True


def jpeg_size(path):
    if path in _sizes:
        return _sizes[path]
    data = (ROOT / path).read_bytes()
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
        elif marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
        elif marker in SOF_MARKERS:
            height, width = struct.unpack('>HH', data[i + 5:i + 9])
            _sizes[path] = (width, height)
            return width, height
        else:
            i += 2 + struct.unpack('>H', data[i + 2:i + 4])[0]
    raise ValueError(f'No se pudo leer el tamaño de {path}')


def img(page, src, alt, lazy=True):
    width, height = jpeg_size(src)
    attrs = f'src="{rel(page, src)}" alt="{esc(alt)}" width="{width}" height="{height}"'
    if lazy:
        attrs += ' loading="lazy" decoding="async"'
    return f'<img {attrs}>'


def vimeo_embed(url):
    match = re.fullmatch(r'https://vimeo\.com/(\d+)', url)
    if match:
        url = f'https://player.vimeo.com/video/{match.group(1)}'
    return url + ('&' if '?' in url else '?') + 'dnt=1'


def project_path(slug, lang):
    return f'proys/{slug}.html' if lang == 'es' else f'en/projects/{slug}.html'


def write(path, text):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')


# --- datos ------------------------------------------------------------------

def load_site():
    return tomllib.loads((CONTENT / 'site.toml').read_text(encoding='utf-8'))


def load_projects():
    projects = []
    for source in sorted((CONTENT / 'projects').glob('*.toml')):
        project = tomllib.loads(source.read_text(encoding='utf-8'))
        project['slug'] = source.stem

        project['image_list'] = []
        spec = project.get('images')
        if spec:
            missing = []
            for n in range(1, spec['count'] + 1):
                name = f"{JPG}/{spec['prefix']}-{n:02d}.jpg"
                (project['image_list'] if exists_exact(name) else missing).append(name)
            if missing:
                warnings.append(f'{source.stem}: faltan {len(missing)} imágenes ({spec["prefix"]}-NN.jpg)')

        project['thumb_path'] = None
        if project.get('thumb'):
            thumb = f"{JPG}/tn/{project['thumb']}"
            if exists_exact(thumb):
                project['thumb_path'] = thumb
            else:
                warnings.append(f'{source.stem}: falta la miniatura {thumb}')
        projects.append(project)
    projects.sort(key=lambda p: p['sort'], reverse=True)
    return projects


# --- piezas de página -------------------------------------------------------

def site_header(site, lang, page, alt_page, section):
    ui = site['ui'][lang]
    items = []
    for number, key in enumerate(NAV, 1):
        target = PAGES[key][lang]
        current = ''
        if target == page:
            current = ' aria-current="page"'
        elif key == section:
            current = ' aria-current="true"'
        items.append(f'<li><a href="{rel(page, target)}"{current}>'
                     f'<span class="num">{number:02d}</span> {esc(ui["nav_" + key])}</a></li>')

    langs = []
    for code in LANGS:
        name = site['ui'][code]['language']
        if code == lang:
            langs.append(f'<li><span aria-current="true" title="{esc(name)}">{code.upper()}</span></li>')
        else:
            href = rel(page, alt_page)
            langs.append(f'<li><a href="{href}" hreflang="{code}" lang="{code}" title="{esc(name)}">'
                         f'{code.upper()}</a></li>')

    return f'''<header class="site-header">
<div class="bar">
<a class="name" href="{rel(page, PAGES['home'][lang])}">{esc(site['name'])}</a>
<button class="button menu-toggle" type="button" aria-expanded="false" aria-controls="site-nav">{esc(ui['menu'])}</button>
</div>
<nav id="site-nav" class="site-nav" aria-label="{esc(ui['main_nav'])}">
<ol>
{chr(10).join(items)}
</ol>
<ul class="lang" aria-label="{esc(ui['lang_nav'])}">
{chr(10).join(langs)}
</ul>
</nav>
</header>'''


def site_footer(site):
    year = datetime.date.today().year
    return f'<footer class="site-footer"><p class="mono">© {year} {esc(site["name"])}</p></footer>'


def render(site, lang, page, alt_page, title, description, content, section,
           og_image=None, og_type='website'):
    ui = site['ui'][lang]
    base = site['base_url']
    es_page = page if lang == 'es' else alt_page
    template = Template((ROOT / 'templates' / 'base.html').read_text(encoding='utf-8'))
    full_title = site['name'] if section == 'home' else f'{title} — {site["name"]}'
    write(page, template.substitute(
        lang=lang,
        alt_lang=OTHER[lang],
        title=esc(full_title),
        description=esc(description),
        canonical=base + url_path(page),
        alt_url=base + url_path(alt_page),
        default_url=base + url_path(es_page),
        og_type=og_type,
        og_locale=OG_LOCALE[lang],
        og_image=base + (og_image or site['info']['portrait']),
        site_name=esc(site['name']),
        root=rel(page, '.') + '/' if '/' in page else '',
        body_class=f'page-{section}',
        skip=esc(ui['skip']),
        header=site_header(site, lang, page, alt_page, section),
        content=content,
        footer=site_footer(site),
    ))
    return page


def sheet(rows):
    body = ''.join(f'<div><dt>{esc(label)}</dt><dd>{value}</dd></div>' for label, value in rows if value)
    return f'<dl class="sheet">{body}</dl>' if body else ''


def contact_links(site):
    """(etiqueta, enlace) de correo, LinkedIn y GitHub; el texto visible es la URL legible."""
    def display(url):
        return url.split('://', 1)[1].removeprefix('www.').rstrip('/')
    return [
        ('email', f'<a href="mailto:{esc(site["email"])}">{esc(site["email"])}</a>'),
        ('LinkedIn', f'<a href="{esc(site["linkedin"])}">{esc(display(site["linkedin"]))}</a>'),
        ('GitHub', f'<a href="{esc(site["github"])}">{esc(display(site["github"]))}</a>'),
    ]


def project_title(project, lang):
    return t(project, 'title', lang)


def project_meta(project, lang):
    parts = [project.get('year'), t(project, 'tech', lang)]
    return ' · '.join(plain(p) for p in parts if p)


def thumb_block(page, project, lang, lazy=True):
    if project['thumb_path']:
        return f'<div class="thumb">{img(page, project["thumb_path"], "", lazy=lazy)}</div>'
    return f'<div class="thumb placeholder" aria-hidden="true"><span>{esc(project_title(project, lang))}</span></div>'


# --- páginas ----------------------------------------------------------------

def page_home(site, projects, lang):
    ui = site['ui'][lang]
    page, alt = PAGES['home'][lang], PAGES['home'][OTHER[lang]]
    featured = next(p for p in projects if p['slug'] == site['featured'])
    href = rel(page, project_path(featured['slug'], lang))
    content = f'''<h1 class="visually-hidden">{esc(site['name'])}</h1>
<p class="tagline">{inline(t(site, 'tagline', lang))}</p>
<figure class="feature">
<a href="{href}" tabindex="-1" aria-hidden="true">{thumb_block(page, featured, lang, lazy=False)}</a>
<figcaption><span class="mono label">{esc(ui['featured'])}</span>
<a href="{href}">{inline(project_title(featured, lang))}</a> <span class="mono">{esc(featured.get('year', ''))}</span></figcaption>
</figure>'''
    return render(site, lang, page, alt, site['name'], t(site, 'description', lang), content, 'home',
                  og_image=featured['thumb_path'])


def page_info(site, lang):
    ui = site['ui'][lang]
    page, alt = PAGES['info'][lang], PAGES['info'][OTHER[lang]]
    info = site['info']
    content = f'''<h1>{esc(ui['nav_info'])}</h1>
<div class="info">
<figure class="portrait">{img(page, info['portrait'], ui['portrait_alt'], lazy=False)}</figure>
<div class="prose">
{paragraphs(t(info, 'bio', lang))}
</div>
</div>'''
    return render(site, lang, page, alt, ui['nav_info'], summary(t(info, 'bio', lang)), content, 'info')


def entry(date, heading, lines):
    body = ''.join(lines)
    return (f'<article class="entry"><p class="entry-date mono">{esc(date)}</p>'
            f'<div><h3>{heading}</h3>{body}</div></article>')


def page_cv(site, projects, lang):
    ui = site['ui'][lang]
    cv = site['cv']
    page, alt = PAGES['cv'][lang], PAGES['cv'][OTHER[lang]]

    def title(key):
        return esc(t(cv, f'{key}_title', lang))

    experience = '\n'.join(entry(
        t(e, 'dates', lang), esc(e['org']),
        [f'<p>{inline(t(e, "role", lang))}</p>']
        + ([f'<p class="detail">{inline(t(e, "detail", lang))}</p>'] if t(e, 'detail', lang) else []),
    ) for e in cv['experience'])

    def studies(items):
        return '\n'.join(entry(t(e, 'dates', lang), inline(t(e, 'title', lang)), [f'<p>{esc(e["org"])}</p>'])
                         for e in items)

    art = '\n'.join(entry(
        t(p, 'cv_date', lang) or t(p, 'date', lang),
        f'<a href="{rel(page, project_path(p["slug"], lang))}">{inline(t(p, "cv", lang))}</a>',
        [],
    ) for p in projects if t(p, 'cv', lang))

    skills = ''.join(f'<li>{esc(s)}</li>' for s in t(cv, 'skills', lang))
    tech = sheet([(t(row, 'label', lang), esc(row['items'])) for row in cv['tech']])
    contacts = ''.join(f'<li>{value}</li>' for _, value in contact_links(site))

    content = f'''<header class="cv-head">
<h1>{esc(site['full_name'])}</h1>
<p class="mono headline">{esc(t(cv, 'headline', lang))}</p>
<ul class="contact-list mono">{contacts}</ul>
<button class="button js-only print" type="button" data-print>{esc(ui['print'])}</button>
</header>
<section aria-labelledby="cv-profile"><h2 id="cv-profile">{title('profile')}</h2>
<div class="prose">{paragraphs(t(cv, 'profile', lang))}</div></section>
<section aria-labelledby="cv-experience"><h2 id="cv-experience">{title('experience')}</h2>
{experience}</section>
<section aria-labelledby="cv-education"><h2 id="cv-education">{title('education')}</h2>
{studies(cv['education'])}</section>
<section aria-labelledby="cv-courses"><h2 id="cv-courses">{title('courses')}</h2>
{studies(cv['courses'])}</section>
<section aria-labelledby="cv-skills"><h2 id="cv-skills">{title('skills')}</h2>
<ul class="skills">{skills}</ul>
{tech}</section>
<section aria-labelledby="cv-art"><h2 id="cv-art">{title('art')}</h2>
{art}</section>'''
    return render(site, lang, page, alt, ui['nav_cv'], summary(t(cv, 'profile', lang)), content, 'cv')


def page_projects(site, projects, lang):
    ui = site['ui'][lang]
    page, alt = PAGES['projects'][lang], PAGES['projects'][OTHER[lang]]
    cards = []
    for index, project in enumerate(projects):
        href = rel(page, project_path(project['slug'], lang))
        cards.append(f'''<li class="card">
<a href="{href}">{thumb_block(page, project, lang, lazy=index >= 4)}
<h2 class="card-title">{inline(project_title(project, lang))}</h2></a>
<p class="card-meta mono">{esc(project_meta(project, lang))}</p>
</li>''')
    content = f'''<h1>{esc(ui['nav_projects'])}</h1>
<ul class="grid">
{chr(10).join(cards)}
</ul>'''
    return render(site, lang, page, alt, ui['nav_projects'], t(site, 'description', lang), content, 'projects')


def page_project(site, project, lang):
    ui = site['ui'][lang]
    page, alt = project_path(project['slug'], lang), project_path(project['slug'], OTHER[lang])
    title = project_title(project, lang)
    images = project['image_list']
    total = len(images)

    def figure(n, src, lazy=True):
        alt_text = f'{plain(title)} — {ui["image"]} {n} {ui["of"]} {total}'
        return f'<figure>{img(page, src, alt_text, lazy=lazy)}</figure>'

    links = ''
    if project.get('links'):
        links = '<ul class="plain">' + ''.join(
            f'<li><a href="{esc(link["url"])}">{esc(t(link, "label", lang))}</a></li>'
            for link in project['links']) + '</ul>'

    rows = [
        (ui['date'], esc(t(project, 'date', lang) or '')),
        (ui['place'], inline(t(project, 'place', lang) or '')),
        (ui['role'], inline(t(project, 'role', lang) or '')),
        (ui['tech'], esc(t(project, 'tech', lang) or '')),
        (ui['credits'], inline(t(project, 'credits', lang) or '')),
        (ui['links'], links),
    ]

    lead = f'<div class="lead">{figure(1, images[0], lazy=False)}</div>' if images else ''
    gallery = ''
    if total > 1:
        gallery = '<div class="gallery">' + ''.join(
            figure(n, src) for n, src in enumerate(images[1:], 2)) + '</div>'
    videos = ''
    if project.get('videos'):
        frames = ''.join(
            f'<div class="video"><iframe src="{esc(vimeo_embed(url))}" '
            f'title="{esc(ui["video"])} {n} — {esc(plain(title))}" loading="lazy" '
            f'allow="fullscreen; picture-in-picture" allowfullscreen></iframe></div>'
            for n, url in enumerate(project['videos'], 1))
        videos = (f'<section class="videos" aria-labelledby="videos-title">'
                  f'<h2 id="videos-title" class="visually-hidden">{esc(ui["videos"])}</h2>{frames}</section>')

    content = f'''<article class="project">
<p class="back mono"><a href="{rel(page, PAGES['projects'][lang])}">← {esc(ui['back'])}</a></p>
<h1>{inline(title)}</h1>
{sheet(rows)}
{lead}
<div class="prose">
{paragraphs(t(project, 'description', lang))}
</div>
{gallery}
{videos}
</article>'''
    return render(site, lang, page, alt, plain(title), summary(t(project, 'description', lang)), content,
                  'projects', og_image=project['thumb_path'], og_type='article')


def page_contact(site, lang):
    ui = site['ui'][lang]
    page, alt = PAGES['contact'][lang], PAGES['contact'][OTHER[lang]]
    links = contact_links(site)
    rows = [(ui['email'] if label == 'email' else label, value) for label, value in links]
    content = f'''<h1>{esc(ui['nav_contact'])}</h1>
<p class="prose">{inline(t(site['contact'], 'intro', lang))}</p>
{sheet(rows)}'''
    return render(site, lang, page, alt, ui['nav_contact'], t(site['contact'], 'intro', lang), content, 'contact')


def page_redirect(site, page, target):
    href = rel(page, target)
    write(page, f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{esc(site['name'])}</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="{site['base_url'] + target}">
<meta http-equiv="refresh" content="0; url={href}">
</head>
<body>
<p><a href="{href}">{esc(site['ui']['es']['nav_projects'])}</a></p>
</body>
</html>
''')
    return page


# --- verificación -----------------------------------------------------------

def check_links(pages):
    """Todas las rutas internas de las páginas y del CSS deben existir (con mayúsculas exactas)."""
    _listing.clear()
    errors = []
    sources = [(page, r'(?:href|src)="([^"]+)"') for page in pages]
    sources.append(('assets/css/site.css', r'url\("?([^")]+)"?\)'))
    for source, pattern in sources:
        text = (ROOT / source).read_text(encoding='utf-8')
        for ref in re.findall(pattern, text):
            if re.match(r'(?:[a-z][a-z0-9+.-]*:|#|//)', ref):
                continue
            path = ref.split('#')[0].split('?')[0]
            target = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
            if target.startswith('..') or not exists_exact(target):
                errors.append(f'{source}: {ref}')
    return errors


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    site = load_site()
    projects = load_projects()
    pages = []
    for lang in LANGS:
        pages.append(page_home(site, projects, lang))
        pages.append(page_info(site, lang))
        pages.append(page_cv(site, projects, lang))
        pages.append(page_projects(site, projects, lang))
        pages.append(page_contact(site, lang))
        pages.extend(page_project(site, project, lang) for project in projects)
    pages.extend(page_redirect(site, page, target) for page, target in REDIRECTS.items())

    generated = set(pages)
    for old in sorted((ROOT / 'proys').glob('*.html')):
        if f'proys/{old.name}' not in generated:
            warnings.append(f'proys/{old.name} no se generó (¿proyecto retirado sin redirección?)')

    errors = check_links(pages)
    print(f'{len(pages)} páginas generadas.')
    for message in warnings:
        print(f'  aviso: {message}')
    for message in errors:
        print(f'  ERROR enlace roto: {message}')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
