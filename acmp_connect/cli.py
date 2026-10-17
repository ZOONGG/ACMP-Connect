import argparse
import os
import sys
from pathlib import Path

from .client import ACMPError, Client, task_statement


def positive(value):
    try:
        number = int(value)
        if number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('нужно положительное целое число')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='acmp-connect')
    commands = parser.add_subparsers(dest='command', required=True)
    task = commands.add_parser('task', help='получить условие')
    task.add_argument('number', type=positive)
    submit = commands.add_parser('submit', help='отправить одно решение')
    submit.add_argument('number', type=positive)
    submit.add_argument('file', type=Path)
    submit.add_argument('--confirm', action='store_true', required=True, help='подтвердить реальную отправку')
    submit.add_argument('--timeout', type=positive, default=180, help='ожидание вердикта в секундах (180)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'task':
            print(task_statement(Client().request(f'/index.asp?main=task&id_task={args.number}'), args.number))
            return 0
        if args.file.suffix.lower() not in {'.c', '.cpp'} or not args.file.is_file():
            raise ACMPError('Укажите один существующий файл .c или .cpp.')
        login, password = os.environ.get('ACMP_LOGIN'), os.environ.get('ACMP_PASSWORD')
        if not login or not password:
            raise ACMPError('Задайте ACMP_LOGIN и ACMP_PASSWORD в окружении.')
        result = Client().submit(args.number, args.file, login, password, args.timeout,
                                 report=lambda message: print(message, flush=True))
        print(f'{result.id}: {result.verdict}')
        return 0 if result.verdict == 'Accepted' else 1
    except ACMPError as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Прервано. Если отправка началась, проверьте статус вручную; повтора нет.', file=sys.stderr)
        return 130
