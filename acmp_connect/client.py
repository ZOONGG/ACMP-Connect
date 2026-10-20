"""Protocol adapted from hanglider/ACMP tools/acmp.py (MIT; see LICENSE)."""
import http.cookiejar
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://acmp.ru"
ENC = "windows-1251"


class ACMPError(Exception):
    pass


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        elif not self.skip:
            if tag == "br":
                self.parts.append("\n")
            elif tag == "sup":
                self.parts.append("^")
            elif tag == "img":
                src = dict(attrs).get("src", "")
                self.parts.append(f" [Изображение: {urllib.parse.urljoin(BASE, src)}] ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        elif not self.skip:
            if tag in {"p", "div", "tr", "h1", "h2", "h3", "li"}:
                self.parts.append("\n")
            elif tag in {"td", "th"}:
                self.parts.append(" | ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def text(html):
    parser = Text()
    parser.feed(html)
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", line).strip(" |\r ")
                     for line in "".join(parser.parts).splitlines()
                     if line.strip(" |\r\xa0 \t"))


def task_statement(page, number):
    match = re.search(r"ЗАДАЧА\s*№\s*" + str(number) + r"\b", page)
    if not match:
        raise ACMPError(f"Задача №{number} не найдена или формат страницы изменился.")
    fragment = page[match.start():]
    end = re.search(r"<h4\b|<form\b", fragment, re.I)
    if end:
        fragment = fragment[:end.start()]
    if not re.search(r"<h1\b", fragment, re.I):
        raise ACMPError("Не удалось разобрать условие задачи.")
    return text(fragment)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.urls.append(dict(attrs).get("href", ""))


def query_links(page):
    parser = Links()
    parser.feed(page)
    return [urllib.parse.parse_qs(urllib.parse.urlsplit(u).query) for u in parser.urls]


class SessionPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.header = True
        self.password = False
        self.upload = False
        self.logout = False
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        # Parse real elements: CSS, comments and script text are not boundaries.
        if 'menu_title' in attrs.get('class', '').split() or tag == 'h1':
            self.header = False
        if tag == 'form':
            action = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, attrs.get('action', '')))
            query = urllib.parse.parse_qs(action.query)
            if (action.netloc == 'acmp.ru' and query.get('main') == ['update']
                    and query.get('mode') == ['upload']):
                self.upload = True
        if not self.header:
            return
        if tag == 'input' and (attrs.get('name', '').lower() == 'password'
                               or attrs.get('type', '').lower() == 'password'):
            self.password = True
        if tag == 'a':
            url = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, attrs.get('href', '')))
            if url.netloc != 'acmp.ru':
                return
            query = urllib.parse.parse_qs(url.query)
            self.logout |= query.get('main') == ['exit']
            key = 'id' if query.get('main') == ['user'] else (
                'id_mem' if query.get('main') == ['status'] else None)
            values = query.get(key, [])
            if len(values) == 1 and values[0].isascii() and values[0].isdigit() and int(values[0]) > 0:
                self.ids.add(int(values[0]))


def authenticated_user(page):
    session = SessionPage()
    session.feed(page)
    # Current ACMP renders the account's My tasks link in the sidebar, not
    # the header. Its label and a header logout link are independent evidence.
    if session.logout and not session.password:
        from bs4 import BeautifulSoup
        ids = set()
        for link in BeautifulSoup(page, 'html.parser').find_all('a', href=True):
            if link.get_text(strip=True).casefold() not in {'мои задачи', 'my tasks', 'my problems'}:
                continue
            url = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, link['href']))
            query = urllib.parse.parse_qs(url.query)
            value = query.get('id', [''])[0]
            if url.netloc == 'acmp.ru' and query.get('main') == ['user'] and value.isascii() and value.isdigit() and int(value) > 0:
                ids.add(int(value))
        if len(ids) == 1 and (not session.ids or session.ids == ids):
            return ids.pop()
    # An account ID alone could be a public profile link. Require independent
    # session evidence and reject a remaining login form or conflicting IDs.
    if session.password or len(session.ids) != 1 or not (session.upload or session.logout):
        if re.search(r'(?:g-recaptcha|h-captcha|name=["\x27]?captcha|/captcha)', page, re.I):
            raise ACMPError("CAPTCHA required. Complete verification on acmp.ru; automated login stopped.")
        if session.password:
            raise ACMPError("Login rejected or session expired. Reconnect your ACMP account.")
        raise ACMPError("Cannot confirm account identity: ACMP page format changed.")
    return session.ids.pop()


