import os
import urllib.request
from urllib.parse import urlsplit


def main():
    request = urllib.request.Request('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz',
                                     headers={'Host': urlsplit(os.environ['PUBLIC_URL']).netloc})
    with urllib.request.urlopen(request, timeout=4) as response:
        if response.status != 200:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
