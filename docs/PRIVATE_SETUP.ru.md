# Первое приватное подключение: Auth0 → Railway → ChatGPT

Проверено по документации 2026-10-16. Auth0 частично настроен 2026-10-17:
актуальные ресурсы и оставшиеся шаги — в [AUTH0_SETUP_STATUS.ru.md](AUTH0_SETUP_STATUS.ru.md).
Railway service и домен ещё не созданы. Адреса ниже остаются шаблонами.

## Выбранный вариант

Auth0: один API и два **first-party Regular Web Applications**, заранее
зарегистрированные оператором: `ACMP ChatGPT` и `ACMP Portal`. ChatGPT получает
свой client ID/secret в настройках подключения, портал — через Railway variables.
Секрет ChatGPT серверу ACMP не нужен. Оба приложения используют одну Auth0
connection и одного пользователя. Это минимальный путь для одной личной
интеграции: не нужны собственный OAuth-сервер, DCR, CIMD и Management API.
Не выбирайте Machine to Machine.

First-party здесь означает способ регистрации клиента в вашем tenant,
а не официальную интеграцию с ACMP. DCR/CIMD оставлены за рамками первого
подключения: у Auth0 third-party клиентов есть отдельные ограничения, в том
числе на OIDC scopes, которые ChatGPT может запрашивать из discovery.

## 1. Подготовить аккаунты и окончательные адреса

Нужны Auth0 tenant с доступом к настройкам приложений/API, Railway workspace
с возможностью подключить volume и ChatGPT web с правом добавлять custom MCP.
GitHub нужен только при выборе сборки из приватного GitHub-репозитория.
Платный AI API не нужен. ACMP-аккаунт для проверки `get_problem` не нужен.

После отдельного подтверждения расходов и деплоя выберите Railway HTTPS hostname.
Обозначения ниже:

| Обозначение | Значение |
| --- | --- |
| `ORIGIN` | `https://<выданный-домен>.up.railway.app`, без `/` в конце |
| `RESOURCE` / API Identifier / audience | `ORIGIN/mcp`, без `/` в конце |
| `ISSUER` | `https://<tenant>.<region>.auth0.com/` — точное значение из discovery |
| MCP URL | `ORIGIN/mcp` |
| Portal callback | `ORIGIN/connect/callback` |

Не смешивайте Auth0 tenant domain и custom domain. Смена домена потребует
обновления audience, callbacks, PUBLIC_URL и переподключения ChatGPT.

## 2. Настроить Auth0

1. Создайте API `ACMP Connect`, Identifier = `RESOURCE`, signing algorithm
   **RS256**, access token lifetime, например, 900 секунд. Добавьте permissions
   `acmp:read`, `acmp:submit`, `acmp:manage`. Для первого запуска оставьте API RBAC
   выключенным; если включаете его, назначьте эти permissions пользователю.
   Поле `permissions` не заменяет строку `scope`, которую проверяет сервер.
2. В Tenant Settings → Advanced включите **Resource Parameter Compatibility
   Profile** (`resource_parameter_profile=compatibility`). ChatGPT передаёт
   `resource`, а Auth0 должен выпустить JWT с `aud=RESOURCE`. Default Audience
   не используйте как замену: он скрывает ошибку привязки ресурса.
3. Создайте `ACMP ChatGPT`: Regular Web Application, first-party, OIDC conformant,
   Authorization Code; отключите Implicit, Password и Client Credentials.
   Token endpoint authentication = **Post** (`client_secret_post`). Включите
   нужную connection. Разрешите `openid`, `profile`, `email`, если они объявлены
   discovery. Если API access policy требует client grant, разрешите этому
   приложению API и выбранные scopes.
4. Callback для ChatGPT скопируйте **точно из страницы управления подключением**
   в Allowed Callback URLs Auth0. Он может быть
   `https://chatgpt.com/connector/oauth/{callback_id}` либо
   `https://chatgpt.com/connector_platform_oauth_redirect`; выбор зависит от
   issuer identification провайдера. Не вводите шаблон с фигурными скобками и
   не используйте wildcard. Если интерфейс показывает callback после создания,
   сохраните подключение, внесите callback в Auth0 и повторите OAuth.
5. Создайте `ACMP Portal`: отдельный first-party Regular Web Application,
   Authorization Code, authentication **Post**, OIDC/`openid`, callback строго
   `ORIGIN/connect/callback`. Включите ту же connection. Портал уже генерирует
   PKCE S256, state и nonce; API audience ему не нужен.
