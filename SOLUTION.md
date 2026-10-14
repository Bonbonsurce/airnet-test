# Решение

## Затраченное время

Время разработки: около 2,5 часов.
Время настройки окружения: отдельно. Зеркало `deb.debian.org` для Debian 11 больше не отдаёт `libpq` из `bullseye-security` (404), поэтому в `backend/Dockerfile` источники APT переведены на `archive.debian.org`. Стек PHP 7.4 не менялся.

## Найденные причины

### 1. При быстром переключении открываются данные предыдущей заявки

Воспроизведение: войти как редактор, открыть заявку 101 (ответ ~1100 мс), сразу выбрать 102 (~100 мс). Карточка сначала показывает 102, затем подменяется данными 101.

Причина: `TicketPanel` не отменял устаревший ответ. `useEffect` всегда вызывал `setTicket` для любого завершившегося запроса. То же происходило с POST сохранения: ответ предыдущей заявки мог перезаписать текущую карточку.

Исправление: флаг `active` для загрузки, `selectedIdRef` для сохранения, показ карточки только если `ticket.id === selectedId`. Список всё равно обновляется через `onChanged`.

Проверка: параллельные GET 101 и 102 в `tools/test_api.py`; ручная проверка переключения 101→102 при `DEMO_LATENCY=1`.

### 2. Карточка заявки без источника загружается с ошибкой

Воспроизведение: открыть заявку 103 или `GET /api/tickets/103`.

Причина: `TicketRepository::find()` всегда читал `$source['id']` после `pg_fetch_assoc`. Для `source_id = NULL` источник не находится, обращение к полям `false` даёт 500.

Исправление: `LEFT JOIN` и `source: null`, если источника нет. Список уже отдавал `source_name: null`.

Проверка: сценарий «ticket without source returns source null (original 500)» в `tools/test_api.py`. На исходном коде он падает, после исправления проходит.

### 3. Сотрудник с правом только на просмотр смог изменить источник

Воспроизведение: войти как viewer и отправить `POST /api/tickets/105/source`.

Причина: сервер проверял только `FUNC_TICKETS_VIEW`. Кнопка на клиенте скрыта, но маршрут смены источника не требовал `FUNC_TICKETS_SOURCE_EDIT`. Архивная заявка тоже не проверялась.

Исправление: `requirePermission(..., 'FUNC_TICKETS_SOURCE_EDIT')` до изменения данных. Для редактора порядок: заявка существует → не архивная → корректный `source_id` → источник есть в справочнике. Обновление и история в одной транзакции. Повтор текущего источника — 200 без новой записи. Сотрудник берётся только из сессии.

Проверка: viewer 403, archived 403, невалидный ввод 400, повтор источника, успешная смена с сотрудником из сессии — все в `tools/test_api.py`.

## Решения и компромиссы

Серверные проверки оставлены в `TicketRepository` и маршруте, без нового слоя и без фреймворка. Валидацию `source_id` перенесли после проверки заявки и архива, чтобы соблюсти требуемый порядок. Транзакцию начинаем только после успешных проверок, чтобы `respond()`/`exit` не оставлял открытый `BEGIN` на worker.

На клиенте выбраны cancellation-флаг и ref, а не AbortController: PHP-задержки нужно сохранить, а отмена fetch не обязательна для корректного UI. Оптимистичную блокировку одновременного редактирования не добавляли — это не обязательная часть.

Альтернативы: optimistic concurrency (`updated_at` в POST), AbortController, отдельный middleware авторизации. Для объёма задания это лишнее.

## Запуск проверок

Приложение:

```sh
docker compose up --build
```

Инфраструктура:

```sh
python3 tools/smoke.py http://localhost:5173
```

Поведение:

```sh
python3 tools/test_api.py http://localhost:5173
```

Фактические результаты на этом окружении после `docker compose up --build`:

```
python3 tools/smoke.py http://localhost:5173
PASS: PHP 7.4, isolated database, session, list, sources, normal ticket

python3 tools/test_api.py http://localhost:5173
PASS: health
PASS: no session is 401 json
PASS: unauthenticated change is 401 json
PASS: viewer login
PASS: editor login
PASS: ticket without source returns source null (original 500)
PASS: list keeps null source_name
PASS: missing ticket is 404 json
PASS: viewer change is 403 and data is unchanged
PASS: archived ticket is 403 and data is unchanged
PASS: invalid source values are 400 without changes
PASS: editor change of missing ticket is 404 before source validation
PASS: viewer is rejected before ticket lookup
PASS: same source succeeds without history row
PASS: successful change is atomic and uses session employee
PASS: restore ticket 105 source
PASS: parallel ticket fetches keep matching payloads
All behaviour checks passed
```

`docker compose exec -T frontend npm run build` завершился успешно. API в журналах без 5xx на сценариях проверки.

## Одновременное редактирование

Защиты от lost update нет. Два редактора могут прочитать один и тот же `source_id`, оба успешно сохранить разные новые значения, и оба добавить записи в историю. Итог: побеждает последний `UPDATE`, в истории могут оказаться две записи с одинаковым `old_source_id`. Данные не откатываются, конфликт пользователю не показывается.

## Оставшиеся ограничения

Нет optimistic locking и нет отдельного браузерного автотеста на гонку карточки: её закрывает клиентский guard и ручная проверка с задержками. Снять источник через это действие по-прежнему нельзя — так требуется заданием.
