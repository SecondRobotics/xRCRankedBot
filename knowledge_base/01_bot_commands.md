# Bot Commands

## Available Commands

### /ping
- **Description**: Check bot latency and responsiveness
- **Usage**: `/ping`
- **Response**: Shows bot latency in milliseconds

### /playerinfo
- **Description**: Get detailed player statistics including ELO, win/loss record, favorite games
- **Usage**: `/playerinfo [user]`
- **Parameters**: 
  - `user` (optional): Discord user to get stats for. If not provided, shows your own stats
- **Features**:
  - Shows ELO ratings for all games
  - Win/loss/tie records
  - Total points scored
  - Average ELO across all games
  - Best game performance
  - Favorite game (most played)

### /question
- **Description**: Ask questions about bot features or game mechanics
- **Usage**: `/question [your_question]`
- **Parameters**:
  - `question`: Your question about the bot or xRC games
- **Features**: AI-powered responses using local LLM