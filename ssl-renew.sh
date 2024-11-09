#!/bin/bash

docker compose run --rm certbot renew

# Reload nginx to pick up the new certificate
docker compose exec nginx nginx -s reload 