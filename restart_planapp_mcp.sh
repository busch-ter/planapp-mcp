cd ~/planapp-mcp

docker build --no-cache -t planapp-mcp:latest .

docker stop planapp-mcp
docker rm planapp-mcp

docker run -d \
  --name planapp-mcp \
  --network features_default \
  -p 8010:8010 \
  planapp-mcp:latest
