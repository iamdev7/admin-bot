Run the bot after deploy
- ssh -i ~/.ssh/bot-key.pem -o IdentitiesOnly=yes ec2-user@13.62.57.59
- cd /home/ec2-user/admin-bot
- source .venv/bin/activate
- python -m bot.main



تمام ✅
بما إن البوت شغّال في venv، أفضل حل يخليه يشتغل بالخلفية ويُعاد تشغيله تلقائيًا بعد أي فشل أو بعد إعادة تشغيل السيرفر هو **systemd**. (البدائل السريعة: `tmux` أو `nohup`—أذكرها آخر الرد).

## الخيار المُوصى به: خدمة systemd

1. أنشئ خدمة باسم `admin-bot.service`:

```bash
sudo tee /etc/systemd/system/admin-bot.service >/dev/null <<'UNIT'
[Unit]
Description=Admin Bot (Python)
After=network-online.target
Wants=network-online.target

[Service]
User=ec2-user
Group=ec2-user
WorkingDirectory=/home/ec2-user/admin-bot
# لو تطبيقك يقرأ .env بنفسه عبر python-dotenv خلّيه؛
# أو احذف السطر التالي إذا ما تحتاج تحميل متغيرات من systemd:
EnvironmentFile=/home/ec2-user/admin-bot/.env
ExecStart=/home/ec2-user/admin-bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=5
# Logs to journald
StandardOutput=journal
StandardError=journal
# تحسين بسيط للأمان
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
```

> ملاحظات:
>
> * تأكد أن المسارات صحيحة عندك.
> * ملف `.env` بصيغة `KEY=VALUE` سطر لكل متغيّر (من دون `export`).
>   إذا تطبيقك يحمّل `.env` بنفسه، تقدر تحذف سطر `EnvironmentFile=`.

2. فعّلها وشغّلها الآن ولجميع الإقلاعات القادمة:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now admin-bot
```

3. فحص الحالة واللوجات:

```bash
sudo systemctl status admin-bot -n 40
journalctl -u admin-bot -f
```

4. أوامر الإدارة:

```bash
sudo systemctl restart admin-bot
sudo systemctl stop admin-bot
sudo systemctl disable admin-bot
```

> لديك سكربت النشر الذي يدعم `--service`، فبعد أي نشر:
>
> ```bash
> ./scripts/deploy.sh --service admin-bot
> ```
>
> سيعمل إعادة تشغيل للخدمة تلقائيًا.

---

## بدائل سريعة (لو ما تبغى systemd الآن)

### 1) tmux (موصى به أكثر من nohup)

```bash
tmux new -s adminbot -d "/home/ec2-user/admin-bot/.venv/bin/python -m bot.main"
tmux ls          # تشوف الجلسات
tmux attach -t adminbot
# لإنهاء العملية:
tmux kill-session -t adminbot
```

### 2) nohup (أبسط، لكن لا يُعيد التشغيل عند الفشل)

```bash
nohup /home/ec2-user/admin-bot/.venv/bin/python -m bot.main \
  >/home/ec2-user/admin-bot/admin-bot.out 2>&1 &
echo $! > /home/ec2-user/admin-bot/admin-bot.pid
# إيقاف:
kill "$(cat /home/ec2-user/admin-bot/admin-bot.pid)"
```

---

## تشيك ليست سريعة

* شغّل الخدمة: `sudo systemctl enable --now admin-bot` ✅
* تأكد أنها تعمل بعد ريستارت السيرفر: **نعم** لأنها enabled.
* راقب اللوجات: `journalctl -u admin-bot -f`.
* بعد أي نشر: `./scripts/deploy.sh --service admin-bot`.

لو حاب أضبط لك **health check** بسيط داخل الخدمة (ExecStartPre/ExecStartPost) أو **rolling restart** بعد النشر، قلّي و أجهزه لك مباشرة.
