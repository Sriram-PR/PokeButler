# 🎩 PokeButler

[![Invite Bot](https://img.shields.io/badge/Discord-Invite%20PokeButler-7289DA?style=for-the-badge&logo=discord)](https://discord.com/oauth2/authorize?client_id=1425522581896822817&permissions=1376537406528&integration_type=0&scope=applications.commands+bot)

**PokeButler** is a high-performance Discord bot designed for competitive Pokemon players and casino game enthusiasts. It features deep integration with Smogon University data, robust fuzzy matching, and a fully-featured multiplayer Blackjack engine.

Built with **Python 3.12**, **Discord.py**, and **Docker**, it utilizes enterprise-grade patterns like Circuit Breakers, Connection Pooling, and Request Deduplication to ensure stability and speed.

---

## ✨ Features

### ⚔️ Competitive Pokemon Analysis

* **Smogon Movesets:** Fetch competitive sets (`/smogon`) with interactive dropdowns to switch between Generations (1-9) and Formats (OU, Uber, etc.) instantly.
* **Smart Fuzzy Matching:** Never worry about typos. If you type `Garchomp` as `Garchompp`, PokeButler knows what you meant.
* **EV Yields:** Quickly check Effort Value yields for efficient training (`/ev`).
* **Shiny Monitoring:** (Admin) Automatically detects shiny spawns from other bots (via Embed analysis) and archives them to a dedicated channel.

### 🃏 Multiplayer Blackjack

* **Casino Rules:** Implements H17 (Dealer hits soft 17), Double Down, Split (with sequential dealing), and Surrender.
* **Lobby System:** Play alone or challenge up to 3 friends in the same channel.
* **Visual Styles:** Dealer can toggle between **Custom Emojis** 🎨 for immersion or **Classic Text** 📝 for accessibility.
* **Quick Start:** Challenge a friend instantly with `.bj @user`.

### ⚙️ Technical Architecture

* **Resilience:** Implements **Circuit Breakers** to handle Smogon/PokeAPI outages gracefully without crashing the bot.
* **Efficiency:** Uses **Request Deduplication**. If 5 users request "Pikachu" simultaneously, only one API call is made.
* **Persistence:** SQLite database with automatic **LRU Cache Eviction** to manage memory and disk usage.
* **Security:** Docker container runs as a non-root user for maximum security.

---

## 🔗 Invite PokeButler

Add the bot to your server with one click:

**[🔗 Click here to Invite PokeButler](https://discord.com/oauth2/authorize?client_id=1425522581896822817&permissions=1376537406528&integration_type=0&scope=applications.commands+bot)**

---

## 🚀 Installation & Deployment (Self-Host)

### Prerequisites

* Docker & Docker Compose
* A Discord Bot Token ([Get one here](https://discord.com/developers/applications))

### 1. Clone the Repository

```bash
git clone https://github.com/Sriram-PR/PokeButler.git
cd pokebutler
```

### 2. Configuration

Create a `.env` file in the root directory:

```bash
cp .env.example .env
nano .env
```

**Required Variables:**

```ini
# Discord Bot Token
DISCORD_TOKEN=your_token_here

# Your Discord User ID (enables Admin commands)
OWNER_ID=1234567890

# (Optional) ID of another bot to monitor for Shiny spawns
TARGET_USER_ID=9876543210
```

### 3. Run with Docker (Recommended)

PokeButler is optimized for Docker. This handles dependencies, permissions, and persistence automatically.

```bash
# 1. Create the data folder with correct permissions (User ID 1000)
mkdir -p smogon-data
sudo chown -R 1000:1000 smogon-data

# 2. Build and Start
docker-compose up -d --build

# 3. View Logs
docker-compose logs -f
```

---

## 🛠️ Commands

### Pokemon

| Command | Description |
| :--- | :--- |
| `/smogon [mon] [gen]` | Fetch competitive sets (e.g., `/smogon garchomp gen9`). |
| `/sprite [mon] [shiny]` | View Pokemon sprites. |
| `/effortvalue [mon]` | Check EV yields (`/ev`). |
| `/dmgcalc` | Get a link to the damage calculator. |

### Blackjack

| Command | Description |
| :--- | :--- |
| `/blackjack start` | Open a lobby for multiplayer. |
| `/blackjack quick-start` | Start an instant 1v1 game (Slash command). |
| `.bj @user` | Start an instant 1v1 game (Prefix command). |
| `/blackjack showhand` | (Dealer) View hole card privately. |

### Admin / System

| Command | Description |
| :--- | :--- |
| `/status` | View health, latency, and cache stats. |
| `/shiny-channel [add/remove]`| Configure channels for shiny detection. |
| `/shiny-archive [set]` | Set a channel to archive shiny alerts. |
| `/cache-stats` | View API cache hit-rates (Owner only). |

---

## 📂 Project Structure

```text
.
├── bot.py                 # Entry point & shiny detection
├── config/
│   └── settings.py        # Configuration & validation
├── cogs/
│   ├── smogon.py          # Pokemon commands & UI
│   ├── blackjack.py       # Blackjack commands & UI
│   └── utility.py         # Admin & Help commands
├── utils/
│   ├── api_clients.py     # Async HTTP client + Circuit Breaker
│   ├── blackjack_game.py  # Game engine logic
│   ├── database.py        # SQLite handler
│   └── ...
└── Dockerfile             # Production-ready Docker build
```

---

## 💖 Acknowledgements & Assets

This project wouldn't be possible without the amazing work of the community. Special thanks to:

* **Smogon University** & **PokeAPI** for the data.
* **[hayeah/playing-cards-assets](https://github.com/hayeah/playing-cards-assets)** for the standard deck card assets used as references for our emojis.
* **[waydelyle/pokemon-assets](https://github.com/waydelyle/pokemon-assets)** for the type icon assets and inspiration.

---

## ⚖️ Legal & Disclaimer

**This project is licensed under the [MIT License](https://github.com/Sriram-PR/PokeButler/blob/main/LICENSE).**

**Disclaimer:**
Pokémon, Pokémon character names, and related assets are trademarks of **The Pokémon Company**, **Game Freak**, and **Nintendo**. This project is an unofficial, free, open-source fan project and is not affiliated with, endorsed, sponsored, or specifically approved by Nintendo or The Pokémon Company.

All trademarks and copyrights belong to their respective owners. The use of these assets in this project is believed to fall under "Fair Use" for educational and non-commercial purposes.
