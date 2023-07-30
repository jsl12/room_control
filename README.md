# room_control
 
## Running with Docker

Needs to have a `requirements.txt` file in the same directory as the `Dockerfile`

```dockerfile
FROM python:3.10

# install order matters because of some weird dependency stuff with websocket-client
# install appdaemon first because it's versioning is more restrictive
RUN pip install git+https://github.com/AppDaemon/appdaemon@dev

ENV CONF=/conf
RUN mkdir $CONF
COPY ./requirements.txt ${CONF}
RUN --mount=type=cache,target=/root/.cache/pip pip install -r ${CONF}/requirements.txt
```

```yaml
version: "3.8"
services:
  appdaemon:
    container_name: appdaemon
    image: acockburn/appdaemon:dev
    volumes:
      - /etc/localtime:/etc/localtime:ro
      - /etc/timezone:/etc/timezone:ro
      - config:/conf
    ports:
      - 5050:5050
    restart: unless-stopped


volumes:
  config:
    driver: local
    driver_opts:
      o: bind
      type: none
      device: ./
```