@dataclass(frozen=True)
class Submission:
    id: int
    user: int
    task: int
    verdict: str


def status_rows(page):
    result = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr\s*>", page, re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td\s*>", row, re.I | re.S)
        if len(cells) < 6 or not text(cells[0]).isdigit():
            continue
        users = [q['id'][0] for q in query_links(cells[2]) if q.get('main') == ['user'] and q.get('id')]
        tasks = [q['id_task'][0] for q in query_links(cells[3]) if q.get('main') == ['task'] and q.get('id_task')]
        if users and tasks and users[0].isdigit() and tasks[0].isdigit():
            result.append(Submission(int(text(cells[0])), int(users[0]), int(tasks[0]), text(cells[5])))
    if not re.search(r"<th\b[^>]*>\s*ID\s*</th>", page, re.I):
        raise ACMPError("Не удалось прочитать таблицу отправок; возможно, сессия истекла.")
    return result


FINAL = {v.casefold(): v for v in (
    'Accepted', 'Wrong answer', 'Presentation error', 'Compilation error',
    'Runtime error', 'Time limit exceeded', 'Memory limit exceeded',
    'Output limit exceeded', 'Security violation', 'Restricted function',
    'Idleness limit exceeded', 'System error', 'Judgement failed')}


def final_verdict(value):
    value = ' '.join(value.split()).casefold()
    if value in FINAL:
        return FINAL[value]
    if not value or any(word in value for word in ('waiting', 'compiling', 'running', 'testing', 'queue', 'очеред', 'провер', 'компиля')):
        return None
    raise ACMPError(f"Неизвестный статус: {value!r}; итоговый вердикт не подтверждён.")


