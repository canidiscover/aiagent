from flask import Flask, request, jsonify
import requests, re, tldextract, concurrent.futures, json, time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import threading
from collections import defaultdict, Counter

app = Flask(__name__)

# ---------- Ultra Fast Config ----------
MAX_WORKERS = 20  # More workers for deep crawling
TIMEOUT = 5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

# ---------- Deep Crawler ----------
def deep_crawl(start_url, max_pages=50):
    """Extremely deep crawler that gets EVERYTHING"""
    visited = set()
    results = []
    url_queue = []
    url_queue.append(start_url)
    domain = tldextract.extract(start_url).domain
    
    # First, get ALL URLs from sitemap and robots
    initial_urls = get_all_urls_from_sitemap(start_url)
    url_queue.extend(initial_urls)
    
    lock = threading.Lock()
    
    def worker():
        while True:
            with lock:
                if not url_queue or len(results) >= max_pages:
                    break
                url = url_queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)
            
            try:
                # Fast request
                resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                if resp.status_code == 200:
                    content = resp.text
                    
                    # Extract page data
                    page_data = extract_all_data(url, content, resp.headers)
                    
                    with lock:
                        results.append(page_data)
                    
                    # Extract MORE links from this page
                    if len(results) < max_pages:
                        new_links = extract_all_links(content, url, domain)
                        for link in new_links:
                            if link not in visited and link not in url_queue:
                                url_queue.append(link)
                                
            except:
                continue
    
    # Start many workers
    threads = []
    for _ in range(min(MAX_WORKERS, max_pages)):
        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        threads.append(t)
    
    # Wait with timeout
    start_time = time.time()
    for t in threads:
        t.join(timeout=20)
    
    return results

def get_all_urls_from_sitemap(base_url):
    """Get ALL URLs from sitemap.xml and robots.txt"""
    urls = []
    
    # Check sitemap.xml
    sitemap_url = urljoin(base_url, 'sitemap.xml')
    try:
        resp = requests.get(sitemap_url, timeout=3)
        if resp.status_code == 200:
            # Parse sitemap
            locs = re.findall(r'<loc>(.*?)</loc>', resp.text, re.IGNORECASE)
            urls.extend([loc.strip() for loc in locs if loc.strip()])
            
            # Also check for sitemap index
            sitemap_index = re.findall(r'<sitemap>\s*<loc>(.*?)</loc>', resp.text, re.IGNORECASE)
            for index_url in sitemap_index:
                try:
                    idx_resp = requests.get(index_url.strip(), timeout=3)
                    if idx_resp.status_code == 200:
                        sub_locs = re.findall(r'<loc>(.*?)</loc>', idx_resp.text, re.IGNORECASE)
                        urls.extend([loc.strip() for loc in sub_locs if loc.strip()])
                except:
                    continue
    except:
        pass
    
    # Check robots.txt for sitemap
    robots_url = urljoin(base_url, 'robots.txt')
    try:
        resp = requests.get(robots_url, timeout=3)
        if resp.status_code == 200:
            # Extract sitemap from robots.txt
            sitemaps = re.findall(r'Sitemap:\s*(.*)', resp.text, re.IGNORECASE)
            for sitemap in sitemaps:
                try:
                    sm_resp = requests.get(sitemap.strip(), timeout=3)
                    if sm_resp.status_code == 200:
                        locs = re.findall(r'<loc>(.*?)</loc>', sm_resp.text, re.IGNORECASE)
                        urls.extend([loc.strip() for loc in locs if loc.strip()])
                except:
                    continue
    except:
        pass
    
    return list(set(urls))

def extract_all_links(html_content, base_url, domain):
    """Extract ALL links from page"""
    links = set()
    
    # Extract href links
    href_matches = re.findall(r'href=[\'"]([^\'"]+)[\'"]', html_content, re.IGNORECASE)
    for href in href_matches:
        full_url = normalize_url(base_url, href)
        if full_url and domain in full_url:
            links.add(full_url)
    
    # Extract src links
    src_matches = re.findall(r'src=[\'"]([^\'"]+)[\'"]', html_content, re.IGNORECASE)
    for src in src_matches:
        full_url = normalize_url(base_url, src)
        if full_url and domain in full_url:
            links.add(full_url)
    
    # Extract action links
    action_matches = re.findall(r'action=[\'"]([^\'"]+)[\'"]', html_content, re.IGNORECASE)
    for action in action_matches:
        full_url = normalize_url(base_url, action)
        if full_url and domain in full_url:
            links.add(full_url)
    
    # Extract data-src, data-url, etc.
    data_matches = re.findall(r'data-[a-z]+=[\'"]([^\'"]+)[\'"]', html_content, re.IGNORECASE)
    for data in data_matches:
        if data.startswith(('http://', 'https://', '/')):
            full_url = normalize_url(base_url, data)
            if full_url and domain in full_url:
                links.add(full_url)
    
    return list(links)

