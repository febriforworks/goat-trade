# IDX Scrapper API (Goat Trade)

A Plug & Play backend for scraping and serving Indonesian Stock Exchange (IDX) data via Yahoo Finance. This project includes a FastAPI backend, background scraping scripts, and a PostgreSQL database.

## 🚀 Quick Start (Plug and Play)

This project uses Docker to make the setup process as seamless as possible. You don't need to manually install PostgreSQL or Python dependencies on your host machine.

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

### Step 1: Configuration
Copy the sample environment file and configure it if necessary:
```bash
cp .env.example .env
```
*(The default `.env` configuration works perfectly out of the box with Docker).*

#### 🔔 Telegram Alert Setup (Optional)
To receive screener signals directly on your phone:
1. Search for `@BotFather` on Telegram and send `/newbot`.
2. Follow the steps and copy the **HTTP API Token**.
3. Search for `@userinfobot` on Telegram to get your **Chat ID** (or use a group/channel ID).
4. Add them to your `.env` file:
   ```env
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

### Step 2: Run the Services
Start the database and the API server in the background:
```bash
docker-compose up -d
```
Docker will pull the necessary images, build the Python application, and spin everything up.

### Step 3: Verify
- The FastAPI application is now running and accessible at: **[http://localhost:8000](http://localhost:8000)**
- Interactive API Documentation (Swagger UI) is available at: **[http://localhost:8000/docs](http://localhost:8000/docs)**
- The PostgreSQL database is running on `localhost:5432`

## 🛠️ Usage

### Fetching Historical Data
If you want to run the backtester or screener, you might want to fetch historical data first. You can run the data fetcher script inside the container:
```bash
docker-compose exec api python scripts/fetch_past_daily.py
```

### Database Fix/Migration
To apply new database schema updates or additions, run:
```bash
docker-compose exec api python scripts/fix_db.py
```

### Running the Screener
To run the screener framework:
```bash
docker-compose exec api python app/services/screener.py
```

### Running the Backtester
To run the backtester:
```bash
docker-compose exec api python app/services/backtester.py
```

## 🛑 Stopping the Services
To stop the application and database, run:
```bash
docker-compose down
```
*(Your database data will persist in a Docker volume even if you take the containers down. If you want to wipe the database, run `docker-compose down -v`)*

## Lisensi
Projek ini dilisensikan dengan CC BY-NC 4.0. Lisensi ini membatasi Anda untuk tidak menggunakan data atau apapun yang berhubungan dengan projek ini untuk tujuan komersial.