6. Для приватного tenant отключите самостоятельную регистрацию в database
   connection, создайте единственного тестового пользователя и отключите
   посторонние/social connections у обоих приложений. Если tenant уже содержит
   других пользователей, ограничьте оба client ID allowlist по `event.user.user_id`
   через Auth0 Post Login Action до подключения. Скрытый в каталоге плагин сам
   по себе не ограничивает доступ к выдаче токенов.
7. Оба клиента должны использовать authorization code + **S256 PKCE**. ChatGPT
   отправляет challenge сам. Для first-party клиентов не считайте наличие PKCE
   в discovery гарантией его обязательности: включите enforcement провайдера
   либо Post Login Action, отклоняющий для этих двух client ID code login без
   `event.request.query.code_challenge` или с методом, отличным от `S256`.
   Refresh-token транзакции исключите из проверки challenge. Проверка:
   запрос без PKCE отклоняется, S256 проходит. Не включайте `plain`.
   Готовый вариант: [auth0-private-login.js](auth0-private-login.js). В Auth0
   Actions создайте Post Login Action, вставьте код, добавьте secrets
   `CHATGPT_CLIENT_ID`, `PORTAL_CLIENT_ID`, `ALLOWED_USER_IDS` (JSON-массив,
   например `["auth0|ВАШ_USER_ID"]`), Deploy и добавьте Action в Login flow.
   Заполните оба client ID: Action действует только для них. Она также
   ограничивает доступ allowlist пользователя, включая refresh. Сам Action
   не выдаёт токены и не заменяет OAuth-провайдер. В реальном tenant ещё не проверен.
8. Для длительной сессии включите API **Allow Offline Access**, grant
   Refresh Token у ChatGPT client и rotation с конечным временем жизни.
   Убедитесь, что OAuth-запрос включает `offline_access`. Без этого первый
   вызов возможен, но после истечения access token понадобится новый login.

Discovery Auth0: `ISSUER.well-known/openid-configuration` (то есть
`https://<tenant-domain>/.well-known/openid-configuration`). Проверьте точный
`issuer`, `authorization_endpoint`, `token_endpoint`, `jwks_uri`, наличие
`S256` в `code_challenge_methods_supported` и `client_secret_post` в
`token_endpoint_auth_methods_supported`. Не добавляйте собственный discovery
или флаг `authorization_response_iss_parameter_supported` поверх Auth0.
API access token должен иметь `iss=ISSUER`, `aud`, включающий `RESOURCE`,
`sub`, `iat`, `exp`, строку `scope` с `acmp:read`. ID token портала имеет
audience его client ID. `iss` и `sub` одного пользователя должны совпадать
между клиентами; сервер не сопоставляет пользователей по email.

## 3. Railway — только после подтверждения ресурсов и деплоя

Создайте один service из Dockerfile и один volume в том же регионе, mount
`/data`. Один instance, один worker; без multi-region и перекрывающихся
экземпляров. Volume подключается при старте, не на build/pre-deploy.
Оставьте Docker ENTRYPOINT; он готовит права volume и сбрасывает root до
UID/GID 10001. Healthcheck `/healthz`, timeout 60 секунд. Target port `8000`
при переменной `PORT=8000`. Включите HTTPS domain с действительным сертификатом.
Свой TLS внутри контейнера не нужен: Railway завершает TLS на proxy.

Шаблон `.railway/railway.ts` соответствует опубликованным полям IaC, но не
применялся и не проходил реальный Railway plan. Source задаётся отдельно.
Перед apply проверьте конкретный план ресурсов; UI достаточно для первого запуска.

| Railway variable | Значение |
| --- | --- |
| `PUBLIC_URL` | `ORIGIN` |
| `OAUTH_ISSUER` | точный `issuer` из discovery, обычно с `/` в конце |
| `OAUTH_JWKS_URL` | `jwks_uri` из discovery |
| `OIDC_AUTHORIZATION_ENDPOINT` | `authorization_endpoint` из discovery |
| `OIDC_TOKEN_ENDPOINT` | `token_endpoint` из discovery |
| `PORTAL_CLIENT_ID` | client ID **ACMP Portal** |
| `PORTAL_CLIENT_SECRET` | secret **ACMP Portal**, приватная переменная |
| `SESSION_ENCRYPTION_KEY` | один постоянный Fernet key, приватная переменная |
| `DATABASE_PATH` | `/data/acmp.sqlite3` |
| `ACMP_DEV` | `0` |
| `PORT` | `8000` |
| `SUBMISSION_INTERVAL` | `30` |
| `ACMP_SESSION_TTL` | `604800` |

