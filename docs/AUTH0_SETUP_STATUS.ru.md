# Состояние Auth0: 2026-10-17

Tenant: `dev-7hq02dz6g07g73nf.us.auth0.com`.
Настройка выполнена официальным Auth0 CLI 1.37.0 через Management API.
Railway не изменялся. Секреты приложений и CLI-токены в проект не сохранялись.

| Ресурс | ID | Состояние |
| --- | --- | --- |
| ChatGPT MCP | `2PBChVXHPlHBmexzzVTFZhuRpzFtwUyw` | Regular Web, first-party, OIDC, code + refresh, client_secret_post |
| ACMP Connect Portal | `uwOgCGOyfQNtfvUDJPv8GuokjG2ii9gU` | Regular Web, first-party, OIDC, только code, client_secret_post |
| ACMP Connect Private Login | `a9a067f6-6c17-41c1-8cfa-a69d65719ce1` | Node 22, Post Login v3, deployed, подключена к Login flow |
| ACMP Connect API | — | Ожидает настоящий HTTPS origin; Identifier нельзя выдумывать |

`resource_parameter_profile=compatibility` уже был включён. Default Audience пуст.
ChatGPT refresh tokens: rotation, максимум 30 суток, idle 7 суток, overlap 3 секунды.
Implicit, Password и Client Credentials у обоих приложений отключены.
Callback URL пока пусты. Discovery подтверждает S256, client_secret_post и OIDC scopes.
Tenant также объявляет `plain`; Action проекта отклоняет его для этих двух клиентов.

Обоим приложениям включена только `Username-Password-Authentication`,
саморегистрация в ней отключена. Google connection им отключена.
Остальные приложения tenant не менялись.

Action загружена из `docs/auth0-private-login.js`. В Auth0 настроены её параметры
`CHATGPT_CLIENT_ID`, `PORTAL_CLIENT_ID`, `ALLOWED_USER_IDS`.
Allowlist сейчас пуст (`[]`): доступ закрыт всем, включая refresh.
В tenant пока нет пользователей приложения. Администратор Auth0 и пользователь
вашего приложения — разные учётные записи; CLI login пользователя приложения не создаёт.

## Что осталось

1. Получить реальный HTTPS origin сервера. Скрипт создаст API с audience
   `ORIGIN/mcp`, RS256, lifetime 900 секунд, scopes `acmp:read`, `acmp:submit`,
   `acmp:manage`, Allow Offline Access, без RBAC. Portal callback будет
   `ORIGIN/connect/callback`. До этого API и его scopes существуют только как
   подготовленная конфигурация в скрипте, а не как ресурс tenant.
2. Скопировать точный callback со страницы подключения ChatGPT.
3. Создать приватного пользователя database connection и передать его `user_id`
   в `AllowedUserIds`. Пароль задаётся приватно, не в чате или командной строке.
4. После появления адресов проверить реальный OAuth login, resource-bound JWT
   и refresh. Они пока не проверены: callbacks пусты, сервер не развёрнут.
5. Секреты приложений позднее взять непосредственно в Auth0 Dashboard и перенести
   в приватные настройки соответствующих клиентов. Здесь они не выводились.

## Повторный запуск

Из корня проекта: `./scripts/configure-auth0.ps1`.
Скрипт использует CLI-сессию и явно выбранный tenant; ищет существующие приложения
и Action перед созданием. Повторный запуск проверен: IDs сохранились, дубликатов нет.
Без параметров существующие callbacks и allowlist сохраняются.

Когда адреса известны, передайте параметры `-Origin`, `-ChatGPTCallback`,
`-AllowedUserIds`. Не передавайте шаблоны или wildcard. `AllowedUserIds` принимает
массив точных Auth0 user ID; указание параметра заменяет allowlist.
Ветка создания API пока не выполнялась: отсутствует origin.

Проверено через повторное чтение Management API: приложения, grants, connections,
disable_signup, deployed Action, Login flow binding, наличие имён её параметров.
Восемь локальных проверок Action прошли: S256, отсутствие PKCE, plain,
посторонний пользователь, пустой allowlist, разрешённый/запрещённый refresh,
нецелевой клиент. Это не заменяет реальный OAuth тест.

Источники: [Auth0 CLI](https://auth0.github.io/auth0-cli/),
[Management API OpenAPI](https://auth0.com/docs/oas/management/v2/management-api-oas.json),
[PKCE enforcement](https://support.auth0.com/center/s/article/Enforce-PKCE-with-Actions),
[refresh rotation](https://auth0.com/docs/secure/tokens/refresh-tokens/configure-refresh-token-rotation).
