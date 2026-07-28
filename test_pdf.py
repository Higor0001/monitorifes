import urllib.request
import urllib.parse
import ssl
import bs4

ctx = ssl._create_unverified_context()
req = urllib.request.Request(
    'https://cachoeiro.ifes.edu.br/processosseletivos/alunos/17163-edital-19-2026-chamada-publica-de-oferta-de-vagas-dos-cursos-tecnicos-concomitante-e-subsequente',
    headers={'User-Agent': 'Mozilla/5.0'}
)

raw_bytes = urllib.request.urlopen(req, context=ctx).read()

# Tenta decodificar como utf-8
html_utf8 = raw_bytes.decode('utf-8', errors='replace')
soup = bs4.BeautifulSoup(html_utf8, 'html.parser')

base = 'https://cachoeiro.ifes.edu.br'

for a in soup.find_all('a', href=True):
    href = a['href']
    if '.pdf' in href.lower():
        full_raw = urllib.parse.urljoin(base, href)
        
        # Converte unquoted para quoted seguro
        unquoted = urllib.parse.unquote(full_raw)
        parsed = urllib.parse.urlparse(unquoted)
        encoded_path = urllib.parse.quote(parsed.path, safe='/')
        final_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))
        
        print("LINK ENCONTRADO:")
        print("  Text:", a.get_text(strip=True))
        print("  Raw href:", href)
        print("  Final URL:", final_url)
        
        try:
            r = urllib.request.urlopen(urllib.request.Request(final_url, headers={'User-Agent': 'Mozilla/5.0'}), context=ctx)
            print("  Status:", r.status, "| Size:", len(r.read()), "bytes")
        except Exception as e:
            print("  ERRO AO BAIXAR:", e)
        print("-" * 60)
