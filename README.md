# GeoGuessBot – A Discord-Based GeoGuessr Battle Royale Game

**GeoGuessBot** is a Discord bot that replicates a simplified version of GeoGuessr’s *Battle Royale* game mode. Players compete by guessing the country of a randomly chosen Google Street View location — all within a Discord channel.

---

## How It Works

- The bot shares a random location from **Google Street View**
- Players can:
  - **Move around** and **look around** using emoji reactions, similar to regular Street View
  - Submit their guess by **typing the name of a country** in the chat
- Players lose lives for incorrect guesses
- All incorrect guesses are shown with **country flags** in the game overview

---

## Features

- *Battle Royale* gameplay: players are eliminated after too many incorrect guesses  
- Interactive navigation: explore the scene as if using Street View  
- Live game state display: see all players, their remaining lives, and incorrect guesses  
- Incorrect guesses displayed as flags for everyone to see

---

## Screenshots

![Start of a round](./screenshots/start.png)  
*A sample randomly selected location*

![In-game UI](./screenshots/game-ui.png)  
*Game state with players, flags, and remaining lives*

---

## ⚠️ Note

Due to updates in the Discord.py API and Google Street View API, this bot may no longer function out of the box. However, the code remains available for educational purposes or further development.

---

## Built With

- Python  
- Discord.py (legacy version)  
- Google Street View Static API   
- async.io

