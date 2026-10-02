# Incident Vectorizer

Индексатор Jira Server/Data Center REST API v2 и Confluence через atlassian-manager → внешний embedder → Vespa.
Логика выгрузки и нормализации перенесена из `incident_vector_db`, структура
приложения соответствует `vectorizer`: FastAPI, Dishka, `src/common`, `core`,
`services`, `repositories`, `models`, `routers`, `interfaces`, bootstrap/application.
Python 3.11+, uv, Docker с Compose v2. PostgreSQL не используется.

## Настройка

```bash
cp .env.example .env
uv sync --locked
```

Заполните Jira URL, Bearer token, JQL и адрес OpenAI-совместимого embedder.
`.env` автоматически читается приложением; не загружайте его через `source`:
JQL содержит пробелы. Секреты не добавляются в Git.

В `.env.example` указаны модель `drawais/Qwen3-Embedding-4B-AWQ-INT4`,
префикс `passage: ` и размерность 2048. Endpoint должен
возвращать именно такую размерность. Проверяются количество, индексы,
размерность и конечность значений ответа. `INCIDENT_EMBEDDER_BATCH_SIZE`
ограничивает батчи сервиса эмбеддингов; индексатор обрабатывает тикеты по одному
для независимой обработки ошибок.

## Запуск в Docker

```bash
docker compose up -d vespa
# Дождитесь готовности config server (healthcheck контейнера).
docker compose exec vespa vespa-deploy prepare /app
docker compose exec vespa vespa-deploy activate
docker compose up -d --build api-gateway
curl --fail http://localhost:8001/api/v1/ready
```

Vespa хранит данные в именованном volume. API публикуется на порту `8001` всех интерфейсов.
Vespa публикует порты 8083 (HTTP) и 19072 (config server); API имеет выход
к Jira и embedder. Для embedder на хосте доступно имя `host.docker.internal`;
endpoint на хосте должен принимать соединения с Docker bridge.
Образ Vespa закреплён на major 8; для воспроизводимого production-развёртывания
закрепите проверенный digest вашего окружения.

CLI внутри уже запущенного API-контейнера использует тот же lock, что HTTP:

```bash
docker compose exec api-gateway jira-index
docker compose exec api-gateway jira-dump PROJ-123
```

`jira-dump` выводит исходный JSON тикета и все страницы комментариев;
ему нужны только настройки Jira. Вывод содержит данные тикета.

## Локальная разработка

```bash
docker compose up -d vespa
docker compose exec vespa vespa-deploy prepare /app
docker compose exec vespa vespa-deploy activate
```

Для локального Python задайте в `.env` `INCIDENT_VESPA_URL=http://localhost:8083`
и доступный с хоста `INCIDENT_EMBEDDER_BASE_URL`. Основной Compose публикует порты Vespa 8083 и 19072.

```bash
uv run jira-dump PROJ-123
uv run jira-index
uv run incident-vectorizer
```

## HTTP

```bash
curl http://localhost:8001/api/v1/ping
curl --fail http://localhost:8001/api/v1/ready
curl --max-time 3600 -X POST http://localhost:8001/api/v1/index \
  -H 'Content-Type: application/json' -d '{}'
```

POST выполняется до завершения прохода. Ответ:

```json
{"processed": 10, "changed": 3, "failed": 0}
```

`processed` — количество попыток обработки, включая неудачные; `changed` —
подтверждённые записи; `failed` — ошибки отдельных тикетов. При частичном сбое
HTTP возвращает 200 с `failed > 0`, CLI — код 1. Сбой обхода страниц Jira или
служебных операций завершает HTTP-запрос кодом 502 и CLI кодом 1. Readiness
возвращает 503, если Vespa или схемы недоступны. Повторный параллельный запуск —
HTTP 409 / CLI 1. При разрыве HTTP-соединения работа в серверном потоке может
продолжаться до завершения; для продолжительных загрузок удобнее CLI.

## Поиск ближайшего тикета

Передайте описание и комментарии одной строкой или через stdin:

```bash
uv run python find_closest_ticket.py 'Описание инцидента. Комментарий оператора.' --vespa-url http://localhost:8083
cat incident.txt | uv run python find_closest_ticket.py - --vespa-url http://localhost:8083
```

Скрипт читает `INCIDENT_EMBEDDER_*` и `INCIDENT_VESPA_*` из `.env`, как индексатор.
Из API-контейнера адрес Vespa обычно `http://vespa:8080`; с хоста используйте
опубликованный порт Compose (`8083` в основном файле). Результат — JSON с
`ticket_id`, `text`, `status`, `updated_at_jira` и `relevance`; `null` означает,
что документов нет.

