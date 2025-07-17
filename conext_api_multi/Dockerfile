ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk update && apk add --no-cache python3 py3-pip nginx py3-requests py3-yaml \
    && pip3 install --no-cache-dir --break-system-packages pyModbusTCP flask flask-restful gunicorn \
    && rm -rf /var/cache/apk/*

WORKDIR /app

COPY solarmonitor.py /app/

COPY nginx.conf /etc/nginx/http.d/default.conf

RUN chmod +x /app/solarmonitor.py

EXPOSE 80

COPY run.sh /

RUN chmod a+x /run.sh

CMD ["/run.sh"]
