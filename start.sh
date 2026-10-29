#!/bin/bash

CONTAINER="planapp-mcp"

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "Removendo container existente: ${CONTAINER}"
    docker rm -f "${CONTAINER}"
fi

echo "Iniciando ${CONTAINER}..."

docker run -d \
  --name "${CONTAINER}" \
  --network features_default \
  -p 8010:8010 \
  -v /home/ciseiadmin/planapp-mcp:/app \
  planapp-mcp:latest

echo
echo "Container iniciado:"
docker ps --filter "name=${CONTAINER}"
