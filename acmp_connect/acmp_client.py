"""Structured ACMP operations. No source code is executed locally."""
import http.cookiejar
import json
import re
import time
import urllib.parse
import uuid
from dataclasses import asdict
from bs4 import BeautifulSoup
from .client import (Client, ACMPError, BASE, ENC, authenticated_user, language,
                     task_statement, text, final_verdict)

MAX_SOURCE = 131072


def positive(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2_147_483_647:
        raise ACMPError('ID must be a positive 32-bit integer.')
    return value


def safe_course_url(value):
    url = urllib.parse.urlsplit(urllib.parse.urljoin(BASE + '/asp/do/index.asp', value))
    q = urllib.parse.parse_qs(url.query)
    if (url.scheme != 'https' or url.netloc != 'acmp.ru' or url.path != '/asp/do/index.asp'
            or url.fragment or q.get('main') not in (['map'], ['section'], ['topic'], ['task'])):
        raise ACMPError('Expected an ACMP course, section, topic or task URL.')
    allowed = {'main', 'id_course', 'id_section', 'id_topic', 'id_problem'}
    if set(q) - allowed or any(len(v) != 1 for v in q.values()):
        raise ACMPError('Invalid course URL parameters.')
    for k, v in q.items():
        if k != 'main' and (not v[0].isascii() or not v[0].isdigit() or int(v[0]) <= 0):
            raise ACMPError('Invalid course identifier.')
    return url.path + '?' + urllib.parse.urlencode({k: v[0] for k, v in q.items()})


def structured_problem(page, number):
    statement = task_statement(page, number)
    start = re.search(r'ЗАДАЧА\s*№\s*' + str(number) + r'\b', page)
    fragment = page[start.start():]
    end = re.search(r'<h4\b|<form\b|<h2[^>]*>\s*Отправить', fragment, re.I)
    if end:
        fragment = fragment[:end.start()]
    soup = BeautifulSoup(fragment, 'html.parser')
    samples = []
    for table in soup.find_all('table'):
        if 'INPUT.TXT' not in table.get_text().upper() or 'OUTPUT.TXT' not in table.get_text().upper():
            continue
        for row in table.find_all('tr')[1:]:
            cells = row.find_all(['td', 'th'], recursive=False)
            if len(cells) >= 2:
                samples.append({'input': cells[-2].get_text('\n', strip=True),
                                'output': cells[-1].get_text('\n', strip=True)})
    sections = {}
    for heading in soup.find_all('h2'):
        parts = []
        for sibling in heading.next_siblings:
            if getattr(sibling, 'name', None) in {'h2', 'h4', 'form'}:
                break
            parts.append(str(sibling))
        sections[heading.get_text(' ', strip=True)] = text(''.join(parts))
    images = []
    for img in soup.find_all('img', src=True):
        url = urllib.parse.urljoin(BASE, img['src'])
        if urllib.parse.urlsplit(url).netloc == 'acmp.ru' and urllib.parse.urlsplit(url).scheme == 'https':
            images.append(url)
    limit = soup.find('i')
    return {'id': number, 'title': soup.h1.get_text(' ', strip=True),
            'url': f'{BASE}/index.asp?main=task&id_task={number}', 'statement': statement,
            'limits': limit.get_text(' ', strip=True) if limit else None,
            'sections': sections, 'examples': samples, 'images': images}


class ACMPClient(Client):
    def dump_cookies(self):
        return json.dumps([vars(c) for c in self.jar], ensure_ascii=True)

    def load_cookies(self, serialized):
        for item in json.loads(serialized):
            # Serialize Cookie attributes rather than executable pickle data.
            item['rest'] = item.pop('_rest', {})
            if item['domain'] not in {'acmp.ru', '.acmp.ru'}:
                raise ACMPError('Invalid stored cookie domain.')
            self.jar.set_cookie(http.cookiejar.Cookie(**item))

    def identity(self):
        return authenticated_user(self.request('/index.asp?main=task&id_task=1'))

    def problem(self, number):
        positive(number)
        return structured_problem(self.request(f'/index.asp?main=task&id_task={number}'), number)

    def submissions(self, user, task=None, submission_id=None, page_index=0):
        positive(user)
        path = f'/index.asp?main=status&id_mem={user}&id_res=0'
        if task is not None:
            path += f'&id_t={positive(task)}'
        if submission_id is not None:
            positive(submission_id)
        if page_index:
            path += f'&page={page_index}'
        page = self.request(path)
        soup = BeautifulSoup(page, 'html.parser')
        if not any(h.get_text(strip=True) == 'ID' for h in soup.find_all('th')):
            raise ACMPError('Cannot read submissions table; session expired or site format changed.')
        result = []
        for tr in soup.find_all('tr'):
            cells = tr.find_all('td', recursive=False)
            if len(cells) < 6 or not cells[0].get_text(strip=True).isdigit():
                continue
            owner = None
            for a in cells[2].find_all('a', href=True):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(a['href']).query)
                if q.get('main') == ['user'] and q.get('id', [''])[0].isdigit():
                    owner = int(q['id'][0])
            if owner != user:
                continue
            task_id = None
            for a in cells[3].find_all('a', href=True):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(a['href']).query)
                val = q.get('id_task', [''])[0]
                if val.isdigit():
                    task_id = int(val)
                elif q.get('main') == ['task'] and a.get_text(strip=True).isdigit():
                    task_id = int(a.get_text(strip=True))
            if not task_id or (task and task_id != task):
                continue
            identifier = int(cells[0].get_text(strip=True))
            verdict = cells[5].get_text(' ', strip=True)
            try:
                final = final_verdict(verdict)
                state = 'final' if final else 'pending'
            except ACMPError:
                final, state = None, 'unknown'
            result.append({'id': identifier, 'user': user, 'task': task_id, 'verdict': final or verdict,
                           'state': state, 'compiler': cells[4].get_text(' ', strip=True),
                           'test': cells[6].get_text(' ', strip=True) if len(cells) > 6 else None,
                           'time': cells[7].get_text(' ', strip=True) if len(cells) > 7 else None,
                           'memory': cells[8].get_text(' ', strip=True) if len(cells) > 8 else None,
                           'url': f'{BASE}/index.asp?main=source&id={identifier}',
                           'diagnostics': 'Only the verdict and fields exposed by ACMP are available; compiler logs are not guaranteed.'})
        return result

    def diagnostics(self, identifier):
        # Only call after independently verifying ownership in the status table.
        page = self.request(f'/index.asp?main=source&id={positive(identifier)}')
        soup = BeautifulSoup(page, 'html.parser')
        logs = []
        for node in soup.find_all('font', color=re.compile(r'^red$', re.I)):
            content = text(str(node))
            if re.search(r'error|ошибк|компилятор', content, re.I):
                logs.append(content)
        return '\n'.join(logs)[:16000] or None

    def matches_source(self, identifier, source):
        # Independently match the stored source, rather than attributing an
        # unrelated browser upload merely because its row appeared after POST.
        page = self.request(f'/index.asp?main=source&id={positive(identifier)}')
        soup = BeautifulSoup(page, 'html.parser')
        candidates = []
        for node in soup.find_all('script'):
            if node.get('type', '').casefold() == 'syntaxhighlighter':
                value = node.string or ''
                match = re.fullmatch(r'\s*<!\[CDATA\[(.*)\]\]>\s*', value, re.S)
                if match:
                    candidates.append(match[1])
        normalize = lambda value: value.replace('\r\n', '\n').strip('\n')
        return len(candidates) == 1 and normalize(candidates[0]) == normalize(source.decode(ENC))

    def upload(self, number, compiler, source):
        boundary = 'acmp' + uuid.uuid4().hex
        body = bytearray()
        for name, value in [('lang', compiler.encode(ENC)), ('source', source)]:
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(value + b'\r\n')
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="fname"; filename=""\r\nContent-Type: application/octet-stream\r\n\r\n\r\n--{boundary}--\r\n'.encode())
        return self.request(f'/index.asp?main=update&mode=upload&id_task={number}', bytes(body),
                            {'Content-Type': f'multipart/form-data; boundary={boundary}',
                             'Referer': f'{BASE}/index.asp?main=task&id_task={number}'})

    def topic(self, query):
        if not query or len(query) > 500:
            raise ACMPError('Provide a topic name or ACMP course URL (up to 500 characters).')
        if '/' in query or '?' in query:
            path = safe_course_url(query)
        else:
            # Discover all first-course sections from the current course map.
            root = '/asp/do/index.asp?main=map&id_course=1'
            soup = BeautifulSoup(self.request(root), 'html.parser')
            links = {}
            sections = set()
            def collect(doc, base):
                for a in doc.find_all('a', href=True):
                    q = urllib.parse.parse_qs(urllib.parse.urlsplit(a['href']).query)
                    if q.get('main') not in (['topic'], ['section']):
                        continue
                    try:
                        url = safe_course_url(urllib.parse.urljoin(BASE + base, a['href']))
                    except ACMPError:
                        continue
                    if q['main'] == ['topic']:
                        links[url] = a.get_text(' ', strip=True)
                    else:
                        sections.add(url)
            collect(soup, root)
            for section in sorted(sections)[:40]:
                collect(BeautifulSoup(self.request(section), 'html.parser'), section)
            tokens = set(re.findall(r'\w+', query.casefold()))
            ranked = sorted(((len(tokens & set(re.findall(r'\w+', title.casefold()))), url, title)
                             for url, title in links.items()), reverse=True)
            if not ranked or ranked[0][0] == 0:
                raise ACMPError('Topic not found. Supply its exact ACMP URL, especially for courses other than course 1.')
            best = [x for x in ranked if x[0] == ranked[0][0]]
            if len(best) != 1:
                return {'candidates': [{'url': BASE + u, 'title': t} for _, u, t in best], 'tasks': []}
            path = best[0][1]
        page = self.request(path)
        soup = BeautifulSoup(page, 'html.parser')
        selected = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query).get('id_topic')
        tasks, seen = [], set()
        for a in soup.find_all('a', href=True):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(a['href']).query)
            if q.get('main') != ['task'] or 'id_problem' not in q or (selected and q.get('id_topic') != selected):
                continue
            label = a.get_text(' ', strip=True)
            m = re.match(r'^([A-Z]+)\.\s*(.+)', label)
            if not m:
                continue
            url = safe_course_url(urllib.parse.urljoin(BASE + path, a['href']))
            if url in seen:
                continue
            seen.add(url)
            if len(tasks) >= 60:
                raise ACMPError('Topic exceeds 60 tasks; use a narrower topic URL.')
            problem_page = self.request(url)
            title = BeautifulSoup(problem_page, 'html.parser').title
            match = re.match(r'\s*(\d+)\.', title.get_text() if title else '')
            if not match:
                raise ACMPError('Cannot map course problem to archive ID; site format changed.')
            tasks.append({'letter': m[1], 'title': m[2], 'id': int(match[1]), 'course_url': BASE + url})
        if not tasks:
            raise ACMPError('No lettered problems found at this topic URL.')
        return {'url': BASE + path, 'tasks': tasks, 'candidates': []}