Ключ создайте локально и сохраните отдельно от резервной копии БД:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Переменной `OAUTH_AUDIENCE` здесь нет: сервер вычисляет audience как
`PUBLIC_URL + '/mcp'`. Не переносите секрет ChatGPT client в `PORTAL_CLIENT_SECRET`.
Не меняйте Fernet key при redeploy; БД, WAL и encrypted tickets должны переживать
рестарт. Для резервных копий используйте SQLite backup API либо остановку сервиса.

После разрешённого деплоя выполните из PowerShell (подставьте реальный origin):

```powershell
$acmpOrigin = 'https://<реальный-домен>'
Invoke-RestMethod "$acmpOrigin/healthz"
Invoke-RestMethod "$acmpOrigin/.well-known/oauth-protected-resource/mcp"
curl.exe -i -X POST "$acmpOrigin/mcp" -H 'Content-Type: application/json' --data '{}'
```

Ожидается: health `ok`; metadata с точным `RESOURCE`, `ISSUER` и тремя scopes;
последний запрос — **401** и `WWW-Authenticate` с `resource_metadata`.
Проверьте также корневой `/.well-known/oauth-protected-resource`.
Это проверяет HTTPS/discovery, но не заменяет реальный OAuth login.

## 4. Подключить ChatGPT и проверить только чтение

В ChatGPT web откройте [Plugins](https://chatgpt.com/plugins) → плюс →
**Add custom MCP server**. URL = `RESOURCE`, authentication = **OAuth**,
static client ID/secret = **ACMP ChatGPT**, не Portal. Перенесите точный callback
в Auth0, завершите login/consent и установите плагин только для себя.
Если интерфейс позволяет выбрать scopes, начните с `acmp:read`; для всех
инструментов нужны также `acmp:submit` и `acmp:manage`. В настройках инструментов
на время проверки отключите все, кроме `get_problem`.

В новом чате выберите `@ACMP Connect` и отправьте:

> Вызови только get_problem с аргументами {"problem_id": 1} через ACMP Connect.
> Покажи название, условие и примеры. Не отправляй решения, не подключай ACMP
> аккаунт и не вызывай другие инструменты.

В деталях вызова должны быть `get_problem`, `problem_id=1` и structured result
с названием `A+B`. Проверяйте именно tool call, а не только текст ответа модели.
Этот инструмент читает публичную задачу; пароль ACMP и `/connect` не нужны.
После успеха проверьте повторный вызов после истечения access token и рестарта
сервиса: это отдельно проверит refresh/relogin и постоянное хранилище.

Если возвращается 401: сначала проверьте точные `iss`, `aud=RESOURCE`, `scope`
и Resource Parameter Compatibility Profile. Не отключайте JWT validation.
Если consent сообщает missing permissions — проверьте API permissions,
client grants/RBAC и повторите подключение. При callback error сверяйте точный
URL и metadata issuer, включая завершающий `/`.

## Граница готовности

Код resource server, PKCE портала, JWT validation, discovery, Docker и шаблон
Railway подготовлены. Локальные тесты используют mock identity provider и
mock ACMP. Реальный Auth0 login, выдача resource-bound JWT, callback ChatGPT,
refresh и HTTPS Railway должны быть проверены после внешней настройки.
Точный MCP URL пока неизвестен: домен service ещё не выделен.

Источники: [OpenAI OAuth](https://developers.openai.com/plugins/build/auth),
[ChatGPT custom MCP](https://developers.openai.com/api/docs/guides/custom-mcp-server),
[Auth0 MCP](https://auth0.com/blog/auth0-auth-for-mcp-servers-generally-available/),
[Auth0 resource parameter](https://auth0.com/docs/api/authentication/authorization-code-flow-with-pkce/authorize-with-pkce),
[Auth0 third-party limitations](https://auth0.com/docs/get-started/applications/third-party-applications/security-controls),
[Railway IaC](https://docs.railway.com/infrastructure-as-code/reference),
[Railway volumes](https://docs.railway.com/volumes/reference).