Сначала скрипт отправляет текст в OpenAI-совместимый endpoint embedder
`POST /v1/embeddings` с той же моделью и префиксом, что использует индексатор.
Затем он отправляет в Vespa `POST /search/` запрос `nearestNeighbor` к полю
`embedding`, передавая вектор как `input.query(q_embedding)`. Указаны
`targetHits:1`, `hits:1` и `ranking:semantic`. Скрипт задаёт
`approximate:false`, поэтому Vespa ищет точного ближайшего соседа; на большом
индексе это может быть медленнее поиска через HNSW.

Поиск задаётся в двух местах. `vespa-app/schemas/incident.sd` определяет поле
вектора, метрику `angular`, индекс HNSW, тип входного вектора и ранжирование
`semantic` через `closeness`. Сам запрос, число результатов и точный режим
задаются в `find_closest_ticket.py`. `vespa-app/services.xml` подключает поиск
и тип документа к сервису Vespa. Профиль `bm25` в схеме предназначен для
текстового поиска и этим скриптом не используется.

Размерность вектора должна совпадать у embedder, проиндексированных документов
и развёрнутой схемы Vespa. В обеих схемах (`incident` и `confluence_page`), настройках по умолчанию
и `.env.example` используется 2048. Embedder должен возвращать 2048 значений.


## Данные и повторные запуски

Один тикет — один документ `incident`, ID равен Jira key. Хранятся `ticket_id`,
`text`, `status`, `content_hash`, `updated_at_jira`, `updated_at_db`, `embedding`
и `embedding_model_version`. Текст содержит описание и все комментарии,
отсортированные по времени создания и ID. Формат и SHA-256 сохранены из исходника.
Даты хранятся в ISO 8601 с часовым поясом.

При неизменившемся тексте и конфигурации embedder существующий вектор сохраняется.
Смена только статуса или даты не вызывает embedder. Идентификатор конфигурации
учитывает endpoint, модель, размерность и префикс (ключ доступа не входит).
Полностью неизменившийся документ не записывается заново.

Каждый запуск `jira-index` и POST `/api/v1/index` обходит весь настроенный JQL,
сохраняя проверку изменений и повторно используя неизменные векторы.
Флаг `--full`, настройка overlap и checkpoint больше не используются.
HTTP-запрос не требует тела; результат содержит только `processed`, `changed`, `failed`.
После смены модели достаточно повторно запустить `jira-index`.
Старая схема `index_checkpoint` оставлена в Vespa для совместимости развёртывания,
но приложение её не читает, не записывает и не проверяет в readiness.

Полный текст передаётся без обрезки и разбиения. При превышении лимита модели
тикет считается неуспешным, его предыдущая версия сохраняется. Ошибки необходимо
устранить перед повторным запуском. Удалённые из Jira/выборки
тикеты автоматически не удаляются. Перенос данных PostgreSQL, расписание,
HTTP API поиска и распределённые worker-ы не входят в этот сервис.

Поддерживается одна установка с одним HTTP worker. CLI и HTTP должны использовать
один `INCIDENT_LOCK_FILE` на общей файловой системе. Не запускайте параллельно
индексатор на хосте и в отдельном контейнере без общего lock volume.

## Проверки

```bash
uv run pytest -q
uv run ty check src main.py
uv build
docker compose config --quiet
docker build -t incident-vectorizer:local .
```

Тесты не обращаются к рабочим Jira/embedder. Интеграционная проверка на пустой
тестовой Vespa запускается отдельно (создаёт документы `SMOKE-1`, `CONFLUENCE-SMOKE-1`):

```bash
INCIDENT_TEST_VESPA_URL=http://localhost:8083 uv run pytest -q tests/test_integration.py
```

## Confluence

Задайте `CONFLUENCE_INDEXER_BASE_URL` — базовый URL atlassian-manager
(порт 8002 в примере условный: укажите порт вашей установки).
Для uv используйте адрес, доступный с хоста; для Docker — имя сервиса в общей
сети или `host.docker.internal`. Compose добавляет это имя через host-gateway.
Сервис на хосте должен принимать соединения из Docker.
Настройки Confluence требуются только при запуске его индексации.

| Переменная | Значение по умолчанию |
| --- | --- |
| `CONFLUENCE_INDEXER_BASE_URL` | Обязательный URL |
| `CONFLUENCE_INDEXER_SPACE_KEY` | Все доступные пространства |
| `CONFLUENCE_INDEXER_PAGE_SIZE` | 100, диапазон 1–1000 |
| `CONFLUENCE_INDEXER_TIMEOUT` | 120 секунд |

