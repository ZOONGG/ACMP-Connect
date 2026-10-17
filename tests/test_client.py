import unittest
from unittest.mock import patch

from acmp_connect.client import (
    ACMPError, Client, Submission, authenticated_user, final_verdict,
    language, status_rows, task_statement,
)
from acmp_connect.cli import main


def row(identifier=101, user=42, task=1, verdict='Accepted'):
    return (f'<tr><td>{identifier}</td><td>date</td>'
            f'<td><a href=/?main=user&amp;id={user}>name</a></td>'
            f'<td><a href=?main=task&id_task={task}>{task:04}</a></td>'
            f'<td>C++</td><td><span>{verdict}</span></td></tr>')


class ParsingTests(unittest.TestCase):
    def test_statement(self):
        page = '''sidebar ЗАДАЧА №1</td><h1>A+B</h1><p>Сложить A и B.</p>
        <h2>Входные данные</h2><p>До 10<sup>9</sup>.</p>
        <h2>Выходные данные</h2><p>Сумма.</p><h2>Пример</h2>
        <table><tr><th>INPUT.TXT</th><th>OUTPUT.TXT</th></tr>
        <tr><td><pre>2 3\n4 5</pre></td><td>5<br>9</td></tr></table>
        <h4>Для отправки необходимо авторизоваться</h4>footer'''
        result = task_statement(page, 1)
        for part in ('A+B', 'Входные данные', 'Выходные данные', 'INPUT.TXT | OUTPUT.TXT', '2 3', '5', '10^9'):
            self.assertIn(part, result)
        self.assertNotIn('footer', result)
        with self.assertRaises(ACMPError):
            task_statement(page, 2)

    def test_identity(self):
        upload = '<form action="/index.asp?main=update&amp;mode=upload&amp;id_task=1"></form>'
        self.assertEqual(authenticated_user('<a href=/?main=user&id=42>me</a><td class=menu_title>sidebar' + upload), 42)
        for page in ('<input name=password>', '<td class=menu_title><a href=/?main=user&id=42>x</a>',
                     '<a href=/?main=user&id=42>x</a><a href=/?main=user&id=43>y</a>' + upload,
                     '<a href=/?main=user&id=42>public profile</a>',
                     '<input type=password><a href=/?main=user&id=42>me</a>' + upload,
                     '<a href=/?main=user&id=42>me</a><a href=?main=status&id_mem=43>status</a>' + upload):
            with self.assertRaises(ACMPError):
                authenticated_user(page)

    def test_identity_uses_elements_and_multiple_signals(self):
        # Text in head/comments must not truncate the account header or look
        # like a password input. Class lists still delimit the sidebar.
        prefix = '''<style>/* class=menu_title */</style>
        <script>const hint = 'name=password';</script><!-- ЗАДАЧА №1 -->'''
        for identity in ('<a href=?main=user&amp;id=42>me</a>',
                         '<a href=?main=status&amp;id_mem=42>my attempts</a>'):
            page = (prefix + identity + '<a href=?main=exit>exit</a>'
                    '<td class="extra menu_title"><a href=?main=user&id=99>other</a>')
            self.assertEqual(authenticated_user(page), 42)
        with self.assertRaises(ACMPError):
            authenticated_user(prefix + '<td class="extra menu_title">' + row()
                               + '<a href=?main=exit>exit</a>')

    def test_login_checks_task_page_without_submitting(self):
        client = Client()
        page = ('<a href=?main=status&id_mem=42>my attempts</a><td class=menu_title>'
                '<form action="/index.asp?main=update&mode=upload&id_task=1"></form>')
        with patch.object(client, 'request', side_effect=['', page]) as request:
            self.assertEqual(client.login('тест', 'test&+pass', 1), (42, page))
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[0].args,
                             ('/index.asp?main=enter',
                              b'lgn=%F2%E5%F1%F2&password=test%26%2Bpass',
                              {'Content-Type': 'application/x-www-form-urlencoded'}))
            self.assertEqual(request.call_args_list[1].args,
                             ('/index.asp?main=task&id_task=1',))

    def test_languages(self):
        page = '''<select name=other><option value=bad>GNU C++</select>
        <select name=lang><option value=c>GNU C</option>
        <option value=cpp>GNU C++17</option><option value=vc>Visual C++</option></select>'''
        self.assertEqual(language(page, '.c'), 'c')
        self.assertEqual(language(page, '.cpp'), 'cpp')
        with self.assertRaises(ACMPError):
            language('<select name=lang><option value=cpp>C++</select>', '.c')

    def test_rows_and_verdicts(self):
        self.assertEqual(status_rows('<th>ID</th>' + row()), [Submission(101, 42, 1, 'Accepted')])
        with self.assertRaises(ACMPError):
            status_rows('login page')
        for value in ('Waiting', 'Compiling', 'Running test 3', 'Testing', 'В очереди', ''):
            self.assertIsNone(final_verdict(value))
        for value in ('Accepted', 'Wrong answer', 'Compilation error', 'Time limit exceeded', 'Runtime error'):
            self.assertEqual(final_verdict(value), value)
        with self.assertRaises(ACMPError):
            final_verdict('new unexpected status')


class StatusTests(unittest.TestCase):
    def run_submission(self, snapshots):
        client = Client()
        with patch('acmp_connect.client.Path.read_text', return_value='int main(){}'), \
             patch.object(client, 'login', return_value=(42, '<select name=lang><option value=cpp>GNU C++</select>')), \
             patch.object(client, 'rows', side_effect=snapshots), \
             patch.object(client, 'request') as request, \
             patch('acmp_connect.client.time.sleep'):
            try:
                return client.submit(1, 'solution.cpp', 'fake', 'fake', report=lambda _: None)
            finally:
                self.assertEqual(request.call_count, 1)  # upload is never retried

    def test_tracks_same_id(self):
        result = self.run_submission([
            [Submission(100, 42, 1, 'Accepted')],
            [Submission(101, 42, 1, 'Testing')],
            [Submission(102, 42, 1, 'Wrong answer'), Submission(101, 42, 1, 'Accepted')],
        ])
        self.assertEqual(result.id, 101)
        self.assertEqual(result.verdict, 'Accepted')

    def test_ambiguity_and_network_error(self):
        for snapshot in ([Submission(101, 42, 1, 'Accepted'), Submission(102, 42, 1, 'Accepted')], ACMPError('network')):
            with self.assertRaises(ACMPError):
                self.run_submission([[], snapshot])

    def test_missing_confirmation_never_connects(self):
        with patch('acmp_connect.cli.Client') as client, patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                main(['submit', '1', 'solution.cpp'])
            client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
