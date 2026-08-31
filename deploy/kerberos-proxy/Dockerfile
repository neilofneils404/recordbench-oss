FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        apache2 curl krb5-user libapache2-mod-auth-gssapi \
    && a2enmod auth_gssapi headers proxy proxy_http \
    && a2dissite 000-default \
    && rm -rf /var/lib/apt/lists/*
COPY ports.conf /etc/apache2/ports.conf
COPY recordbench-auth.conf.template /etc/apache2/sites-available/recordbench-auth.conf.template
COPY entrypoint /usr/local/sbin/recordbench-auth-entrypoint
RUN chmod 0755 /usr/local/sbin/recordbench-auth-entrypoint
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD test "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8080/)" = 401
ENTRYPOINT ["/usr/local/sbin/recordbench-auth-entrypoint"]
CMD ["apachectl", "-D", "FOREGROUND"]
