# Telegram Schedule Bot

Bot pengingat jadwal kerja via Telegram.

## Setup

### 1. Buat Bot Token
1. Buka Telegram, cari **@BotFather**
2. Ketik `/newbot`
3. Ikuti instruksi untuk nama bot
4. Simpan token yang diberikan

### 2. Install Dependencies
```bash
cd telegram_schedule_bot
pip install -r requirements.txt
```

### 3. Set Bot Token
```bash
export TELEGRAM_BOT_TOKEN="YOUR_TOKEN_HERE"
```

Atau edit `bot.py`, ganti `YOUR_BOT_TOKEN_HERE` dengan token Anda.

### 4. Jalankan Bot
```bash
python bot.py
```

## Commands

| Command | Deskripsi |
|---------|-----------|
| `/start` | Mulai bot |
| `/help` | Panduan lengkap |
| `/add [judul] [hari] [jam]` | Tambah jadwal |
| `/list` | Lihat semua jadwal |
| `/today` | Jadwal hari ini |
| `/delete [id]` | Hapus jadwal |
| `/clear` | Hapus semua jadwal |

## Contoh Penggunaan

```
/add Meeting client Senin 09:00
/add Lunch break tomorrow 12:30
/add Daily report daily 17:00
/add Review meeting 15/04/2026 10:00
```

## Format Hari

- `Senin`, `Selasa`, `Rabu`, `Kamis`, `Jumat`, `Sabtu`, `Minggu`
- `today` - hari ini
- `tomorrow` - besok
- `daily` - setiap hari
- `DD/MM/YYYY` - tanggal spesifik (15/04/2026)

## Reminder

Bot akan mengirim notifikasi 15 menit sebelum jadwal dimulai.

## Hosting

Untuk menjalankan 24/7, gunakan:
- VPS/Cloud server
- Railway.app (gratis)
- Render.com (gratis)
- Your MacBook (selama online)

## Stop Bot

Tekan `Ctrl+C` di terminal.