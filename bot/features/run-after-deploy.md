Run the bot after deploy
- ssh -i ~/.ssh/bot-key.pem -o IdentitiesOnly=yes ec2-user@13.62.57.59
- cd /home/ec2-user/admin-bot
- source .venv/bin/activate
- python -m bot.main