FROM python:3.7

COPY . /app

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

CMD python -u /app/mtb.py $OWNER_USERNAME $BOT_USERNAME $BOT_PASSWORD $DEFAULT_SUB $USER_AGENT $CLIENT_ID $CLIENT_SECRET $REDIRECT $TELEGRAM_TOKEN $TELEGRAM_OWNER_ID