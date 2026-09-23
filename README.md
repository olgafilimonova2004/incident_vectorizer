# Incident Vectorizer

Индексатор Jira Server/Data Center REST API v2 → внешний embedder → Vespa.
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

По умолчанию используется модель `drawais/Qwen3-Embedding-4B-AWQ-INT4`,
префикс `passage: ` и размерность 2560, как в референсе. Endpoint должен
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

Vespa хранит данные в именованном volume. API слушает `127.0.0.1:8001`.
Внешние сети из референса не нужны. Сеть Vespa изолирована, API имеет выход
к Jira и embedder. Для embedder на хосте доступно имя `host.docker.internal`;
endpoint на хосте должен принимать соединения с Docker bridge.
Образ Vespa закреплён на major 8; для воспроизводимого production-развёртывания
закрепите проверенный digest вашего окружения.

CLI внутри уже запущенного API-контейнера использует тот же lock, что HTTP:

```bash
docker compose exec api-gateway jira-index
docker compose exec api-gateway jira-index --full
docker compose exec api-gateway jira-dump PROJ-123
```

`jira-dump` выводит исходный JSON тикета и все страницы комментариев;
ему нужны только настройки Jira. Вывод содержит данные тикета.

## Локальная разработка

```bash
docker compose -f docker-compose.yaml -f docker-compose-dev.yaml up -d vespa
docker compose exec vespa vespa-deploy prepare /app
docker compose exec vespa vespa-deploy activate
```

Для локального Python задайте в `.env` `INCIDENT_VESPA_URL=http://localhost:8080`
и доступный с хоста `INCIDENT_EMBEDDER_BASE_URL`. Dev override публикует
порты Vespa 8080 и 19071 только на loopback.

```bash
uv run jira-dump PROJ-123
uv run jira-index
uv run jira-index --full
uv run incident-vectorizer
```

## HTTP

```bash
curl http://localhost:8001/api/v1/ping
curl --fail http://localhost:8001/api/v1/ready
curl --max-time 3600 -X POST http://localhost:8001/api/v1/index \
  -H 'Content-Type: application/json' -d '{"full": false}'
```

POST выполняется до завершения прохода. Ответ:

```json
{"processed": 10, "changed": 3, "failed": 0, "checkpoint_advanced": true}
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
и развёрнутой схемы Vespa. В текущем `incident.sd` указано 2048, а в
`.env.example` — 2560; установите `INCIDENT_EMBEDDER_DIMENSIONS` в значение,
соответствующее **уже развёрнутой** схеме и используемой модели. Если модель
выдаёт другую размерность, понадобится новая схема и повторная индексация.

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

Checkpoint хранится отдельно в `index_checkpoint`, с ID по Jira URL и JQL.
Он сдвигается на максимальную дату успешно обработанных тикетов только после
полностью успешного прохода. При сбое старый checkpoint сохраняется; повторный
запуск безопасно повторяет записи. Первый/пустой проход не создаёт искусственную
границу. Overlap по умолчанию — 300 секунд. Как в исходнике, JQL-дата имеет
точность до минуты; часовой пояс пользователя Jira должен соответствовать поясу
дат API. При меняющейся во время обхода выдаче Jira offset-пагинация не даёт
снимка данных; overlap снижает риск пропусков, `--full` выполняет сверку всей выборки.

`--full` игнорирует границу checkpoint, сохраняя проверку изменений. После смены
модели выполните полный проход. Размерность зафиксирована в `incident.sd`
(поле embedding и query tensor): при её смене измените оба объявления и
`INCIDENT_EMBEDDER_DIMENSIONS`, подготовьте отдельный индекс Vespa с новой схемой
и заполните его через `--full` перед переключением потребителей. Не смешивайте
разные размерности в одном индексе.

Полный текст передаётся без обрезки и разбиения. При превышении лимита модели
тикет считается неуспешным, его предыдущая версия сохраняется. Ошибки необходимо
устранить, иначе checkpoint не будет продвигаться. Удалённые из Jira/выборки
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
тестовой Vespa запускается отдельно (создаёт документ `SMOKE-1` и checkpoint):

```bash
INCIDENT_TEST_VESPA_URL=http://localhost:8080 uv run pytest -q tests/test_integration.py
```