def extract_all_data(url, html_content, headers):
    """Extract EVERYTHING from a page"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Basic Info
    data = {
        'url': url,
        'title': soup.title.string[:200] if soup.title else '',
        'meta_description': '',
        'meta_keywords': '',
        'word_count': len(soup.get_text().split()),
        'character_count': len(soup.get_text()),
        'language': soup.html.get('lang', '') if soup.html else '',
        'doctype': get_doctype(html_content),
        'response_headers': dict(headers),
        'status_code': 200
    }
    
    # 2. Meta Tags
    meta_data = {}
    for meta in soup.find_all('meta'):
        name = meta.get('name') or meta.get('property') or meta.get('http-equiv') or ''
        content = meta.get('content', '')
        if name and content:
            meta_data[name.lower()] = content[:500]
        
        if name.lower() == 'description':
            data['meta_description'] = content[:500]
        elif name.lower() == 'keywords':
            data['meta_keywords'] = content[:500]
    
    data['meta_tags'] = meta_data
    
    # 3. All Links
    all_links = []
    internal_links = []
    external_links = []
    for link in soup.find_all('a', href=True):
        href = link['href']
        text = link.get_text(strip=True)[:100]
        full_url = normalize_url(url, href)
        
        link_data = {
            'text': text,
            'href': href,
            'full_url': full_url,
            'title': link.get('title', '')[:100],
            'rel': link.get('rel', [])
        }
        
        all_links.append(link_data)
        
        if full_url:
            if tldextract.extract(url).domain in full_url:
                internal_links.append(link_data)
            else:
                external_links.append(link_data)
    
    data['links'] = {
        'total': len(all_links),
        'internal': internal_links[:50],  # Limit
        'external': external_links[:50]   # Limit
    }
    
    # 4. All Images
    images = []
    for img in soup.find_all('img'):
        src = img.get('src', '')
        if src:
            images.append({
                'src': src,
                'alt': img.get('alt', '')[:100],
                'title': img.get('title', '')[:100],
                'width': img.get('width'),
                'height': img.get('height'),
                'full_url': normalize_url(url, src)
            })
    
    data['images'] = images[:50]  # Limit
    
    # 5. All Scripts
    scripts = []
    for script in soup.find_all('script'):
        script_data = {
            'src': script.get('src', ''),
            'type': script.get('type', ''),
            'async': script.get('async', False),
            'defer': script.get('defer', False),
            'has_content': bool(script.string and script.string.strip()),
            'content_length': len(script.string or '')
        }
        
        if script_data['src']:
            script_data['full_url'] = normalize_url(url, script_data['src'])
        
        scripts.append(script_data)
    
    data['scripts'] = scripts
    
    # 6. All Stylesheets
    styles = []
    for link in soup.find_all('link', rel='stylesheet'):
        href = link.get('href', '')
        if href:
            styles.append({
                'href': href,
                'media': link.get('media', ''),
                'full_url': normalize_url(url, href)
            })
    
    for style in soup.find_all('style'):
        styles.append({
            'inline': True,
            'content_length': len(style.string or '') if style.string else 0
        })
    
    data['stylesheets'] = styles
    
    # 7. All Forms with EVERYTHING
    forms = []
    for form in soup.find_all('form'):
        form_data = {
            'action': form.get('action', ''),
            'method': form.get('method', 'GET').upper(),
            'enctype': form.get('enctype', ''),
            'target': form.get('target', ''),
            'id': form.get('id', ''),
            'name': form.get('name', ''),
            'class': form.get('class', []),
            'inputs': [],
            'buttons': [],
            'labels': []
        }
        
        # All inputs
        for inp in form.find_all(['input', 'textarea', 'select']):
            input_data = {
                'tag': inp.name,
                'type': inp.get('type', 'text'),
                'name': inp.get('name', ''),
                'id': inp.get('id', ''),
                'class': inp.get('class', []),
                'placeholder': inp.get('placeholder', ''),
                'value': inp.get('value', ''),
                'required': inp.get('required') is not None,
                'disabled': inp.get('disabled') is not None,
                'readonly': inp.get('readonly') is not None,
                'maxlength': inp.get('maxlength'),
                'minlength': inp.get('minlength'),
                'pattern': inp.get('pattern', ''),
                'autocomplete': inp.get('autocomplete', ''),
                'aria_label': inp.get('aria-label', '')
            }
            
            # For select options
            if inp.name == 'select':
                options = []
                for option in inp.find_all('option'):
                    options.append({
                        'value': option.get('value', ''),
                        'text': option.get_text(strip=True)[:100],
                        'selected': option.get('selected') is not None
                    })
                input_data['options'] = options
            
            form_data['inputs'].append(input_data)
        
        # All buttons
        for btn in form.find_all('button'):
            form_data['buttons'].append({
                'type': btn.get('type', 'submit'),
                'name': btn.get('name', ''),
                'value': btn.get('value', ''),
                'text': btn.get_text(strip=True)[:100]
            })
        
        # Associated labels
        for lbl in soup.find_all('label'):
            if lbl.get('for'):
                form_data['labels'].append({
                    'for': lbl.get('for'),
                    'text': lbl.get_text(strip=True)[:100]
                })
        
        forms.append(form_data)
    
    data['forms'] = forms
    
    # 8. Headings Structure
    headings = defaultdict(list)
    for level in range(1, 7):
        for h in soup.find_all(f'h{level}'):
            headings[f'h{level}'].append({
                'text': h.get_text(strip=True)[:200],
                'id': h.get('id', ''),
                'class': h.get('class', [])
            })
    
    data['headings'] = dict(headings)
    
    # 9. Tables
    tables = []
    for table in soup.find_all('table'):
        table_data = {
            'id': table.get('id', ''),
            'class': table.get('class', []),
            'caption': table.find('caption').get_text(strip=True)[:200] if table.find('caption') else '',
            'headers': [],
            'rows': []
        }
        
        # Headers
        for th in table.find_all('th'):
            table_data['headers'].append(th.get_text(strip=True)[:100])
        
        # Rows
        for tr in table.find_all('tr'):
            row = []
            for td in tr.find_all('td'):
                row.append(td.get_text(strip=True)[:100])
            if row:
                table_data['rows'].append(row)
        
        tables.append(table_data)
    
    data['tables'] = tables[:10]  # Limit
    
    # 10. Lists
    lists = []
    for ul in soup.find_all(['ul', 'ol']):
        list_data = {
            'type': ul.name,
            'id': ul.get('id', ''),
            'class': ul.get('class', []),
            'items': [li.get_text(strip=True)[:100] for li in ul.find_all('li')]
        }
        lists.append(list_data)
    
    data['lists'] = lists[:10]  # Limit
    
    # 11. Comments
    comments = []
    for comment in soup.find_all(string=lambda text: isinstance(text, str) and text.strip().startswith('<!--')):
        comments.append(comment.strip()[:500])
    
    data['html_comments'] = comments[:20]  # Limit
    
    # 12. Text Content Analysis
    all_text = soup.get_text()
    lines = [line.strip() for line in all_text.split('\n') if line.strip()]
    paragraphs = [p.get_text(strip=True) for p in soup.find_all('p')]
    
    data['text_content'] = {
        'lines': lines[:100],  # First 100 non-empty lines
        'paragraphs': paragraphs[:50],  # First 50 paragraphs
        'most_common_words': get_most_common_words(all_text, 20),
        'longest_words': get_longest_words(all_text, 10)
    }
    
    # 13. JSON-LD and Structured Data
    json_ld = []
    for script in soup.find_all('script', type='application/ld+json'):
        if script.string:
            try:
                json_data = json.loads(script.string)
                json_ld.append(json_data)
            except:
                json_ld.append({'raw': script.string[:500]})
    
    data['structured_data'] = json_ld
    
    # 14. Open Graph and Twitter Cards
    og_tags = {}
    twitter_tags = {}
    for meta in soup.find_all('meta'):
        prop = meta.get('property', '') or meta.get('name', '')
        content = meta.get('content', '')
        
        if prop.startswith('og:'):
            og_tags[prop] = content
        elif prop.startswith('twitter:'):
            twitter_tags[prop] = content
    
    data['open_graph'] = og_tags
    data['twitter_cards'] = twitter_tags
    
    # 15. Technology Detection
    data['technology_hints'] = detect_tech_hints(html_content, headers)
    
    # 16. Performance Hints
    data['performance'] = {
        'html_size': len(html_content),
        'image_count': len(images),
        'script_count': len(scripts),
        'stylesheet_count': len(styles),
        'dom_elements': len(soup.find_all())
    }
    
    return data

def get_doctype(html):
    """Extract DOCTYPE"""
    doctype_match = re.match(r'<!DOCTYPE\s+(.*?)\s*>', html, re.IGNORECASE)
    return doctype_match.group(1) if doctype_match else ''

def get_most_common_words(text, n=20):
    """Get most common words"""
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    return [word for word, count in Counter(words).most_common(n)]

def get_longest_words(text, n=10):
    """Get longest words"""
    words = re.findall(r'\b[a-zA-Z]{5,}\b', text)
    return sorted(set(words), key=len, reverse=True)[:n]

def detect_tech_hints(html_content, headers):
    """Detect technology hints"""
    hints = []
    content_lower = html_content.lower()
    
    # Framework hints
    if 'wp-content' in content_lower:
        hints.append('WordPress')
    if 'react' in content_lower:
        hints.append('React')
    if 'vue' in content_lower:
        hints.append('Vue.js')
    if 'angular' in content_lower:
        hints.append('Angular')
    if 'jquery' in content_lower:
        hints.append('jQuery')
    
    # Server hints
    server = headers.get('Server', '')
    if server:
        hints.append(f'Server: {server}')
    
    # CMS hints from meta generator
    generator_match = re.search(r'<meta[^>]*name=["\']generator["\'][^>]*content=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    if generator_match:
        hints.append(f'Generator: {generator_match.group(1)}')
    
    return list(set(hints))

def normalize_url(base, href):
    """Normalize URL"""
    if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:')):
        return None
    
    try:
        full = urljoin(base, href)
        parsed = urlparse(full)
        if parsed.scheme in ('http', 'https'):
            return full
    except:
        pass
    return None

# ---------- Security Files Scanner ----------
def scan_all_files(base_url):
    """Scan ALL common files"""
    common_files = [
        # Security files
        'robots.txt', 'security.txt', '.well-known/security.txt',
        'humans.txt', 'ads.txt', '.htaccess', '.htpasswd',
        
        # Sitemaps
        'sitemap.xml', 'sitemap_index.xml', 'sitemap1.xml',
        
        # Config files
        '.env', '.env.local', '.env.production', '.env.development',
        'config.php', 'configuration.php', 'settings.php', 'wp-config.php',
        'database.yml', 'database.json', 'config.json', 'config.yml',
        
        # Version control
        '.git/config', '.git/HEAD', '.hg/store', '.svn/entries',
        
        # API docs
        'swagger.json', 'openapi.json', 'api-docs', 'graphql',
        'graphiql', 'playground',
        
        # Backup files
        'backup.zip', 'backup.tar.gz', 'backup.sql', 'dump.sql',
        'database.backup', 'backup/database.sql',
        
        # Log files
        'error_log', 'access.log', 'error.log',
        
        # Admin files
        'phpinfo.php', 'test.php', 'info.php', 'admin.php',
        'administrator/', 'wp-admin/', 'cpanel/', 'webmail/',
        
        # Cross-domain
        'crossdomain.xml', 'clientaccesspolicy.xml',
        
        # Other common
        'package.json', 'composer.json', 'requirements.txt',
        'README.md', 'LICENSE', 'CHANGELOG.md'
    ]
    
    results = {}
    
    def check_file(file_path):
        url = urljoin(base_url, file_path)
        try:
            resp = requests.head(url, timeout=2, allow_redirects=False)
            if resp.status_code < 400:
                # If HEAD worked, try GET for content
                resp_get = requests.get(url, timeout=3)
                return {
                    'file': file_path,
                    'url': url,
                    'status': resp.status_code,
                    'size': len(resp_get.content),
                    'content_preview': resp_get.text[:1000]
                }
        except:
            pass
        return None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(check_file, f) for f in common_files]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                results[result['file']] = result
    
    return results

# ---------- Main Endpoint ----------
@app.route('/extract', methods=['POST'])
@app.route('/extract', methods=['POST'])
def extract():
    start_time = time.time()

    try:
        data = request.get_json() or {}
        url = data.get('website_url', '').strip()
        mode = data.get('mode', 'advanced').lower()  # <-- DEFAULT advanced

        if not url:
            return jsonify({'error': 'website_url is required'}), 400

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        print(f"🔍 Extracting: {url} | Mode: {mode}")

        # ---------------- BASIC MODE ----------------
        if mode == "basic":
            try:
                resp = requests.get(url, headers=HEADERS, timeout=7)
                soup = BeautifulSoup(resp.text, "html.parser")

                tech = detect_tech_hints(resp.text, resp.headers)
                links = list(set(a.get("href") for a in soup.find_all("a", href=True)))[:50]

                basic_result = {
                    "mode": "basic",
                    "target_url": url,
                    "status_code": resp.status_code,
                    "security_headers": dict(resp.headers),
                    "tech_stack": tech,
                    "endpoints": links,
                    "extraction_time": round(time.time() - start_time, 2)
                }
                return jsonify(basic_result)

            except Exception as e:
                return jsonify({"error": str(e), "message": "Basic extraction failed"}), 500

        # ---------------- ADVANCED MODE ----------------
        elif mode == "advanced":
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                crawl_future = executor.submit(deep_crawl, url, 30)
                files_future = executor.submit(scan_all_files, url)

                try:
                    headers_resp = requests.get(url, headers=HEADERS, timeout=5)
                    headers_info = dict(headers_resp.headers)
                except:
                    headers_info = {}

                try:
                    pages_data = crawl_future.result(timeout=30)
                    files_data = files_future.result(timeout=15)
                except concurrent.futures.TimeoutError:
                    pages_data = []
                    files_data = {}

            # All URLs found
            all_urls = set()
            for page in pages_data:
                all_urls.add(page['url'])
                for link in page.get('links', {}).get('internal', []):
                    if link.get('full_url'):
                        all_urls.add(link['full_url'])

            result = {
                "mode": "advanced",
                "extraction_summary": {
                    "target_url": url,
                    "total_pages_extracted": len(pages_data),
                    "total_urls_found": len(all_urls),
                    "total_files_found": len(files_data),
                    "extraction_time": round(time.time() - start_time, 2)
                },
                "website_structure": {
                    "pages": pages_data[:5],
                    "all_urls": list(all_urls)[:100],
                    "sitemap_urls": get_all_urls_from_sitemap(url)[:50]
                },
                "technical_data": {
                    "headers": headers_info,
                    "detected_files": files_data,
                    "file_types_found": list(files_data.keys()),
                    "technology_hints": pages_data[0]['technology_hints'] if pages_data else []
                },
                "content_analysis": {
                    "total_forms": sum(len(page.get('forms', [])) for page in pages_data),
                    "total_images": sum(len(page.get('images', [])) for page in pages_data),
                    "total_scripts": sum(len(page.get('scripts', [])) for page in pages_data),
                    "total_links": sum(page.get('links', {}).get('total', 0) for page in pages_data),
                    "word_count": sum(page.get('word_count', 0) for page in pages_data)
                },
                "llm_ready_data": {
                    "pages_count": len(pages_data),
                    "forms_count": sum(len(page.get('forms', [])) for page in pages_data),
                    "endpoints_found": len(all_urls),
                    "technologies": pages_data[0]['technology_hints'] if pages_data else []
                }
            }
            return jsonify(result)

        else:
            return jsonify({"error": "mode must be 'basic' or 'advanced'"}), 400

    except Exception as e:
        return jsonify({"error": str(e), "message": "Internal error"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'Deep Website Extractor',
        'version': '1.0',
        'description': 'Extracts EVERYTHING from websites for LLM processing'
    })

if __name__ == '__main__':
    print("🚀 Starting Deep Website Extractor on port 6000...")
    print("📦 Extracts: Pages, Forms, Links, Images, Scripts, Styles, Headers, Files, Content")
    print("🎯 Purpose: Provide complete website data for LLM analysis")
    app.run(host='0.0.0.0', port=6000, debug=False, threaded=True)


    ######################

    
#curl -X POST http://127.0.0.1:6000/extract -H "Content-Type: application/json" -d "{\"website_url\":\"https://safesecureaudit.in\", \"mode\":\"advance\"}"
#curl -X POST http://127.0.0.1:6000/extract -H "Content-Type: application/json" -d "{\"website_url\":\"https://safesecureaudit.in\", \"mode\":\"basic\"}"