class Options(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_lang = False
        self.current = None
        self.options = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'select':
            self.in_lang = attrs.get('name') == 'lang'
        if tag == 'option' and self.in_lang:
            self.current = [attrs.get('value', ''), '']
            self.options.append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag == 'option':
            self.current = None
        if tag == 'select':
            self.in_lang = False
            self.current = None


def language(page, suffix, *, allow_cpp_fallback=False):
    parser = Options()
    parser.feed(page)
    candidates = [(v, label) for v, label in parser.options if v and
                  (('c++' in label.lower() or 'g++' in label.lower()) if suffix == '.cpp'
                   else bool(re.search(r'\bC\b(?!\+)', label, re.I)) and 'c++' not in label.lower())]
    if not candidates and suffix == '.c' and allow_cpp_fallback:
        candidates = [(v, label) for v, label in parser.options if v and
                      re.search(r'c\+\+|g\+\+', label, re.I) and
                      re.search(r'GNU|G\+\+', label, re.I)]
    if not candidates:
        raise ACMPError(f"На странице нет компилятора для {suffix}.")
    preferred = [item for item in candidates if re.search(r'GNU|G\+\+', item[1], re.I)]
    return (preferred or candidates)[-1][0]


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urllib.parse.urlsplit(newurl)
        if url.scheme != 'https' or url.netloc != 'acmp.ru':
            raise ACMPError("Отклонено перенаправление за пределы https://acmp.ru.")
        if req.data is not None and code in (307, 308):
            raise ACMPError("Повтор POST при перенаправлении запрещён.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), SafeRedirect())
        self.opener.addheaders = [('User-Agent', 'acmp-connect/0.2')]

    def request(self, path, data=None, headers=None):
        try:
            if not path.startswith('/') or path.startswith('//') or '\\' in path:
                raise ACMPError('Invalid ACMP path.')
            req = urllib.request.Request(BASE + path, data=data, headers=headers or {})
            with self.opener.open(req, timeout=30) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ACMPError('ACMP response exceeds size limit.')
                return raw.decode(response.headers.get_content_charset() or ENC)
        except urllib.error.HTTPError as exc:
            raise ACMPError(f"HTTP {exc.code}: сервер отклонил запрос.") from None
        except (OSError, urllib.error.URLError, UnicodeError, ValueError):
            raise ACMPError("Ошибка сети или ответа acmp.ru. Запрос не повторён.") from None

    def login(self, login, password, number):
        try:
            body = urllib.parse.urlencode({'lgn': login, 'password': password}, encoding=ENC).encode('ascii')
        except UnicodeError:
            raise ACMPError("Учётные данные содержат символы вне Windows-1251.") from None
        reply = self.request('/index.asp?main=enter', body, {'Content-Type': 'application/x-www-form-urlencoded'})
        if re.search(r'(?:g-recaptcha|h-captcha|name=["\x27]?captcha|/captcha)', reply, re.I):
            raise ACMPError('CAPTCHA required. Complete verification on acmp.ru; automated login stopped.')
        page = self.request(f'/index.asp?main=task&id_task={number}')
        user = authenticated_user(page)
        if 'mode=upload' not in page:
            raise ACMPError("Авторизация выполнена, но форма отправки недоступна.")
        return user, page

    def rows(self, user, number):
        page = self.request(f'/index.asp?main=status&id_mem={user}&id_res=0&id_t={number}')
        return [r for r in status_rows(page) if r.user == user and r.task == number]

    def submit(self, number, path, login, password, timeout=180, report=print):
        try:
            source = Path(path).read_text(encoding='utf-8-sig').encode(ENC)
        except (OSError, UnicodeError):
            raise ACMPError("Не удалось прочитать файл: нужен UTF-8 и символы, представимые в Windows-1251.") from None
        if not source.strip():
            raise ACMPError("Файл решения пуст.")
        user, page = self.login(login, password, number)
        compiler = language(page, Path(path).suffix.lower())
        before = max((r.id for r in self.rows(user, number)), default=0)
        boundary = 'acmp' + uuid.uuid4().hex
        body = bytearray()
        for name, value in [('lang', compiler.encode(ENC)), ('source', source)]:
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(value + b'\r\n')
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="fname"; filename=""\r\nContent-Type: application/octet-stream\r\n\r\n\r\n--{boundary}--\r\n'.encode())
        try:
            self.request(f'/index.asp?main=update&mode=upload&id_task={number}', bytes(body),
                         {'Content-Type': f'multipart/form-data; boundary={boundary}',
                          'Referer': f'{BASE}/index.asp?main=task&id_task={number}'})
        except ACMPError as exc:
            raise ACMPError(f"{exc} Отправка могла быть принята: проверьте статус вручную. Повтора нет.") from None
        deadline = time.monotonic() + timeout
        submission_id = None
        try:
            while time.monotonic() < deadline:
                rows = self.rows(user, number)
                if submission_id is None:
                    new = [r for r in rows if r.id > before]
                    if len(new) > 1:
                        raise ACMPError("Несколько новых отправок: нельзя однозначно определить отправку этого клиента.")
                    if new:
                        submission_id = new[0].id
                        report(f'ID отправки: {submission_id}')
                row = next((r for r in rows if r.id == submission_id), None)
                if row and (verdict := final_verdict(row.verdict)):
                    return Submission(row.id, user, number, verdict)
                time.sleep(min(3, max(0, deadline - time.monotonic())))
        except ACMPError as exc:
            raise ACMPError(f"{exc} Отправка уже выполнена; ID: {submission_id or 'не определён'}. Проверьте статус вручную; повтора нет.") from None
        raise ACMPError(f"Время ожидания истекло; ID: {submission_id or 'не определён'}. Проверьте статус вручную; повтора нет.")