Индексатор вызывает `GET /api/v1/confluence/records` без заголовка авторизации,
с `content_type=page`, `body_format=text`, `page_size` и необязательным `space_key`.
`max_results` не передаётся. Пагинацию выполняет atlassian-manager; весь ответ
загружается в память. Каждый запуск получает всю выборку, без checkpoint и `--full`.

```bash
uv run confluence-index
# После запуска API через uv run incident-vectorizer:
curl --max-time 3600 --fail -X POST http://localhost:8001/api/v1/index/confluence
# Или CLI в работающем Compose-контейнере:
docker compose exec api-gateway confluence-index
```

Одна страница — один документ `confluence_page`, ID равен `id` записи.
`text` содержит `body` без изменений; заголовок не добавляется. Текст не режется
и не разбивается на части. Используются те же модель, префикс и 2048-мерный
embedder, что и для Jira. При неизменных SHA-256 текста и версии embedder
вектор сохраняется; изменение только даты не вызывает embedder. Полностью
неизменный документ не перезаписывается. `updated_at_confluence` берётся из
`updated_at`, при отсутствии даты сохраняется пустая строка.

Пустой/null body или ошибка отдельной записи увеличивают `failed`; предыдущая
версия документа сохраняется. Остальные записи продолжают обрабатываться.
Ответ использует те же счётчики, что Jira: `processed`, `changed`, `failed`.
Частичный сбой — HTTP 200 и CLI 1; сбой получения ответа — HTTP 502 и CLI 1;
занятый общий с Jira lock — HTTP 409 и CLI 1. Удаления не синхронизируются.

После обновления кода повторно выполните `vespa-deploy prepare /app` и
`vespa-deploy activate` из инструкции выше, затем перезапустите API.
Readiness проверяет обе рабочие схемы. В `confluence_page` доступны `bm25`,
`semantic` и `weighted`; последний вычисляет
`0.5 * closeness(field, embedding) + 0.5 * bm25(text)`.
Смена конфигурации embedder требует повторного запуска `confluence-index`,
а для Jira — `jira-index`.

## Запуск образа из Dockerfile без Compose

Сначала разверните приложение `vespa-app` в доступной Vespa. В отдельном
файле `.env.docker` задайте доступные из контейнера URL Vespa, embedder и
atlassian-manager. Для Vespa на хосте из приведённого Compose используйте
`INCIDENT_VESPA_URL=http://host.docker.internal:8083`.

```bash
docker build -t incident-vectorizer:local .
docker run -d --name incident-vectorizer \
  --env-file .env.docker --add-host host.docker.internal:host-gateway \
  -p 8001:8001 incident-vectorizer:local
docker exec incident-vectorizer jira-index
docker exec incident-vectorizer confluence-index
curl --fail http://localhost:8001/api/v1/ready
```

Обе команды внутри контейнера используют общий lock с HTTP API.
Не запускайте параллельно индексацию с хоста без общего lock volume.

## JSON одной страницы Confluence

```bash
uv run confluence-dump 123456
docker compose exec api-gateway confluence-dump 123456
```

Команда требует только настройки `CONFLUENCE_INDEXER_*`, запрашивает
`body_format=text` и печатает полный JSON выбранной записи, включая `body`,
заголовок и остальные метаданные. Исходный body сохраняется без изменений.
API не поддерживает фильтр по ID, поэтому команда получает всю настроенную
выборку и выбирает запись локально. `CONFLUENCE_INDEXER_SPACE_KEY` ограничивает
поиск. Если ID не найден или запрос завершился ошибкой, код выхода — 1;
сообщение об ошибке выводится в stderr. Vespa и embedder не вызываются.

## Принудительная переиндексация

```bash
uv run jira-index-force
uv run confluence-index-force
# В работающем контейнере:
docker compose exec api-gateway jira-index-force
docker compose exec api-gateway confluence-index-force
```

Обе команды обходят всю настроенную выборку (JQL для Jira, выбранные пространства
для Confluence), заново вычисляют embedding и записывают каждый документ,
даже если текст и версия embedder не изменились. Обычные команды `jira-index`
и `confluence-index` продолжают переиспользовать неизменные векторы.
Успешная принудительная запись увеличивает `changed`. Общая блокировка,
обработка ошибок и коды выхода совпадают с обычными командами; ошибка embedder
сохраняет предыдущий документ. Документы за пределами выборки не удаляются.
