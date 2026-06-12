# Docker и деплой на VPS

Бот упакован в Docker: секреты в `.env`, настройки стратегии в `config.yaml`, логи в папке `logs/` на хосте.

## Что внутри

| Файл | Назначение |
|------|------------|
| `Dockerfile` | Образ Python 3.12 + зависимости |
| `docker-compose.yml` | Сервис `bot` (live), профили `dry` и `tools` |
| `.env` | Ключи Hyperliquid и ntfy-топик (**не в git**) |
| `config.yaml` | Стратегия, live, notifications (монтируется в контейнер) |

## 1. Подготовка VPS

Подойдёт Ubuntu 22.04 / 24.04 (1 vCPU, 1 GB RAM достаточно).

Подключитесь по SSH:

```bash
ssh root@ВАШ_IP
```

Установите Docker:

```bash
apt update && apt install -y ca-certificates curl
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker
```

Проверка:

```bash
docker --version
docker compose version
```

Опционально — отдельный пользователь (без root):

```bash
adduser trader
usermod -aG docker trader
su - trader
```

## 2. Загрузка проекта на VPS

**Вариант A — git:**

```bash
cd ~
git clone <URL_ВАШЕГО_РЕПО> btc-trend-scalper
cd btc-trend-scalper
```

**Вариант B — архив с Windows:**

На своём ПК в папке проекта (без `.env` и `.venv`):

```powershell
tar -czf scalper.tar.gz --exclude=.venv --exclude=.env --exclude=logs .
scp scalper.tar.gz trader@ВАШ_IP:~/
```

На VPS:

```bash
mkdir -p ~/btc-trend-scalper && cd ~/btc-trend-scalper
tar -xzf ~/scalper.tar.gz
```

## 3. Секреты и конфиг

```bash
cd ~/btc-trend-scalper
cp .env.example .env
nano .env
```

Заполните:

```env
HYPERLIQUID_PRIVATE_KEY=0x...
HYPERLIQUID_WALLET_ADDRESS=0x...   # основной аккаунт с USDC, не API wallet
NTFY_TOPIC=ваш_логин_из_приложения_ntfy
```

Права на `.env`:

```bash
chmod 600 .env
```

При необходимости отредактируйте `config.yaml` (символ, плечо, bracket и т.д.).

## 4. Сборка и запуск

**Сначала dry-run** (без ордеров):

```bash
docker compose --profile dry up -d bot-dry
docker compose logs -f bot-dry
```

Остановить dry-run:

```bash
docker compose --profile dry down
```

**Live-торговля:**

В `docker-compose.yml` в `command` уже стоит `live -t 1h --confirm-live`.  
Другой таймфрейм — измените `-t 1h` на `15m`, `4h` и т.д.

```bash
docker compose build
docker compose up -d bot
docker compose logs -f bot
```

Логи на диске VPS: `./logs/bot_YYYY-MM-DD.log`.

## 5. Управление

| Действие | Команда |
|----------|---------|
| Статус | `docker compose ps` |
| Логи в реальном времени | `docker compose logs -f bot` |
| Перезапуск | `docker compose restart bot` |
| Остановка | `docker compose stop bot` |
| Удалить контейнер | `docker compose down` |
| Бэктест разово | `docker compose --profile tools run --rm backtest` |

**Обновление после правок кода:**

```bash
git pull   # или залейте новый архив
docker compose build --no-cache
docker compose up -d bot
```

**Обновление только `config.yaml`** (без пересборки):

```bash
nano config.yaml
docker compose restart bot
```

## 6. Автозапуск

В `docker-compose.yml` уже указано `restart: unless-stopped` — после перезагрузки VPS контейнер поднимется сам, если до этого был запущен через `docker compose up -d`.

## 7. Безопасность

- Не коммитьте `.env` в git.
- На VPS: `chmod 600 .env`.
- API-ключ Hyperliquid — только с правами торговли, без вывода средств.
- Рекомендуется firewall: `ufw allow OpenSSH && ufw enable` (порты для бота наружу не нужны).

## 8. Частые проблемы

| Симптом | Решение |
|---------|---------|
| Баланс $0 в уведомлении | Неверный `HYPERLIQUID_WALLET_ADDRESS` (нужен master, не API wallet) |
| Нет push от ntfy | Пустой `NTFY_TOPIC` или топик не подписан в приложении ntfy |
| Контейнер падает сразу | `docker compose logs bot` — часто пустой `.env` |
| Нет логов в `logs/` | Папка создаётся при старте; проверьте volume в compose |
| Сменить TF без правки compose | `docker compose run --rm bot live -t 15m --confirm-live` (разовый запуск) |

## Пример: только docker run (без compose)

```bash
docker build -t btc-trend-scalper .
docker run -d --name hype-scalper --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/config.yaml:/app/config.yaml:ro" \
  -v "$(pwd)/logs:/app/logs" \
  btc-trend-scalper:latest live -t 1h --confirm-live
```
