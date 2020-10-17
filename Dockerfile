FROM python:3-alpine

WORKDIR /usr/travian

COPY . .

RUN apk add --update --no-cache --virtual .build-dependencies \
  gcc \
  musl-dev \
  curl \
  && pip3 install -r requirements.txt \
  && apk del .build-dependencies

EXPOSE 80

HEALTHCHECK --interval=1m --timeout=3s \
  CMD curl --fail http://localhost/inactive || exit 1

CMD ["python3", "-u", "main.py"]
