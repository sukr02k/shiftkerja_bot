# Deploy Telegram Bot ke Coolify

## 1. Upload ke VPS

```bash
scp -r telegram_schedule_bot user@your-vps-ip:/home/user/telegram_schedule_bot
```

## 2. Deploy via Coolify

### Option A: Deploy from Docker Compose

1. Login Coolify dashboard
2. Create new Project → "Schedule Bot"
3. Add new Service → "Docker Compose"
4. Set repository atau upload `docker-compose.yml`
5. Deploy

### Option B: Deploy from Git

1. Push code ke GitHub/GitLab
2. Coolify → New Project → Connect Git repo
3. Set Dockerfile sebagai build source
4. Deploy

## 3. Set Environment Variable

Di Coolify dashboard:
- Service → Environment Variables
- Add: `TELEGRAM_BOT_TOKEN` = `8798147711:AAFju12aVbLNEeQDSXGy0vzjoBWyUHjyLGM`

## 4. Deploy & Start

- Click "Deploy" button
- Bot akan running 24/7
- Logs dapat dilihat di Coolify dashboard

## 5. Verify Bot

Di Telegram:
- Ketik `/start`
- Ketik `/help`

## Troubleshooting

- Check logs di Coolify → Service → Logs
- Pastikan port tidak diblok firewall
- Volume untuk `schedules.db` agar data persist

## Stop Bot

- Coolify → Service → Stop/Delete